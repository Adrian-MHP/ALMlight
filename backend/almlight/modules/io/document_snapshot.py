"""A document as an ordered tree of item contents — live, or exactly as frozen in a baseline."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from almlight.core.db import utcnow
from almlight.core.errors import NotFound
from almlight.modules.baselines.models import Baseline, BaselineItem, BaselineLink
from almlight.modules.items.models import Item, ItemVersion
from almlight.modules.links import service as links_svc
from almlight.modules.links.models import Link
from almlight.modules.projects.models import Project


@dataclass
class DocNode:
    key: str
    type_key: str
    type_label: str
    title: str
    description: str
    fields: list[tuple[str, str]]
    applicability: str | None
    state: str | None
    version: str
    is_heading: bool
    links: list[tuple[str, str, str]] = field(default_factory=list)  # (label, key, title)
    children: list[DocNode] = field(default_factory=list)


@dataclass
class DocSnapshot:
    project_key: str
    project_name: str
    root: DocNode
    source: str  # "Live state" or "Baseline: <name>"
    generated_at: datetime


def _field_rows(project: Project, type_key: str, values: dict[str, Any]) -> list[tuple[str, str]]:
    t = project.model.item_type(type_key)
    rows = []
    for f in t.fields if t else []:
        v = values.get(f.key)
        if v in (None, "", []) or f.type == "text":
            continue
        if f.type == "enum":
            v = next((o.label for o in f.options if o.key == v), v)
        elif f.type == "multienum":
            v = ", ".join(next((o.label for o in f.options if o.key == x), x) for x in v)
        elif isinstance(v, list):
            v = ", ".join(map(str, v))
        elif isinstance(v, bool):
            v = "Yes" if v else "No"
        rows.append((f.label, str(v)))
    return rows


def _text_fields(project: Project, type_key: str, values: dict[str, Any]) -> str:
    t = project.model.item_type(type_key)
    parts = []
    for f in t.fields if t else []:
        if f.type == "text" and values.get(f.key):
            parts.append(f"**{f.label}:** {values[f.key]}")
    return "\n\n".join(parts)


def _node(project: Project, item: Item, version: ItemVersion, state: str | None) -> DocNode:
    t = project.model.item_type(item.type_key)
    wf = project.model.workflow_for(item.type_key)
    st = wf.state(state) if wf else None
    description = version.description or ""
    extra = _text_fields(project, item.type_key, version.fields)
    if extra:
        description = f"{description}\n\n{extra}".strip()
    return DocNode(
        key=item.key, type_key=item.type_key, type_label=t.label if t else item.type_key, title=version.title,
        description=description, fields=_field_rows(project, item.type_key, version.fields),
        applicability=version.applicability, state=st.label if st else state,
        version=f"{version.revision}.{version.iteration}",
        is_heading=bool(t and not t.workflow and t.category == "document" and not t.document),
    )


def live_snapshot(db: Session, project: Project, root: Item) -> DocSnapshot:
    structural = project.model.structural_link_types()
    versions = {}

    def version_of(it: Item) -> ItemVersion:
        if it.id not in versions:
            versions[it.id] = db.get(ItemVersion, it.head_version_id)
        return versions[it.id]

    def build(it: Item, seen: frozenset) -> DocNode:
        node = _node(project, it, version_of(it), it.state)
        node.links = _outgoing(db, project, it.id, structural)
        for _, child in links_svc.children(db, it, structural):
            if child.id not in seen and child.project_id == project.id:
                node.children.append(build(child, seen | {child.id}))
        return node

    return DocSnapshot(project.key, project.name, build(root, frozenset({root.id})), "Live state", utcnow())


def _outgoing(db: Session, project: Project, item_id: uuid.UUID, structural: list[str]) -> list[tuple[str, str, str]]:
    rows = db.execute(
        select(Link, Item).join(Item, Item.id == Link.target_id)
        .where(Link.source_id == item_id, Link.deleted_at.is_(None), Link.type_key.not_in(structural),
               Item.deleted_at.is_(None))
        .order_by(Link.type_key, Item.key)
    ).all()
    out = []
    for link, other in rows:
        lt = project.model.link_type(link.type_key)
        out.append((lt.label if lt else link.type_key, other.key, other.title))
    return out


def baseline_snapshot(db: Session, project: Project, root: Item, baseline_id: uuid.UUID) -> DocSnapshot:
    baseline = db.get(Baseline, baseline_id)
    if baseline is None or baseline.project_id != project.id:
        raise NotFound("Baseline not found")
    entries = {
        bi.item_id: (bi, v, it)
        for bi, v, it in db.execute(
            select(BaselineItem, ItemVersion, Item)
            .join(ItemVersion, ItemVersion.id == BaselineItem.version_id)
            .join(Item, Item.id == BaselineItem.item_id)
            .where(BaselineItem.baseline_id == baseline.id)
        ).all()
    }
    if root.id not in entries:
        raise NotFound(f"{root.key} is not part of baseline '{baseline.name}'")
    structural = set(project.model.structural_link_types())
    blinks = db.execute(select(BaselineLink).where(BaselineLink.baseline_id == baseline.id)
                        .order_by(BaselineLink.position.nulls_last())).scalars().all()
    children: dict[uuid.UUID, list[uuid.UUID]] = {}
    outgoing: dict[uuid.UUID, list[BaselineLink]] = {}
    for bl in blinks:
        if bl.type_key in structural:
            children.setdefault(bl.source_id, []).append(bl.target_id)
        else:
            outgoing.setdefault(bl.source_id, []).append(bl)
    titles = {iid: v.title for iid, (_, v, _) in entries.items()}
    keys = {iid: it.key for iid, (_, _, it) in entries.items()}
    missing = {bl.target_id for lst in outgoing.values() for bl in lst} - set(keys)
    if missing:
        for it in db.execute(select(Item).where(Item.id.in_(missing))).scalars():
            keys[it.id], titles[it.id] = it.key, it.title

    def build(iid: uuid.UUID, seen: frozenset) -> DocNode:
        bi, v, it = entries[iid]
        node = _node(project, it, v, bi.state)
        for bl in outgoing.get(iid, []):
            lt = project.model.link_type(bl.type_key)
            node.links.append((lt.label if lt else bl.type_key, keys.get(bl.target_id, "?"),
                               titles.get(bl.target_id, "")))
        for cid in children.get(iid, []):
            if cid in entries and cid not in seen:
                node.children.append(build(cid, seen | {cid}))
        return node

    return DocSnapshot(project.key, project.name, build(root.id, frozenset({root.id})),
                       f"Baseline: {baseline.name}", baseline.created_at)
