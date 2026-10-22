"""ReqIF 1.x import (.reqif / .reqifz).

Reads DATATYPES, SPEC-TYPES, SPEC-OBJECTS, SPEC-RELATIONS and SPECIFICATIONS and maps them onto the project's
information model:

* SPEC-OBJECT-TYPE  -> item type      (suggested by name, overridable; ``skip`` ignores the type)
* attributes        -> title / description / custom fields (matched by field label or key; enum values by label)
* SPEC-RELATION-TYPE -> link type     (matched by label, reverse label or key)
* SPECIFICATION     -> a document item with the SPEC-HIERARCHY as ordered structural links

Every imported object keeps its ReqIF identifier as an external reference (system ``reqif``). Importing a newer
file from the same source therefore *updates* the existing items (new versions) instead of creating duplicates —
the usual round trip with customers and suppliers. Frozen items are not changed; they are reported so they can be
revised. ``dry_run`` analyses and reports without writing anything.
"""

from __future__ import annotations

import io
import re
import uuid
import zipfile
from dataclasses import dataclass, field
from typing import Any
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as SafeET
from sqlalchemy import select
from sqlalchemy.orm import Session

from almlight.core.errors import DomainError, ValidationFailed
from almlight.modules.audit import service as audit
from almlight.modules.identity.models import User
from almlight.modules.integrations.models import ExternalRef
from almlight.modules.integrations.service import upsert_ref
from almlight.modules.items import service as items_svc
from almlight.modules.items.lifecycle import is_frozen
from almlight.modules.items.models import Item
from almlight.modules.links import service as links_svc
from almlight.modules.links.models import Link
from almlight.modules.projects.metamodel import ItemTypeDef
from almlight.modules.projects.models import Project

MAX_OBJECTS = 20_000
TITLE_NAMES = ("title", "reqif.name", "name", "heading", "object heading", "summary", "reqif.chaptername",
               "chapter name")
TEXT_NAMES = ("description", "reqif.text", "text", "object text", "body", "content")
ID_NAMES = ("id", "reqif.foreignid", "identifier", "absolute number", "object identifier", "foreign id", "key")
IGNORED_NAMES = ("status", "state", "version", "reqif.chaptername", "reqif.foreigncreatedby",
                 "reqif.foreignmodifiedby", "reqif.foreigncreatedon", "reqif.foreignmodifiedon")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(el: Element, name: str) -> Element | None:
    return next((c for c in el if _local(c.tag) == name), None)


def _children(el: Element | None, name: str | None = None) -> list[Element]:
    if el is None:
        return []
    return [c for c in el if name is None or _local(c.tag) == name]


def _ref(el: Element, container: str) -> str | None:
    holder = _child(el, container)
    if holder is None:
        return None
    for c in holder:
        if _local(c.tag).endswith("-REF") and c.text:
            return c.text.strip()
    return None


def own_identifier(kind: str, item_id: uuid.UUID) -> str:
    """Identifier that the ReqIF export of this installation gives an item (see io/reqif.py)."""
    return "_" + uuid.uuid5(uuid.NAMESPACE_URL, f"almlight:{kind}:{item_id}").hex


def _norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


# --- XHTML -> Markdown -------------------------------------------------------------------------


def xhtml_to_markdown(el: Element) -> str:
    """Convert the XHTML content of an ATTRIBUTE-VALUE-XHTML to Markdown (paragraphs, emphasis, lists, tables)."""
    blocks: list[str] = []
    _blocks(el, blocks, list_prefix=None)
    text = "\n\n".join(b.strip("\n") for b in blocks if b.strip())
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _inline(el: Element) -> str:
    """Text content of ``el`` with inline formatting (children rendered, tails kept)."""
    parts = [el.text or ""]
    for c in el:
        parts.append(_inline_element(c))
        parts.append(c.tail or "")
    return re.sub(r"[ \t]+", " ", "".join(parts))


def _inline_element(c: Element) -> str:
    tag = _local(c.tag).lower()
    inner = _inline(c)
    if tag in ("b", "strong") and inner.strip():
        return f"**{inner.strip()}**"
    if tag in ("i", "em") and inner.strip():
        return f"*{inner.strip()}*"
    if tag == "br":
        return "  \n"
    if tag == "a":
        href = c.get("href")
        return f"[{inner}]({href})" if href else inner
    if tag in ("object", "img"):
        return "[image]"
    if tag == "code":
        return f"`{inner}`"
    return inner


