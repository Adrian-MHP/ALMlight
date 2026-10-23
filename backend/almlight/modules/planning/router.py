"""Release planning: releases/milestones with planned work, progress, schedule status and a burn-up chart."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from almlight.core.db import get_db, utcnow
from almlight.core.deps import current_user
from almlight.core.schemas import UserDirectory
from almlight.modules.identity.models import User
from almlight.modules.items import service as items_svc
from almlight.modules.items.models import Item
from almlight.modules.links.models import Link
from almlight.modules.projects.access import get_project
from almlight.modules.projects.models import Project
from almlight.modules.workflow.models import WorkflowEvent

router = APIRouter(prefix="/projects/{project_key}", tags=["planning"])
DONE = ("released", "closed")


def _date(v: Any) -> date | None:
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def _done_state(project: Project, type_key: str, state: str | None) -> bool:
    wf = project.model.workflow_for(type_key)
    st = wf.state(state) if wf else None
    return bool(st and st.category in DONE)


def plan_of(db: Session, project: Project, release: Item, *, with_items: bool) -> dict[str, Any]:
    sem = project.model.semantics
    rows = db.execute(
        select(Item).join(Link, Link.source_id == Item.id)
        .where(Link.target_id == release.id, Link.type_key == sem.planned_link, Link.deleted_at.is_(None),
               Item.deleted_at.is_(None)).order_by(Item.type_key, Item.seq)
    ).scalars().all()
    by_category: dict[str, int] = defaultdict(int)
    done_ids: list[uuid.UUID] = []
    for it in rows:
        wf = project.model.workflow_for(it.type_key)
        st = wf.state(it.state) if wf else None
        by_category[st.category if st else "none"] += 1
        if st and st.category in DONE:
            done_ids.append(it.id)
    start, due = _date(release.fields.get("start_date")), _date(release.fields.get("due_date"))
    today = utcnow().date()
    rel_wf = project.model.workflow_for(release.type_key)
    rel_state = rel_wf.state(release.state) if rel_wf else None
    total, done = len(rows), len(done_ids)
    finished = bool(rel_state and rel_state.category in ("closed", "obsolete"))
    expected = None
    if start and due and due > start and not finished:
        expected = max(0.0, min(1.0, (today - start).days / (due - start).days))
    status = ("done" if finished else "overdue" if due and due < today
              else "at_risk" if expected is not None and total and done / total + 0.15 < expected else "on_track")
    out: dict[str, Any] = {
        "key": release.key, "title": release.title, "state": release.state,
        "state_label": rel_state.label if rel_state else release.state,
        "state_color": rel_state.color if rel_state else None,
        "start_date": release.fields.get("start_date"), "due_date": release.fields.get("due_date"),
        "goal": release.fields.get("goal"), "total": total, "done": done,
        "progress": round(done / total, 3) if total else 0.0, "expected": expected, "status": status,
        "by_category": dict(by_category),
    }
    if with_items:
        users = UserDirectory(db)
        users.preload({i.owner_id for i in rows})
        out["items"] = []
        for it in rows:
            wf = project.model.workflow_for(it.type_key)
            st = wf.state(it.state) if wf else None
            t = project.model.item_type(it.type_key)
            out["items"].append({"key": it.key, "title": it.title, "type_key": it.type_key,
                                 "type_label": t.label if t else it.type_key, "state": st.label if st else it.state,
                                 "state_category": st.category if st else None, "state_color": st.color if st else None,
                                 "version": it.version_label, "owner": users.ref(it.owner_id),
                                 "done": bool(st and st.category in DONE)})
        # burn-up: cumulative items reaching a done state, per day from the start (or first event) to today/due
        events = db.execute(
            select(WorkflowEvent.item_id, WorkflowEvent.to_state, WorkflowEvent.created_at)
            .where(WorkflowEvent.item_id.in_([i.id for i in rows])).order_by(WorkflowEvent.created_at)
        ).all() if rows else []
        type_of = {i.id: i.type_key for i in rows}
        reached: dict[uuid.UUID, date] = {}
        for iid, to_state, at in events:
            if _done_state(project, type_of[iid], to_state):
                reached.setdefault(iid, at.date())
            elif iid in reached:
                reached.pop(iid)
        first = min([start] + list(reached.values()) if start else list(reached.values()) or [today])
        last = max(today, due) if due else today
        if (last - first).days > 400:
            first = last - timedelta(days=400)
        series = []
        day = first
        while day <= last:
            series.append({"date": day.isoformat(), "done": sum(1 for d in reached.values() if d <= day),
                           "scope": total, "future": day > today})
            day += timedelta(days=1)
        out["burnup"] = series
    return out


@router.get("/plans", summary="Releases and milestones with progress and schedule status")
def plans(project_key: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    sem = project.model.semantics
    t = project.model.item_type(sem.release_type) if sem.release_type else None
    if t is None or project.model.link_type(sem.planned_link) is None:
        return {"enabled": False, "releases": []}
    releases = db.execute(select(Item).where(Item.project_id == project.id, Item.type_key == t.key,
                                             Item.deleted_at.is_(None))).scalars().all()
    out = [plan_of(db, project, r, with_items=False) for r in releases]
    out.sort(key=lambda r: (r["due_date"] or "9999", r["key"]))
    unplanned_types = [lt for lt in project.model.link_type(sem.planned_link).sources]
    return {"enabled": True, "type": t.key, "type_label": t.label, "releases": out, "plannable_types": unplanned_types}


@router.get("/plans/{release_key}", summary="One release with its planned items and burn-up")
def plan(project_key: str, release_key: str, user: User = Depends(current_user),
         db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    release = items_svc.get_item(db, project, release_key)
    return plan_of(db, project, release, with_items=True)
