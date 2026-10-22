"""A document as an ordered tree of item contents — live, as of any point in time, or as frozen in a baseline.

Point-in-time views are exact because everything they need is immutable or versioned:
item contents are ``ItemVersion`` rows, lifecycle states are ``WorkflowEvent`` rows, and structural links are
closed and re-created on every change (``created_at`` / ``deleted_at`` validity). Baseline views read the
baseline's own snapshot tables.
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from almlight.core.db import utcnow
from almlight.core.errors import NotFound
from almlight.modules.baselines.models import Baseline, BaselineItem, BaselineLink
from almlight.modules.items.models import Comment, Item, ItemVersion
from almlight.modules.links.models import Link
from almlight.modules.projects.models import Project
from almlight.modules.variants import expressions
from almlight.modules.variants import service as variants_svc
from almlight.modules.workflow.models import WorkflowEvent

_NUMBERED = re.compile(r"^\d+(\.\d+)*\.?\s")


@dataclass
class DocNode:
    item_id: uuid.UUID
    key: str
    type_key: str
    type_label: str
    title: str
    description: str
    raw_description: str
    fields: list[tuple[str, str]]
    fields_raw: dict[str, Any]
    applicability: str | None
    state: str | None
    state_key: str | None
    state_color: str | None
    state_category: str | None
    frozen: bool
    released: bool
    version: str
    version_no: int
    is_heading: bool
    link_id: uuid.UUID | None = None
    position: float | None = None
    number: str | None = None
    comment_count: int = 0
    reused_in: int = 0
    suspect_links: int = 0
    links: list[tuple[str, str, str]] = field(default_factory=list)  # (label, key, title)
    children: list[DocNode] = field(default_factory=list)

    @property
    def display_title(self) -> str:
        if self.number and not _NUMBERED.match(self.title):
            return f"{self.number} {self.title}"
        return self.title


@dataclass
class DocSnapshot:
    project_key: str
    project_name: str
    root: DocNode
    source: str  # human-readable: "Live state", "Baseline: …", "As of …"
    mode: str  # live | at | baseline
    generated_at: datetime
    at: datetime | None = None
    baseline: dict[str, Any] | None = None
    variant: dict[str, Any] | None = None

    def walk(self):
        stack = list(reversed(self.root.children))
        while stack:
            n = stack.pop()
            yield n
            stack.extend(reversed(n.children))


# --- sources -----------------------------------------------------------------------------------


@dataclass
class _Edge:
    id: uuid.UUID | None
    position: float | None
    applicability: str | None
    child_id: uuid.UUID


class _Source(Protocol):
    def version(self, item_id: uuid.UUID) -> ItemVersion | None: ...
    def state(self, item_id: uuid.UUID) -> str | None: ...
    def children(self, item_id: uuid.UUID) -> list[_Edge]: ...
    def outgoing(self, item_id: uuid.UUID) -> list[tuple[str, uuid.UUID]]: ...


class _LiveSource:
    def __init__(self, db: Session, structural: list[str]):
        self.db, self.structural = db, structural
        self._items: dict[uuid.UUID, Item] = {}

    def item(self, iid: uuid.UUID) -> Item | None:
        if iid not in self._items:
            self._items[iid] = self.db.get(Item, iid)
        return self._items[iid]

    def version(self, item_id: uuid.UUID) -> ItemVersion | None:
        it = self.item(item_id)
        if it is None or it.deleted_at is not None:
            return None
        return self.db.get(ItemVersion, it.head_version_id)

    def state(self, item_id: uuid.UUID) -> str | None:
        it = self.item(item_id)
        return it.state if it else None

    def children(self, item_id: uuid.UUID) -> list[_Edge]:
        rows = self.db.execute(
            select(Link).where(Link.source_id == item_id, Link.type_key.in_(self.structural),
                               Link.deleted_at.is_(None)).order_by(Link.position.nulls_last(), Link.created_at)
        ).scalars().all()
        return [_Edge(r.id, r.position, r.applicability, r.target_id) for r in rows]

    def outgoing(self, item_id: uuid.UUID) -> list[tuple[str, uuid.UUID]]:
        rows = self.db.execute(
            select(Link.type_key, Link.target_id).where(Link.source_id == item_id, Link.deleted_at.is_(None),
                                                        Link.type_key.not_in(self.structural))
        ).all()
        return [(t, i) for t, i in rows]


class _AtSource:
    """The state of the database at instant ``at`` (reconstructed from versions, events and link validity)."""

    def __init__(self, db: Session, structural: list[str], at: datetime):
        self.db, self.structural, self.at = db, structural, at
        self._versions: dict[uuid.UUID, ItemVersion | None] = {}
        self._states: dict[uuid.UUID, str | None] = {}

    def _valid(self):
        return (Link.created_at <= self.at) & ((Link.deleted_at.is_(None)) | (Link.deleted_at > self.at))

    def version(self, item_id: uuid.UUID) -> ItemVersion | None:
        if item_id not in self._versions:
            self._versions[item_id] = self.db.execute(
                select(ItemVersion).where(ItemVersion.item_id == item_id, ItemVersion.created_at <= self.at)
                .order_by(ItemVersion.version_no.desc()).limit(1)
            ).scalar_one_or_none()
        return self._versions[item_id]

    def state(self, item_id: uuid.UUID) -> str | None:
        if item_id not in self._states:
            ev = self.db.execute(
                select(WorkflowEvent.to_state).where(WorkflowEvent.item_id == item_id,
                                                     WorkflowEvent.created_at <= self.at)
                .order_by(WorkflowEvent.created_at.desc()).limit(1)
            ).scalar()
            if ev is None:
                first = self.db.execute(
                    select(ItemVersion.state).where(ItemVersion.item_id == item_id, ItemVersion.version_no == 1)
                ).scalar()
                ev = first
            self._states[item_id] = ev
        return self._states[item_id]

    def children(self, item_id: uuid.UUID) -> list[_Edge]:
        rows = self.db.execute(
            select(Link).where(Link.source_id == item_id, Link.type_key.in_(self.structural), self._valid())
            .order_by(Link.position.nulls_last(), Link.created_at)
        ).scalars().all()
        return [_Edge(r.id, r.position, r.applicability, r.target_id) for r in rows]

    def outgoing(self, item_id: uuid.UUID) -> list[tuple[str, uuid.UUID]]:
        rows = self.db.execute(
            select(Link.type_key, Link.target_id).where(Link.source_id == item_id, self._valid(),
                                                        Link.type_key.not_in(self.structural))
        ).all()
        return [(t, i) for t, i in rows]


class _BaselineSource:
    def __init__(self, db: Session, structural: list[str], baseline: Baseline):
        self.db = db
        self.entries = {
            bi.item_id: (bi, v)
            for bi, v in db.execute(
                select(BaselineItem, ItemVersion).join(ItemVersion, ItemVersion.id == BaselineItem.version_id)
                .where(BaselineItem.baseline_id == baseline.id)
            ).all()
        }
        self._children: dict[uuid.UUID, list[_Edge]] = defaultdict(list)
        self._out: dict[uuid.UUID, list[tuple[str, uuid.UUID]]] = defaultdict(list)
        for bl in db.execute(select(BaselineLink).where(BaselineLink.baseline_id == baseline.id)
                             .order_by(BaselineLink.position.nulls_last())).scalars():
            if bl.type_key in structural:
                self._children[bl.source_id].append(_Edge(bl.link_id, bl.position, bl.applicability, bl.target_id))
            else:
                self._out[bl.source_id].append((bl.type_key, bl.target_id))

    def version(self, item_id: uuid.UUID) -> ItemVersion | None:
        e = self.entries.get(item_id)
        return e[1] if e else None

    def state(self, item_id: uuid.UUID) -> str | None:
        e = self.entries.get(item_id)
        return e[0].state if e else None

    def children(self, item_id: uuid.UUID) -> list[_Edge]:
        return self._children.get(item_id, [])

    def outgoing(self, item_id: uuid.UUID) -> list[tuple[str, uuid.UUID]]:
        return self._out.get(item_id, [])


# --- builder -----------------------------------------------------------------------------------


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


def _description(project: Project, type_key: str, v: ItemVersion) -> str:
    t = project.model.item_type(type_key)
    parts = [v.description or ""]
    for f in t.fields if t else []:
        if f.type == "text" and v.fields.get(f.key):
            parts.append(f"**{f.label}:** {v.fields[f.key]}")
    return "\n\n".join(p for p in parts if p).strip()


def build_snapshot(
    db: Session, project: Project, root: Item, *, at: datetime | None = None, baseline_id: uuid.UUID | None = None,
    variant_key: str | None = None, numbering: bool = True,
) -> DocSnapshot:
    structural = project.model.structural_link_types()
    baseline = None
    if baseline_id:
        baseline = db.get(Baseline, baseline_id)
        if baseline is None or baseline.project_id != project.id:
            raise NotFound("Baseline not found")
        src: _Source = _BaselineSource(db, structural, baseline)
        mode, label = "baseline", f"Baseline: {baseline.name}"
    elif at is not None:
        src = _AtSource(db, structural, at)
        mode, label = "at", f"As of {at:%Y-%m-%d %H:%M:%S} UTC"
    else:
        src = _LiveSource(db, structural)
        mode, label = "live", "Live state"

    selection: set[str] | None = None
    variant_info = None
    if variant_key:
        from almlight.modules.items.service import get_item

        variant = get_item(db, project, variant_key)
        selection = variants_svc.selection_of(variant)
        variant_info = {"key": variant.key, "title": variant.title, "selection": sorted(selection)}

    items: dict[uuid.UUID, Item] = {}

    def item(iid: uuid.UUID) -> Item | None:
        if iid not in items:
            items[iid] = db.get(Item, iid)
        return items[iid]

    def applies(expr: str | None) -> bool:
        if selection is None:
            return True
        try:
            return expressions.applies(expr, selection)
        except Exception:  # noqa: BLE001
            return False

    def node(iid: uuid.UUID, edge: _Edge | None, seen: frozenset) -> DocNode | None:
        it = item(iid)
        v = src.version(iid)
        if it is None or v is None or it.project_id != project.id:
            return None
        t = project.model.item_type(it.type_key)
        wf = project.model.workflow_for(it.type_key)
        heading = bool(t and not t.workflow and t.category == "document" and not t.document)
        state_key = src.state(iid)
        st = wf.state(state_key) if wf else None
        n = DocNode(
            item_id=it.id, key=it.key, type_key=it.type_key, type_label=t.label if t else it.type_key,
            title=v.title, description=_description(project, it.type_key, v), raw_description=v.description or "",
            fields=_field_rows(project, it.type_key, v.fields),
            fields_raw=dict(v.fields), applicability=v.applicability, state=st.label if st else state_key,
            state_key=state_key, state_color=st.color if st else None, state_category=st.category if st else None,
            frozen=bool(st and st.frozen), released=bool(st and st.released), version=f"{v.revision}.{v.iteration}",
            version_no=v.version_no, is_heading=heading,
            link_id=edge.id if edge else None, position=edge.position if edge else None,
        )
        for type_key, target in src.outgoing(iid):
            other = item(target)
            ov = src.version(target) if other else None
            lt = project.model.link_type(type_key)
            if other is not None:
                n.links.append((lt.label if lt else type_key, other.key, ov.title if ov else other.title))
        n.links.sort()
        for e in src.children(iid):
            if e.child_id in seen or not applies(e.applicability):
                continue
            child = node(e.child_id, e, seen | {e.child_id})
            if child is not None and applies(child.applicability):
                n.children.append(child)
        return n

    root_node = node(root.id, None, frozenset({root.id}))
    if root_node is None:
        what = f"baseline '{baseline.name}'" if baseline else f"{at:%Y-%m-%d %H:%M} UTC" if at else "the live state"
        raise NotFound(f"{root.key} is not part of {what}")
    snap = DocSnapshot(project.key, project.name, root_node, label, mode, utcnow(), at=at,
                       baseline={"id": str(baseline.id), "name": baseline.name,
                                 "created_at": baseline.created_at.isoformat()} if baseline else None,
                       variant=variant_info)
    if numbering:
        _number(root_node.children, "")
    if mode == "live":
        _live_annotations(db, project, snap, structural)
    return snap


def _number(nodes: list[DocNode], prefix: str) -> None:
    i = 0
    for n in nodes:
        if n.is_heading:
            i += 1
            n.number = f"{prefix}{i}"
            _number(n.children, f"{n.number}.")
        else:
            _number(n.children, prefix)


def _live_annotations(db: Session, project: Project, snap: DocSnapshot, structural: list[str]) -> None:
    ids = [n.item_id for n in snap.walk()] + [snap.root.item_id]
    if not ids:
        return
    comments = dict(db.execute(
        select(Comment.item_id, func.count()).where(Comment.item_id.in_(ids), Comment.deleted_at.is_(None),
                                                    Comment.resolved_at.is_(None), Comment.parent_id.is_(None))
        .group_by(Comment.item_id)
    ).all())
    parents = dict(db.execute(
        select(Link.target_id, func.count()).where(Link.target_id.in_(ids), Link.type_key.in_(structural),
                                                   Link.deleted_at.is_(None)).group_by(Link.target_id)
    ).all())
    suspects = dict(db.execute(
        select(Link.source_id, func.count()).where(Link.source_id.in_(ids), Link.suspect.is_(True),
                                                   Link.deleted_at.is_(None)).group_by(Link.source_id)
    ).all())
    for n in [snap.root, *snap.walk()]:
        n.comment_count = comments.get(n.item_id, 0)
        n.reused_in = max(0, parents.get(n.item_id, 0) - (1 if n is not snap.root else 0))
        n.suspect_links = suspects.get(n.item_id, 0)


def snapshot_json(snap: DocSnapshot) -> dict[str, Any]:
    def node(n: DocNode) -> dict[str, Any]:
        return {
            "item_id": str(n.item_id), "key": n.key, "type_key": n.type_key, "type_label": n.type_label,
            "title": n.title, "display_title": n.display_title, "number": n.number, "description": n.description,
            "fields": [{"label": a, "value": b} for a, b in n.fields], "fields_raw": n.fields_raw,
            "applicability": n.applicability, "state": n.state, "state_key": n.state_key, "state_color": n.state_color,
            "state_category": n.state_category, "frozen": n.frozen, "released": n.released, "version": n.version,
            "version_no": n.version_no, "is_heading": n.is_heading, "link_id": str(n.link_id) if n.link_id else None,
            "position": n.position, "comment_count": n.comment_count, "reused_in": n.reused_in,
            "suspect_links": n.suspect_links, "links": [{"label": a, "key": b, "title": c} for a, b, c in n.links],
            "children": [node(c) for c in n.children],
        }

    return {"project_key": snap.project_key, "mode": snap.mode, "source": snap.source,
            "at": snap.at.isoformat() if snap.at else None, "baseline": snap.baseline, "variant": snap.variant,
            "generated_at": snap.generated_at.isoformat(), "root": node(snap.root)}


# Backwards-compatible helpers used by exports.

def live_snapshot(db: Session, project: Project, root: Item) -> DocSnapshot:
    return build_snapshot(db, project, root)


def baseline_snapshot(db: Session, project: Project, root: Item, baseline_id: uuid.UUID) -> DocSnapshot:
    return build_snapshot(db, project, root, baseline_id=baseline_id)