def _blocks(el: Element, out: list[str], list_prefix: str | None) -> None:
    inline_buf = [el.text or ""]

    def flush() -> None:
        text = "".join(inline_buf).strip()
        if text:
            out.append(re.sub(r"[ \t]+", " ", text))
        inline_buf.clear()

    for c in el:
        tag = _local(c.tag).lower()
        if tag in ("p", "div", "blockquote", "pre"):
            flush()
            if any(_local(g.tag).lower() in ("p", "div", "ul", "ol", "table") for g in c):
                _blocks(c, out, list_prefix)
            else:
                out.append(_inline(c).strip())
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            flush()
            out.append("#" * int(tag[1]) + " " + _inline(c).strip())
        elif tag in ("ul", "ol"):
            flush()
            lines = []
            for n, li in enumerate(_children(c, "li"), start=1):
                marker = f"{n}." if tag == "ol" else "-"
                lines.append(f"{marker} {_inline(li).strip()}")
            out.append("\n".join(lines))
        elif tag == "table":
            flush()
            out.append(_table(c))
        else:
            inline_buf.append(_inline_element(c))
        inline_buf.append(c.tail or "")
    flush()


def _table(t: Element) -> str:
    rows = [r for r in t.iter() if _local(r.tag).lower() == "tr"]
    cells = [[_inline(td).strip().replace("|", "\\|") for td in r if _local(td.tag).lower() in ("td", "th")]
             for r in rows]
    cells = [r for r in cells if r]
    if not cells:
        return ""
    width = max(len(r) for r in cells)
    cells = [r + [""] * (width - len(r)) for r in cells]
    lines = ["| " + " | ".join(cells[0]) + " |", "|" + " --- |" * width]
    lines += ["| " + " | ".join(r) + " |" for r in cells[1:]]
    return "\n".join(lines)


# --- parsing -----------------------------------------------------------------------------------


@dataclass
class AttrDef:
    id: str
    name: str
    kind: str
    datatype: str | None


@dataclass
class SpecType:
    id: str
    name: str
    kind: str  # object | relation | specification
    attrs: dict[str, AttrDef] = field(default_factory=dict)


@dataclass
class SpecObject:
    id: str
    type_id: str | None
    long_name: str | None
    values: dict[str, Any] = field(default_factory=dict)


@dataclass
class HNode:
    object_id: str
    children: list[HNode] = field(default_factory=list)


@dataclass
class Specification:
    id: str
    name: str
    children: list[HNode] = field(default_factory=list)


@dataclass
class ReqIF:
    title: str | None
    enums: dict[str, str]  # enum value id -> label
    types: dict[str, SpecType]
    objects: dict[str, SpecObject]
    relations: list[tuple[str, str | None, str, str]]  # id, type id, source, target
    specifications: list[Specification]


