"""Import pipeline of the connectors: analyse a source model, map it, and create or update items and links.

Rules (same as the ReqIF import): every object keeps its source id as an external reference; a re-import updates
the item with a new version only when the source changed. When the item was also edited in Ariadne since the last
import, the source is *not* applied (reported as a conflict). Frozen items are reported, not changed. A dry run
executes everything inside a savepoint and rolls it back, so the preview is exact.
"""

from __future__ import annotations

import re
import uuid
from collections import Counter
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from almlight.core import richtext
from almlight.core.errors import DomainError, ValidationFailed
from almlight.modules.audit import service as audit
from almlight.modules.connectors.base import ExtModel, ExtObject, Suggestion, norm
from almlight.modules.identity.models import User
from almlight.modules.integrations.models import ExternalRef
from almlight.modules.io.reqif_import import _field_value
from almlight.modules.items import service as items_svc
from almlight.modules.items.lifecycle import is_frozen
from almlight.modules.items.models import Item
from almlight.modules.links import service as links_svc
from almlight.modules.links.models import Link
from almlight.modules.projects.models import Project

LABELS = {"ea": "Enterprise Architect", "medini": "medini analyze", "sysml": "SysML v2"}


def _target_fields(project: Project, type_key: str) -> dict[str, str]:
    t = project.model.item_type(type_key)
    out: dict[str, str] = {}
    for f in t.fields if t else []:
        if f.computed:
            continue
        out[norm(f.label)] = f.key
        out[norm(f.key)] = f.key
    return out


def analyse(project: Project, model: ExtModel, suggestion: Suggestion, mapping: dict[str, Any]) -> dict[str, Any]:
    """Per source kind: count, suggested and chosen item type, attribute -> field plan; per relation kind likewise."""
    kinds = Counter(o.kind for o in model.objects)
    types_map = mapping.get("types") or {}
    rel_map = mapping.get("relations") or {}
    types = []
    for kind, count in sorted(kinds.items(), key=lambda x: (-x[1], x[0])):
        suggested = suggestion.types.get(kind)
        if suggested and project.model.item_type(suggested) is None:
            suggested = None
        chosen = types_map.get(kind, suggested)
        if chosen == "skip":
            chosen = None
        if chosen and project.model.item_type(chosen) is None:
            raise ValidationFailed(f"Unknown item type '{chosen}' for '{kind}'")
        attrs = sorted({a for o in model.objects if o.kind == kind for a in o.fields})
        fields = _target_fields(project, chosen) if chosen else {}
        sample = next((o.name for o in model.objects if o.kind == kind), "")
        types.append({"kind": kind, "count": count, "suggested": suggested, "mapped": chosen, "sample": sample[:80],
                      "attributes": {a: fields.get(norm(a)) for a in attrs}})
    rels = Counter(r.kind for r in model.relations)
    relations = []
    for kind, count in sorted(rels.items(), key=lambda x: (-x[1], x[0])):
        suggested = suggestion.relations.get(kind)
        if suggested and project.model.link_type(suggested.split(":")[0]) is None:
            suggested = None
        chosen = rel_map.get(kind, suggested)
        if chosen == "skip":
            chosen = None
        if chosen and project.model.link_type(chosen.split(":")[0]) is None:
            raise ValidationFailed(f"Unknown link type '{chosen}' for '{kind}'")
        relations.append({"kind": kind, "count": count, "suggested": suggested, "mapped": chosen})
    return {"types": types, "relations": relations, "objects": len(model.objects), "packages": model.packages}


