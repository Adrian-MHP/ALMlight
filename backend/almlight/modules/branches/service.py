"""Document branching with a field-level 3-way merge.

Branching copies a structural sub-tree (e.g. a specification with its headings and requirements) into new items.
Each copy remembers its source item and the *base version* both sides started from. A merge preview compares,
field by field, the base version, the current source and the current branch:

    branch == base, source != base  -> only the source changed     (take source)
    source == base, branch != base  -> only the branch changed     (take branch)
    source == branch                -> both made the same change   (nothing to decide)
    otherwise                       -> conflict                    (user resolves: branch or source)

Merging writes new versions to the target side through the normal item service, so lifecycle rules apply:
a released target must be revised first (under a change order if change-controlled). Merges are all-or-nothing.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from almlight.core.db import utcnow
from almlight.core.errors import NotFound, ValidationFailed
from almlight.modules.audit import service as audit
from almlight.modules.branches.models import Branch, BranchItem
from almlight.modules.identity.models import User
from almlight.modules.items import service as items_svc
from almlight.modules.items.models import Item, ItemVersion
from almlight.modules.links import service as links_svc
from almlight.modules.links.models import Link
from almlight.modules.projects.models import Project


def _flat(title: str, description: str, applicability: str | None, fields: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"title": title, "description": description or "", "applicability": applicability}
    out.update({f"fields.{k}": v for k, v in (fields or {}).items()})
    return out


def _flat_item(it: Item) -> dict[str, Any]:
    return _flat(it.title, it.description, it.applicability, it.fields)


def _flat_version(v: ItemVersion) -> dict[str, Any]:
    return _flat(v.title, v.description, v.applicability, v.fields)


def get_branch(db: Session, project: Project, branch_id: uuid.UUID) -> Branch:
    b = db.get(Branch, branch_id)
    if b is None or b.project_id != project.id:
        raise NotFound("Branch not found")
    return b


def branch_of_root(db: Session, item: Item) -> Branch | None:
    return db.execute(select(Branch).where(Branch.branch_root_id == item.id)).scalar_one_or_none()


def create_branch(db: Session, project: Project, actor: User, root: Item, *, name: str,
                  description: str | None = None) -> Branch:
    name = (name or "").strip()
    if not name:
        raise ValidationFailed("Branch name is required")
    structural = project.model.structural_link_types()
    if not structural:
        raise ValidationFailed("The information model has no structural link type to branch along")
    # Pre-order traversal keeps the document order, so copies get ascending keys in reading order.
    by_id: dict[uuid.UUID, Item] = {root.id: root}
    order: list[uuid.UUID] = [root.id]

    def walk(parent: Item) -> None:
        for _, child in links_svc.children(db, parent, structural):
            if child.id in by_id or child.project_id != project.id:
                continue
            by_id[child.id] = child
            order.append(child.id)
            walk(child)

    walk(root)

    copies: dict[uuid.UUID, Item] = {}
    for iid in order:
        src = by_id[iid]
        copy = items_svc.create_item(
            db, project, actor, type_key=src.type_key, title=name if iid == root.id else src.title,
            description=src.description, fields=src.fields, applicability=src.applicability, kind="branch",
            change_note=f"Branched from {src.key} {src.version_label}",
        )
        if src.attachments:
            copy.attachments = list(src.attachments)
            db.execute(ItemVersion.__table__.update().where(ItemVersion.id == copy.head_version_id)
                       .values(attachments=copy.attachments))
        copies[iid] = copy

    branch = Branch(project_id=project.id, name=name[:200], description=description, source_root_id=root.id,
                    branch_root_id=copies[root.id].id, created_by=actor.id)
    db.add(branch)
    db.flush()
    for iid, copy in copies.items():
        db.add(BranchItem(branch_id=branch.id, branch_item_id=copy.id, source_item_id=iid, base_side="source",
                          base_version_no=by_id[iid].version_no))

    # Re-create the outline and the outgoing traces of the copied items.
    for link in db.execute(
        select(Link).where(Link.source_id.in_(copies), Link.deleted_at.is_(None)).order_by(Link.position.nulls_last())
    ).scalars():
        target = copies.get(link.target_id)
        if link.type_key in structural and target is None:
            continue  # structure leading outside the sub-tree (other projects) is not copied
        target_item = target or db.get(Item, link.target_id)
        if target_item is None or target_item.deleted_at is not None:
            continue
        links_svc.create_link(db, project, actor, type_key=link.type_key, source=copies[link.source_id],
                              target=target_item, position=link.position, attributes=link.attributes,
                              applicability=link.applicability)
    audit.record(db, actor=actor, action="branch.created", entity_type="branch", entity_id=branch.id,
                 project_id=project.id,
                 summary=f"Branched {root.key} into {copies[root.id].key} '{branch.name}' ({len(copies)} items)",
                 related_ids=[root.id, copies[root.id].id])
    return branch


def _pairs(db: Session, branch: Branch) -> list[tuple[BranchItem, Item, Item]]:
    rows = db.execute(select(BranchItem).where(BranchItem.branch_id == branch.id)).scalars().all()
    items = {
        i.id: i for i in db.execute(
            select(Item).where(Item.id.in_({r.branch_item_id for r in rows} | {r.source_item_id for r in rows}))
        ).scalars()
    }
    return [(r, items[r.source_item_id], items[r.branch_item_id]) for r in rows]


def preview(db: Session, project: Project, branch: Branch) -> dict[str, Any]:
    structural = project.model.structural_link_types()
    pairs = _pairs(db, branch)
    mapped_branch_ids = {b.id for _, _, b in pairs}
    out_pairs = []
    for pair, s, b in pairs:
        if b.id == branch.branch_root_id:
            continue  # the document item itself carries the branch name; its content is not merged
        entry: dict[str, Any] = {"source": s.key, "branch": b.key, "type_key": s.type_key, "title": b.title,
                                 "source_version": s.version_label, "branch_version": b.version_label,
                                 "changes": []}
        if s.deleted_at or b.deleted_at:
            entry["status"] = "deleted_in_source" if s.deleted_at else "deleted_in_branch"
            out_pairs.append(entry)
            continue
        base_item = s if pair.base_side == "source" else b
        base_v = db.execute(select(ItemVersion).where(ItemVersion.item_id == base_item.id,
                                                      ItemVersion.version_no == pair.base_version_no)).scalar_one()
        base, sv, bv = _flat_version(base_v), _flat_item(s), _flat_item(b)
        kinds = set()
        for key in sorted(set(base) | set(sv) | set(bv)):
            o, x, y = base.get(key), sv.get(key), bv.get(key)
            if x == o and y == o:
                continue
            kind = "source" if y == o else "branch" if x == o else "same" if x == y else "conflict"
            kinds.add(kind)
            entry["changes"].append({"field": key, "base": o, "source": x, "branch": y, "kind": kind})
        if not entry["changes"] or kinds == {"same"}:
            entry["status"] = "unchanged"
        elif "conflict" in kinds:
            entry["status"] = "conflict"
        elif kinds <= {"branch", "same"}:
            entry["status"] = "branch_changed"
        elif kinds <= {"source", "same"}:
            entry["status"] = "source_changed"
        else:
            entry["status"] = "both_changed"
        out_pairs.append(entry)

    added = []
    src_of = {b.id: s for _, s, b in pairs}
    for iid in links_svc.descendant_ids(db, branch.branch_root_id, structural):
        if iid in mapped_branch_ids:
            continue
        it = db.get(Item, iid)
        parent_link = db.execute(select(Link).where(Link.target_id == iid, Link.type_key.in_(structural),
                                                    Link.deleted_at.is_(None))).scalars().first()
        parent_src = src_of.get(parent_link.source_id) if parent_link else None
        added.append({"branch": it.key, "type_key": it.type_key, "title": it.title,
                      "parent_in_source": parent_src.key if parent_src else None})
    root = db.get(Item, branch.source_root_id)
    copy_root = db.get(Item, branch.branch_root_id)
    order = {"conflict": 0, "both_changed": 1, "branch_changed": 2, "source_changed": 3, "deleted_in_branch": 4,
             "deleted_in_source": 5, "unchanged": 6}
    out_pairs.sort(key=lambda p: (order[p["status"]], p["source"]))
    return {"branch": branch_out(branch, root, copy_root), "pairs": out_pairs, "added_in_branch": added}


def branch_out(branch: Branch, root: Item | None, copy_root: Item | None) -> dict[str, Any]:
    return {"id": str(branch.id), "name": branch.name, "description": branch.description,
            "source_root": root.key if root else None, "branch_root": copy_root.key if copy_root else None,
            "created_at": branch.created_at.isoformat(),
            "last_merged_at": branch.last_merged_at.isoformat() if branch.last_merged_at else None}


def merge(db: Session, project: Project, actor: User, branch: Branch, *, direction: str,
          keys: list[str] | None = None, resolutions: dict[str, dict[str, str]] | None = None,
          include_added: bool = True) -> dict[str, Any]:
    """Apply a merge. ``direction``: ``to_source`` (branch -> source) or ``from_source`` (source -> branch)."""
    if direction not in ("to_source", "from_source"):
        raise ValidationFailed("direction must be 'to_source' or 'from_source'")
    resolutions = resolutions or {}
    prev = preview(db, project, branch)
    pairs = {b.key: (pair, s, b) for pair, s, b in _pairs(db, branch)}
    wanted = {k.upper() for k in keys} if keys else None
    unresolved, applied = [], []
    plans = []
    for entry in prev["pairs"]:
        if wanted is not None and entry["branch"] not in wanted:
            continue
        if entry["status"] in ("unchanged", "deleted_in_source", "deleted_in_branch"):
            continue
        pair, s, b = pairs[entry["branch"]]
        merged = _flat_item(s if direction == "to_source" else b)
        for ch in entry["changes"]:
            choice = {"source": "source", "branch": "branch", "same": "branch"}.get(ch["kind"])
            if ch["kind"] == "conflict":
                choice = resolutions.get(entry["branch"], {}).get(ch["field"])
                if choice not in ("source", "branch"):
                    unresolved.append(f"{entry['branch']}: {ch['field']}")
                    continue
            value = ch[choice]
            if value is None:
                merged.pop(ch["field"], None)
            else:
                merged[ch["field"]] = value
        plans.append((pair, s, b, merged))
    if unresolved:
        raise ValidationFailed("Resolve the conflicts first", {"conflicts": unresolved})

    for pair, s, b, merged in plans:
        target = s if direction == "to_source" else b
        current = _flat_item(target)
        if merged != current:
            fields = {k[7:]: merged.get(k) for k in set(merged) | set(current) if k.startswith("fields.")}
            change = items_svc.ContentChange(title=merged["title"], description=merged["description"],
                                             fields=fields, applicability=merged.get("applicability"))
            other = b if direction == "to_source" else s
            items_svc.update_item(db, project, actor, target, change,
                                  change_note=f"Merged from {other.key} (branch '{branch.name}')")
            applied.append(target.key)
        # The merged side now contains the other side's state: that becomes the new common ancestor.
        if direction == "to_source":
            pair.base_side, pair.base_version_no = "branch", b.version_no
        else:
            pair.base_side, pair.base_version_no = "source", s.version_no

    created = []
    if direction == "to_source" and include_added:
        by_key = {e["branch"]: e for e in prev["added_in_branch"]}
        for key, entry in by_key.items():
            if wanted is not None and key not in wanted:
                continue
            if not entry["parent_in_source"]:
                continue
            b_item = items_svc.get_item(db, project, key)
            parent = items_svc.get_item(db, project, entry["parent_in_source"])
            new = items_svc.create_item(db, project, actor, type_key=b_item.type_key, title=b_item.title,
                                        description=b_item.description, fields=b_item.fields,
                                        applicability=b_item.applicability, parent=parent,
                                        change_note=f"Added by merge of {b_item.key} (branch '{branch.name}')")
            db.add(BranchItem(branch_id=branch.id, branch_item_id=b_item.id, source_item_id=new.id,
                              base_side="branch", base_version_no=b_item.version_no))
            created.append(new.key)
    branch.last_merged_at = utcnow()
    db.flush()
    audit.record(db, actor=actor, action="branch.merged", entity_type="branch", entity_id=branch.id,
                 project_id=project.id,
                 summary=f"Merged branch '{branch.name}' {direction.replace('_', ' ')}: "
                         f"{len(applied)} updated, {len(created)} created",
                 details={"updated": applied, "created": created})
    return {"updated": applied, "created": created}