def _read_bytes(filename: str, content: bytes) -> bytes:
    if filename.lower().endswith(".reqifz") or content[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                name = next((n for n in z.namelist() if n.lower().endswith(".reqif")), None)
                if name is None:
                    raise ValidationFailed("The .reqifz archive contains no .reqif file")
                return z.read(name)
        except zipfile.BadZipFile:
            raise ValidationFailed("Not a valid .reqifz archive") from None
    return content


def parse_reqif(filename: str, content: bytes) -> ReqIF:
    try:
        root = SafeET.fromstring(_read_bytes(filename, content))
    except DomainError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ValidationFailed(f"Not a valid ReqIF file: {exc}") from None
    if _local(root.tag) != "REQ-IF":
        raise ValidationFailed("Not a ReqIF file (root element must be REQ-IF)")
    title_el = next((e for e in root.iter() if _local(e.tag) == "TITLE"), None)
    content_el = next((e for e in root.iter() if _local(e.tag) == "REQ-IF-CONTENT"), None)
    if content_el is None:
        raise ValidationFailed("ReqIF file has no REQ-IF-CONTENT")

    enums: dict[str, str] = {}
    dt_kind: dict[str, str] = {}
    for dt in _children(_child(content_el, "DATATYPES")):
        tag = _local(dt.tag)
        dt_kind[dt.get("IDENTIFIER", "")] = tag.replace("DATATYPE-DEFINITION-", "").lower()
        if tag == "DATATYPE-DEFINITION-ENUMERATION":
            for ev in _children(_child(dt, "SPECIFIED-VALUES"), "ENUM-VALUE"):
                emb = next((e for e in ev.iter() if _local(e.tag) == "EMBEDDED-VALUE"), None)
                enums[ev.get("IDENTIFIER", "")] = ev.get("LONG-NAME") or (emb.get("OTHER-CONTENT") if emb is not None
                                                                          else "") or ""

    types: dict[str, SpecType] = {}
    for st in _children(_child(content_el, "SPEC-TYPES")):
        tag = _local(st.tag)
        kind = {"SPEC-OBJECT-TYPE": "object", "SPEC-RELATION-TYPE": "relation",
                "SPECIFICATION-TYPE": "specification"}.get(tag)
        if kind is None:
            continue
        stype = SpecType(id=st.get("IDENTIFIER", ""), name=st.get("LONG-NAME") or st.get("IDENTIFIER", ""), kind=kind)
        for ad in _children(_child(st, "SPEC-ATTRIBUTES")):
            dtype = _ref(ad, "TYPE")
            akind = _local(ad.tag).replace("ATTRIBUTE-DEFINITION-", "").lower()
            stype.attrs[ad.get("IDENTIFIER", "")] = AttrDef(ad.get("IDENTIFIER", ""), ad.get("LONG-NAME") or "",
                                                            akind, dtype)
        types[stype.id] = stype

    def values_of(el: Element) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for av in _children(_child(el, "VALUES")):
            tag = _local(av.tag)
            def_id = _ref(av, "DEFINITION")
            if not def_id:
                continue
            if tag == "ATTRIBUTE-VALUE-XHTML":
                the = _child(av, "THE-VALUE")
                out[def_id] = xhtml_to_markdown(the) if the is not None else ""
            elif tag == "ATTRIBUTE-VALUE-ENUMERATION":
                out[def_id] = [enums.get(r.text.strip(), r.text.strip())
                               for r in _children(_child(av, "VALUES")) if r.text]
            else:
                out[def_id] = av.get("THE-VALUE")
        return out

    objects: dict[str, SpecObject] = {}
    for so in _children(_child(content_el, "SPEC-OBJECTS"), "SPEC-OBJECT"):
        obj = SpecObject(id=so.get("IDENTIFIER", ""), type_id=_ref(so, "TYPE"), long_name=so.get("LONG-NAME"),
                         values=values_of(so))
        objects[obj.id] = obj
        if len(objects) > MAX_OBJECTS:
            raise ValidationFailed(f"At most {MAX_OBJECTS} objects per import")

    relations = []
    for rel in _children(_child(content_el, "SPEC-RELATIONS"), "SPEC-RELATION"):
        src, tgt = _ref(rel, "SOURCE"), _ref(rel, "TARGET")
        if src and tgt:
            relations.append((rel.get("IDENTIFIER", ""), _ref(rel, "TYPE"), src, tgt))

    def hierarchy(el: Element | None) -> list[HNode]:
        nodes = []
        for h in _children(el, "SPEC-HIERARCHY"):
            obj_id = _ref(h, "OBJECT")
            if obj_id:
                nodes.append(HNode(obj_id, hierarchy(_child(h, "CHILDREN"))))
        return nodes

    specs = [Specification(id=sp.get("IDENTIFIER", ""), name=sp.get("LONG-NAME") or "Imported specification",
                           children=hierarchy(_child(sp, "CHILDREN")))
             for sp in _children(_child(content_el, "SPECIFICATIONS"), "SPECIFICATION")]
    return ReqIF(title=title_el.text if title_el is not None else None, enums=enums, types=types, objects=objects,
                 relations=relations, specifications=specs)


# --- mapping -----------------------------------------------------------------------------------


def _is_heading_type(st: SpecType) -> bool:
    n = st.name.lower()
    return any(w in n for w in ("heading", "chapter", "section", "überschrift", "kapitel"))


def suggest_type(project: Project, st: SpecType) -> str | None:
    model = project.model
    for t in model.item_types:
        if _norm(t.label) == _norm(st.name) or _norm(t.key) == _norm(st.name):
            return t.key
    if _is_heading_type(st) and model.item_type("heading"):
        return "heading"
    return None


def suggest_link(project: Project, name: str) -> str | None:
    for lt in project.model.link_types:
        if _norm(name) in (_norm(lt.label), _norm(lt.reverse_label), _norm(lt.key)):
            return lt.key
    return None


@dataclass
class AttrPlan:
    title: list[str] = field(default_factory=list)
    text: list[str] = field(default_factory=list)
    ident: list[str] = field(default_factory=list)
    chapter: list[str] = field(default_factory=list)
    fields: dict[str, str] = field(default_factory=dict)  # attr id -> field key
    unmapped: list[str] = field(default_factory=list)


def plan_attributes(st: SpecType, target: ItemTypeDef | None) -> AttrPlan:
    plan = AttrPlan()
    by_field = {}
    if target is not None:
        for f in target.fields:
            by_field[_norm(f.label)] = f.key
            by_field[_norm(f.key)] = f.key
    for ad in st.attrs.values():
        n = ad.name.lower().strip()
        if n in ("reqif.chaptername", "chapter name"):
            plan.chapter.append(ad.id)
        if n in TITLE_NAMES:
            plan.title.append(ad.id)
        elif n in TEXT_NAMES or (ad.kind == "xhtml" and not plan.text):
            plan.text.append(ad.id)
        elif n in ID_NAMES:
            plan.ident.append(ad.id)
        elif _norm(ad.name) in by_field:
            plan.fields[ad.id] = by_field[_norm(ad.name)]
        elif n not in IGNORED_NAMES:
            plan.unmapped.append(ad.name)
    # ReqIF.ChapterName titles headings; for other objects prefer an explicit title attribute.
    plan.title.sort(key=lambda a: st.attrs[a].name.lower() == "reqif.chaptername")
    return plan


def _first(obj: SpecObject, ids: list[str]) -> str | None:
    for a in ids:
        v = obj.values.get(a)
        if isinstance(v, list):
            v = ", ".join(v)
        if v not in (None, ""):
            return str(v)
    return None


def _field_value(target: ItemTypeDef, field_key: str, raw: Any) -> Any:
    f = target.field(field_key)
    if f is None or raw in (None, "", []):
        return None
    if f.type in ("enum", "multienum"):
        values = raw if isinstance(raw, list) else [raw]
        mapped = []
        for v in values:
            opt = next((o.key for o in f.options if _norm(o.key) == _norm(v) or _norm(o.label) == _norm(v)), None)
            if opt:
                mapped.append(opt)
        if not mapped:
            return None
        return mapped[0] if f.type == "enum" else mapped
    if isinstance(raw, list):
        raw = ", ".join(raw)
    if f.type == "boolean":
        return str(raw).lower() in ("true", "1", "yes")
    return raw


# --- import ------------------------------------------------------------------------------------


def import_reqif(
    db: Session, project: Project, actor: User, filename: str, content: bytes, *, dry_run: bool = True,
    type_mapping: dict[str, str] | None = None, relation_mapping: dict[str, str] | None = None,
    default_type: str | None = None,
) -> dict[str, Any]:
    doc = parse_reqif(filename, content)
    model = project.model
    type_mapping = type_mapping or {}
    relation_mapping = relation_mapping or {}
    if default_type and model.item_type(default_type) is None:
        raise ValidationFailed(f"Unknown default type '{default_type}'")
    doc_type = next((t.key for t in model.item_types if t.document), None)
    heading_type = model.semantics.heading_type if model.item_type(model.semantics.heading_type or "") else None

    counts: dict[str, int] = {}
    for obj in doc.objects.values():
        counts[obj.type_id or ""] = counts.get(obj.type_id or "", 0) + 1
    rel_counts: dict[str, int] = {}
    for _, tid, _, _ in doc.relations:
        rel_counts[tid or ""] = rel_counts.get(tid or "", 0) + 1

    # Resolve mappings (user choice > suggestion > default type).
    resolved_types: dict[str, str | None] = {}
    analysis_types = []
    plans: dict[str, AttrPlan] = {}
    for tid, st in doc.types.items():
        if st.kind != "object":
            continue
        suggested = suggest_type(project, st)
        chosen = type_mapping.get(st.name, suggested or default_type)
        if chosen == "skip":
            chosen = None
        elif chosen and model.item_type(chosen) is None:
            raise ValidationFailed(f"Unknown item type '{chosen}' for ReqIF type '{st.name}'")
        resolved_types[tid] = chosen
        plans[tid] = plan_attributes(st, model.item_type(chosen) if chosen else None)
        p = plans[tid]
        analysis_types.append({
            "name": st.name, "count": counts.get(tid, 0), "suggested": suggested, "mapped": chosen,
            "attributes": {
                "title": [st.attrs[a].name for a in p.title], "description": [st.attrs[a].name for a in p.text],
                "id": [st.attrs[a].name for a in p.ident],
                "fields": {st.attrs[a].name: k for a, k in p.fields.items()}, "unmapped": p.unmapped,
            },
        })
    resolved_links: dict[str, str | None] = {}
    analysis_relations = []
    for tid, st in doc.types.items():
        if st.kind != "relation":
            continue
        suggested = suggest_link(project, st.name)
        chosen = relation_mapping.get(st.name, suggested)
        if chosen == "skip":
            chosen = None
        elif chosen and model.link_type(chosen) is None:
            raise ValidationFailed(f"Unknown link type '{chosen}' for ReqIF relation '{st.name}'")
        resolved_links[tid] = chosen
        analysis_relations.append({"name": st.name, "count": rel_counts.get(tid, 0), "suggested": suggested,
                                   "mapped": chosen})

    # Identity of previously imported objects; files exported by this installation map back to their items.
    existing: dict[str, uuid.UUID] = {}
    for it_id, it_type in db.execute(select(Item.id, Item.type_key).where(Item.project_id == project.id,
                                                                          Item.deleted_at.is_(None))).all():
        existing[own_identifier("so", it_id)] = it_id
        if model.item_type(it_type) is not None and model.item_type(it_type).document:
            existing[f"spec:{own_identifier('spec', it_id)}"] = it_id
    for ref in db.execute(select(ExternalRef).where(ExternalRef.project_id == project.id,
                                                    ExternalRef.system == "reqif")).scalars():
        existing[ref.external_id] = ref.item_id
    warnings: list[str] = []
    errors: list[str] = []
    actions: dict[str, int] = {"created": 0, "updated": 0, "unchanged": 0, "skipped": 0, "frozen": 0, "links": 0}
    item_of: dict[str, Item] = {}
    savepoint = db.begin_nested()
    try:
        for obj in doc.objects.values():
            type_key = resolved_types.get(obj.type_id or "")
            st = doc.types.get(obj.type_id or "")
            if not type_key or st is None:
                actions["skipped"] += 1
                continue
            plan = plans[obj.type_id or ""]
            text = _first(obj, plan.text) or ""
            # DOORS-style exports mark headings by a chapter name without text within the same object type.
            if heading_type and _first(obj, plan.chapter) and not text.strip():
                type_key = heading_type
                actions["headings"] = actions.get("headings", 0) + 1
            target = model.item_type(type_key)
            first_line = re.sub(r"[*_`#>]", "", text.splitlines()[0]).strip()[:120] if text else None
            title = _first(obj, plan.title) or obj.long_name or first_line or obj.id
            title = re.sub(r"\s+", " ", title).strip()[:500]
            fields = {k: v for a, k in plan.fields.items()
                      if target.field(k) is not None and (v := _field_value(target, k, obj.values.get(a))) is not None}
            ident = _first(obj, plan.ident)
            try:
                if obj.id in existing:
                    item = db.get(Item, existing[obj.id])
                    if item is None or item.deleted_at is not None:
                        raise ValidationFailed(f"{obj.id}: previously imported item was deleted")
                    change = items_svc.ContentChange(title=title, description=text,
                                                     fields={**{k: None for k in item.fields if k in
                                                                set(plan.fields.values())}, **fields})
                    before = item.version_no
                    if is_frozen(project, item):
                        probe = (item.title, item.description) != (title, text) or any(
                            item.fields.get(k) != v for k, v in fields.items())
                        if probe:
                            actions["frozen"] += 1
                            warnings.append(f"{item.key} is frozen ({item.state}); revise it to take over the change")
                        else:
                            actions["unchanged"] += 1
                    else:
                        items_svc.update_item(db, project, actor, item, change,
                                              change_note=f"ReqIF import ({filename})")
                        actions["updated" if item.version_no != before else "unchanged"] += 1
                else:
                    item = items_svc.create_item(db, project, actor, type_key=type_key, title=title, description=text,
                                                 fields=fields, kind="import",
                                                 change_note=f"ReqIF import ({filename})")
                    upsert_ref(db, project, item, system="reqif", kind="spec_object", external_id=obj.id,
                               url=None, title=ident or obj.long_name, data={"file": filename, "type": st.name},
                               actor=actor)
                    actions["created"] += 1
                item_of[obj.id] = item
            except DomainError as exc:
                errors.append(f"{obj.id} ({title[:60]}): {exc.message}")

        structural = model.structural_link_types()
        for spec in doc.specifications:
            key = f"spec:{spec.id}"
            if doc_type is None:
                warnings.append("The information model has no document type; specification hierarchy not imported")
                break
            if key in existing:
                spec_item = db.get(Item, existing[key])
            else:
                spec_item = items_svc.create_item(db, project, actor, type_key=doc_type, title=spec.name[:500],
                                                  kind="import", change_note=f"ReqIF import ({filename})")
                upsert_ref(db, project, spec_item, system="reqif", kind="specification", external_id=key, url=None,
                           title=spec.name, data={"file": filename}, actor=actor)
                actions["created"] += 1
            _attach_children(db, project, actor, spec_item, spec.children, item_of, structural, warnings, actions)

        for _, tid, src, tgt in doc.relations:
            link_type = resolved_links.get(tid or "")
            if not link_type:
                continue
            s, t = item_of.get(src), item_of.get(tgt)
            if s is None or t is None:
                continue
            already = db.execute(select(Link.id).where(Link.type_key == link_type, Link.source_id == s.id,
                                                       Link.target_id == t.id, Link.deleted_at.is_(None))).scalar()
            if already:
                continue
            try:
                links_svc.create_link(db, project, actor, type_key=link_type, source=s, target=t)
                actions["links"] += 1
            except DomainError as exc:
                warnings.append(f"Relation {s.key} -> {t.key} not imported: {exc.message}")

        applied = not dry_run and not errors
        if applied:
            audit.record(db, actor=actor, action="project.reqif_imported", entity_type="project", entity_id=project.id,
                         project_id=project.id, summary=f"ReqIF import of {filename}: "
                         f"{actions['created']} created, {actions['updated']} updated, {actions['links']} links",
                         details={"actions": actions, "warnings": warnings[:100]})
            savepoint.commit()
        else:
            savepoint.rollback()
    except Exception:
        savepoint.rollback()
        raise
    return {
        "dry_run": dry_run, "applied": applied, "title": doc.title,
        "analysis": {"types": analysis_types, "relations": analysis_relations,
                     "specifications": [{"name": s.name, "top_level": len(s.children)} for s in doc.specifications],
                     "objects": len(doc.objects)},
        "summary": actions, "warnings": warnings[:300], "errors": errors[:300],
    }


def _attach_children(db: Session, project: Project, actor: User, parent: Item, nodes: list[HNode],
                     item_of: dict[str, Item], structural: list[str], warnings: list[str],
                     actions: dict[str, int]) -> None:
    for pos, node in enumerate(nodes, start=1):
        child = item_of.get(node.object_id)
        if child is None:
            _attach_children(db, project, actor, parent, node.children, item_of, structural, warnings, actions)
            continue
        exists = db.execute(select(Link.id).where(Link.source_id == parent.id, Link.target_id == child.id,
                                                  Link.type_key.in_(structural), Link.deleted_at.is_(None))).scalar()
        if not exists:
            lt = next((t.key for t in project.model.link_types if t.structural and t.allows(parent.type_key,
                                                                                             child.type_key)), None)
            if lt is None:
                warnings.append(f"{child.key} cannot be placed below {parent.key} (no structural link type allows "
                                f"{parent.type_key} -> {child.type_key})")
            else:
                try:
                    links_svc.create_link(db, project, actor, type_key=lt, source=parent, target=child,
                                          position=float(pos))
                except DomainError as exc:
                    warnings.append(f"{child.key} not placed below {parent.key}: {exc.message}")
        _attach_children(db, project, actor, child, node.children, item_of, structural, warnings, actions)
