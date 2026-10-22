"""Baselines: freeze the configuration of a project or of a sub-tree, and compare configurations.

Revision rules (as in PLM configuration management):
  * ``latest``   — the head version of every item (working state)
  * ``released`` — the latest released version of every item; unreleased items are left out
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from almlight.core.errors import NotFound, ValidationFailed
from almlight.modules.audit import service as audit
from almlight.modules.baselines.models import Baseline, BaselineItem, BaselineLink
from almlight.modules.identity.models import User
from almlight.modules.integrations.outbox import emit
from almlight.modules.items.models import Item, ItemVersion
from almlight.modules.items.service import diff_versions
from almlight.modules.links import service as links
from almlight.modules.links.models import Link
from almlight.modules.projects.models import Project

REVISION_RULES = ("latest", "released")


def get_baseline(db: Session, project: Project, baseline_id: uuid.UUID) -> Baseline:
    b = db.get(Baseline, baseline_id)
    if b is None or b.project_id != project.id:
        raise NotFound("Baseline not found")
    return b


def create_baseline(
    db: Session,
    project: Project,
    actor: User | None,
    *,
    name: str,
    description: str | None = None,
    scope_root: Item | None = None,
    revision_rule: str = "latest",
) -> Baseline:
    name = (name or "").strip()
    if not name:
        raise ValidationFailed("Baseline name is required")
    if revision_rule not in REVISION_RULES:
        raise ValidationFailed(f"revision_rule must be one of {REVISION_RULES}")
    stmt = select(Item).where(Item.project_id == project.id, Item.deleted_at.is_(None))
    if scope_root is not None:
        ids = [scope_root.id, *links.descendant_ids(db, scope_root.id, project.model.structural_link_types())]
        stmt = stmt.where(Item.id.in_(ids))
    items = db.execute(stmt).scalars().all()

    baseline = Baseline(project_id=project.id, name=name[:200], description=description,
                        scope_root_id=scope_root.id if scope_root else None, revision_rule=revision_rule,
                        created_by=actor.id if actor else None)
    db.add(baseline)
    db.flush()

    version_ids = {}
    for it in items:
        vid = it.released_version_id if revision_rule == "released" else it.head_version_id
        if vid is not None:
            version_ids[it.id] = vid
    versions = {
        v.id: v for v in db.execute(select(ItemVersion).where(ItemVersion.id.in_(version_ids.values()))).scalars()
    }
    by_id = {it.id: it for it in items}
    for item_id, vid in version_ids.items():
        v = versions[vid]
        it = by_id[item_id]
        if it.head_version_id == vid:
            state = it.state
        else:
            # An older released version, while a newer revision is in work.
            wf = project.model.workflow_for(it.type_key)
            state = wf.released_state.key if wf and wf.released_state else None
        db.add(BaselineItem(baseline_id=baseline.id, item_id=item_id, version_id=vid, version_no=v.version_no,
                            revision=v.revision, iteration=v.iteration, state=state))
    included = set(version_ids)
    link_rows = db.execute(
        select(Link).where(Link.source_id.in_(included), Link.deleted_at.is_(None))
    ).scalars().all() if included else []
    count_links = 0
    for link in link_rows:
        if link.target_id not in included and link.project_id == project.id and scope_root is None:
            continue
        db.add(BaselineLink(baseline_id=baseline.id, link_id=link.id, type_key=link.type_key,
                            source_id=link.source_id, target_id=link.target_id, position=link.position,
                            attributes=link.attributes, applicability=link.applicability, suspect=link.suspect))
        count_links += 1
    baseline.item_count = len(version_ids)
    baseline.link_count = count_links
    db.flush()
    audit.record(db, actor=actor, action="baseline.created", entity_type="baseline", entity_id=baseline.id,
                 project_id=project.id,
                 summary=f"Created baseline '{baseline.name}' ({revision_rule}, {baseline.item_count} items)",
                 details={"scope": scope_root.key if scope_root else None, "items": baseline.item_count,
                          "links": count_links, "skipped": len(items) - len(version_ids)},
                 related_ids=[scope_root.id] if scope_root else [])
    emit(db, "baseline.created", project.id, {"project": project.key, "baseline_id": baseline.id,
                                              "name": baseline.name})
    return baseline


def baseline_entries(db: Session, baseline: Baseline) -> list[tuple[BaselineItem, ItemVersion, Item]]:
    rows = db.execute(
        select(BaselineItem, ItemVersion, Item)
        .join(ItemVersion, ItemVersion.id == BaselineItem.version_id)
        .join(Item, Item.id == BaselineItem.item_id)
        .where(BaselineItem.baseline_id == baseline.id)
        .order_by(Item.type_key, Item.seq)
    ).all()
    return [(bi, v, it) for bi, v, it in rows]


def _current_snapshot(db: Session, project: Project) -> tuple[dict[uuid.UUID, ItemVersion], set[tuple]]:
    heads = db.execute(
        select(ItemVersion)
        .join(Item, Item.head_version_id == ItemVersion.id)
        .where(Item.project_id == project.id, Item.deleted_at.is_(None))
    ).scalars().all()
    link_keys = {
        (lk.type_key, lk.source_id, lk.target_id)
        for lk in db.execute(select(Link).where(Link.project_id == project.id, Link.deleted_at.is_(None))).scalars()
    }
    return {v.item_id: v for v in heads}, link_keys


def _baseline_snapshot(db: Session, baseline: Baseline) -> tuple[dict[uuid.UUID, ItemVersion], set[tuple]]:
    entries = baseline_entries(db, baseline)
    link_keys = {
        (bl.type_key, bl.source_id, bl.target_id)
        for bl in db.execute(select(BaselineLink).where(BaselineLink.baseline_id == baseline.id)).scalars()
    }
    return {it.id: v for _, v, it in entries}, link_keys


def compare(db: Session, project: Project, a: Baseline, b: Baseline | None) -> dict[str, Any]:
    """Differences from baseline ``a`` to baseline ``b`` (or to the current state if ``b`` is None)."""
    va, la = _baseline_snapshot(db, a)
    vb, lb = _baseline_snapshot(db, b) if b else _current_snapshot(db, project)
    if b is None and a.scope_root_id is not None:
        # Compare a scoped baseline only with the same scope today.
        scope = {a.scope_root_id, *links.descendant_ids(db, a.scope_root_id, project.model.structural_link_types())}
        vb = {k: v for k, v in vb.items() if k in scope}
        lb = {lk for lk in lb if lk[1] in scope}
    ids = set(va) | set(vb)
    items = {i.id: i for i in db.execute(select(Item).where(Item.id.in_(ids))).scalars()} if ids else {}

    def summary(item_id: uuid.UUID) -> dict[str, Any]:
        it = items[item_id]
        return {"id": str(it.id), "key": it.key, "type_key": it.type_key, "title": it.title}

    added = [{**summary(i), "version": vb[i].version_label} for i in vb.keys() - va.keys()]
    removed = [{**summary(i), "version": va[i].version_label} for i in va.keys() - vb.keys()]
    changed = []
    unchanged = 0
    for i in va.keys() & vb.keys():
        if va[i].id == vb[i].id:
            unchanged += 1
            continue
        changed.append({**summary(i), "from_version": va[i].version_label, "to_version": vb[i].version_label,
                        "changes": diff_versions(va[i], vb[i])})
    keys = {it.id: it.key for it in items.values()}
    extra_ids = {x for lk in la | lb for x in lk[1:]} - set(keys)
    if extra_ids:
        keys.update({it.id: it.key for it in db.execute(select(Item).where(Item.id.in_(extra_ids))).scalars()})

    def link_view(lk: tuple) -> dict[str, Any]:
        return {"type": lk[0], "source": keys.get(lk[1], str(lk[1])), "target": keys.get(lk[2], str(lk[2]))}

    for lst in (added, removed, changed):
        lst.sort(key=lambda r: (r["type_key"], r["key"]))
    return {
        "from": {"id": str(a.id), "name": a.name},
        "to": {"id": str(b.id), "name": b.name} if b else {"id": None, "name": "Current state"},
        "items": {"added": added, "removed": removed, "changed": changed, "unchanged": unchanged},
        "links": {
            "added": sorted((link_view(lk) for lk in lb - la), key=lambda r: (r["type"], r["source"])),
            "removed": sorted((link_view(lk) for lk in la - lb), key=lambda r: (r["type"], r["source"])),
        },
    }