def run_import(db: Session, project: Project, actor: User, model: ExtModel, suggestion: Suggestion, *,
               mapping: dict[str, Any] | None = None, dry_run: bool = True,
               own_id: Callable[[uuid.UUID], str] | None = None) -> dict[str, Any]:
    mapping = mapping or {}
    analysis = analyse(project, model, suggestion, mapping)
    type_of = {t["kind"]: t["mapped"] for t in analysis["types"]}
    rel_of = {r["kind"]: r["mapped"] for r in analysis["relations"]}
    label = LABELS.get(model.system, model.system)
    note = f"{label} import ({model.source})"

    existing: dict[str, tuple[uuid.UUID, ExternalRef | None]] = {}
    if own_id is not None:  # elements exported by this installation map back to their items
        ids = select(Item.id).where(Item.project_id == project.id, Item.deleted_at.is_(None))
        for iid in db.execute(ids).scalars():
            existing[own_id(iid)] = (iid, None)
    for ref in db.execute(select(ExternalRef).where(ExternalRef.project_id == project.id,
                                                    ExternalRef.system == model.system,
                                                    ExternalRef.kind == "element")).scalars():
        existing[ref.external_id] = (ref.item_id, ref)
    doc = _document(db, project, mapping.get("document"))

    actions = {"created": 0, "updated": 0, "unchanged": 0, "conflicts": 0, "frozen": 0, "skipped": 0, "links": 0}
    warnings: list[str] = list(model.warnings)
    errors: list[str] = []
    item_of: dict[str, Item] = {}
    savepoint = db.begin_nested()
    try:
        for obj in model.objects:
            type_key = type_of.get(obj.kind)
            if not type_key:
                actions["skipped"] += 1
                continue
            try:
                item = _upsert(db, project, actor, obj, type_key, existing.get(obj.ext_id), model.system, note,
                               actions, warnings, doc)
                if item is not None:
                    item_of[obj.ext_id] = item
            except DomainError as exc:
                errors.append(f"{obj.name[:60]} ({obj.kind}): {exc.message}")
        keys: dict[str, Item] = {}
        for rel in model.relations:
            link = rel_of.get(rel.kind)
            if not link:
                continue
            link_type, _, direction = link.partition(":")
            s, t = _end(db, project, rel.source, item_of, existing, keys), _end(db, project, rel.target, item_of,
                                                                                   existing, keys)
            if s is None or t is None:
                continue
            if direction == "reverse":
                s, t = t, s
            if s.id == t.id or db.execute(select(Link.id).where(Link.type_key == link_type, Link.source_id == s.id,
                                                                 Link.target_id == t.id,
                                                                 Link.deleted_at.is_(None))).scalar():
                continue
            try:
                links_svc.create_link(db, project, actor, type_key=link_type, source=s, target=t)
                actions["links"] += 1
            except DomainError as exc:
                warnings.append(f"{rel.kind} {s.key} → {t.key} not imported: {exc.message}")
        applied = not dry_run and not errors
        if applied:
            audit.record(db, actor=actor, action="connector.imported", entity_type="project", entity_id=project.id,
                         project_id=project.id,
                         summary=f"{label} import of {model.source}: {actions['created']} created, "
                                 f"{actions['updated']} updated, {actions['links']} links",
                         details={"system": model.system, "actions": actions, "warnings": warnings[:100]})
            savepoint.commit()
        else:
            savepoint.rollback()
    except Exception:
        savepoint.rollback()
        raise
    return {"dry_run": dry_run, "applied": applied, "system": model.system, "source": model.source,
            "analysis": analysis, "summary": actions, "warnings": warnings[:300], "errors": errors[:300]}


def _document(db: Session, project: Project, spec: Any) -> Item | None:
    if not spec:
        return None
    return items_svc.get_item(db, project, str(spec))


def _end(db: Session, project: Project, ref: str, item_of: dict[str, Item],
         existing: dict[str, tuple[uuid.UUID, ExternalRef | None]], keys: dict[str, Item]) -> Item | None:
    if ref.startswith("key:"):
        key = ref[4:].upper()
        if key not in keys:
            found = db.execute(select(Item).where(Item.project_id == project.id, Item.key == key,
                                                  Item.deleted_at.is_(None))).scalar_one_or_none()
            if found is None:
                return None
            keys[key] = found
        return keys[key]
    if ref in item_of:
        return item_of[ref]
    if ref in existing:
        item = db.get(Item, existing[ref][0])
        return item if item is not None and item.deleted_at is None else None
    return None


def _upsert(db: Session, project: Project, actor: User, obj: ExtObject, type_key: str,
            known: tuple[uuid.UUID, ExternalRef | None] | None, system: str, note: str, actions: dict[str, int],
            warnings: list[str], doc: Item | None) -> Item | None:
    target = project.model.item_type(type_key)
    plan = _target_fields(project, type_key)
    fields = {}
    for name, raw in obj.fields.items():
        key = plan.get(norm(name))
        if key and (value := _field_value(target, key, raw)) is not None:  # type: ignore[arg-type]
            fields[key] = value
    title = re.sub(r"\s+", " ", obj.name or obj.ext_id).strip()[:500] or obj.ext_id
    description = richtext.canonical(obj.text) if obj.html else richtext.plain_to_html(obj.text or "")
    digest = obj.digest()
    data = {"kind": obj.kind, "hash": digest, "path": " / ".join(obj.path)}
    if known is not None:
        item = db.get(Item, known[0])
        ref = known[1]
        if item is None or item.deleted_at is not None:
            warnings.append(f"{obj.name[:60]}: the item it was imported into has been deleted — skipped")
            actions["skipped"] += 1
            return None
        if ref is not None and ref.data.get("hash") == digest:
            actions["unchanged"] += 1
            return item
        if ref is not None and ref.data.get("version") not in (None, item.version_no):
            actions["conflicts"] += 1
            warnings.append(f"{item.key} changed in Ariadne and in the source since the last import — not overwritten")
            return item
        if is_frozen(project, item):
            actions["frozen"] += 1
            warnings.append(f"{item.key} is frozen ({item.state}); revise it to take over the change")
            return item
        before = item.version_no
        items_svc.update_item(db, project, actor, item, items_svc.ContentChange(
            title=title, description=description, fields={**{k: None for k in plan.values() if k in item.fields
                                                              and k in {plan.get(norm(n)) for n in obj.fields}},
                                                          **fields}), change_note=note)
        actions["updated" if item.version_no != before else "unchanged"] += 1
    else:
        # requirements go into the chosen document (architecture and tests keep their own structures)
        parent = _container(db, project, actor, doc, obj, system, note) \
            if doc is not None and target.category == "requirement" else None  # type: ignore[union-attr]
        item = items_svc.create_item(db, project, actor, type_key=type_key, title=title, description=description,
                                     fields=fields, parent=parent, kind="import", change_note=note)
        actions["created"] += 1
        ref = None
    _remember(db, project, actor, item, system, obj, {**data, "version": item.version_no}, ref)
    return item


def _remember(db: Session, project: Project, actor: User, item: Item, system: str, obj: ExtObject,
              data: dict[str, Any], ref: ExternalRef | None) -> None:
    if ref is None:
        ref = db.execute(select(ExternalRef).where(ExternalRef.item_id == item.id, ExternalRef.system == system,
                                                   ExternalRef.kind == "element",
                                                   ExternalRef.external_id == obj.ext_id)).scalar_one_or_none()
    if ref is None:
        db.add(ExternalRef(project_id=project.id, item_id=item.id, system=system, kind="element",
                           external_id=obj.ext_id[:255], url=obj.url, title=obj.name[:500], status=None, data=data,
                           created_by=actor.id))
    else:
        ref.data, ref.title, ref.url = data, obj.name[:500], obj.url
    db.flush()


def _container(db: Session, project: Project, actor: User, doc: Item, obj: ExtObject, system: str,
               note: str) -> Item:
    """New items go into the chosen document, below a heading per package of the source."""
    heading_type = project.model.semantics.heading_type
    if not obj.path or not heading_type or project.model.item_type(heading_type) is None:
        return doc
    parent = doc
    for depth in range(1, len(obj.path) + 1):
        ext = f"package:{'/'.join(obj.path[:depth])}"
        ref = db.execute(select(ExternalRef).where(ExternalRef.project_id == project.id, ExternalRef.system == system,
                                                   ExternalRef.kind == "package",
                                                   ExternalRef.external_id == ext[:255])).scalar_one_or_none()
        heading = db.get(Item, ref.item_id) if ref else None
        if heading is None or heading.deleted_at is not None:
            heading = items_svc.create_item(db, project, actor, type_key=heading_type, title=obj.path[depth - 1][:500],
                                            parent=parent, kind="import", change_note=note)
            db.add(ExternalRef(project_id=project.id, item_id=heading.id, system=system, kind="package",
                               external_id=ext[:255], title=obj.path[depth - 1][:500], data={}, created_by=actor.id))
            db.flush()
        parent = heading
    return parent
