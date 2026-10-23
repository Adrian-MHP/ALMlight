"""Release planning and the timeline.

*Plans* (Polarion Plans): releases, iterations and milestones form a hierarchy (``part_of``); work is planned with
``planned_in``. A plan's scope includes the work of its sub-plans. Per plan: progress by count and by estimate,
capacity and load, expected progress by today, schedule status, burn-up / burn-down.

*Timeline* (Teamcenter Schedule Manager): plans and tasks as a Gantt chart with finish-to-start dependencies
(``depends_on``), total slack and the critical path, date conflicts, and the dates of a baseline for comparison.
"""

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
from almlight.modules.items.models import Item, ItemVersion
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


def _num(v: Any) -> float:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0


def _state(project: Project, item: Item):
    wf = project.model.workflow_for(item.type_key)
    return wf.state(item.state) if wf else None


def _done(project: Project, type_key: str, state: str | None) -> bool:
    wf = project.model.workflow_for(type_key)
    st = wf.state(state) if wf else None
    return bool(st and st.category in DONE)


def _sub_plans(db: Session, project: Project) -> dict[uuid.UUID, list[uuid.UUID]]:
    """parent plan id -> child plan ids (``part_of``)."""
    sem = project.model.semantics
    out: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    if project.model.link_type(sem.subplan_link) is None:
        return out
    rows = db.execute(select(Link.target_id, Link.source_id).join(Item, Item.id == Link.source_id)
                      .where(Link.type_key == sem.subplan_link, Link.deleted_at.is_(None), Item.deleted_at.is_(None),
                             Item.project_id == project.id)).all()
    for parent, child in rows:
        out[parent].append(child)
    return out


def _descendants(tree: dict[uuid.UUID, list[uuid.UUID]], root: uuid.UUID) -> list[uuid.UUID]:
    out, stack, seen = [], list(tree.get(root, [])), {root}
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        out.append(n)
        stack.extend(tree.get(n, []))
    return out


def plan_of(db: Session, project: Project, release: Item, *, with_items: bool,
            tree: dict[uuid.UUID, list[uuid.UUID]] | None = None) -> dict[str, Any]:
    sem = project.model.semantics
    tree = tree if tree is not None else _sub_plans(db, project)
    scope_ids = [release.id, *_descendants(tree, release.id)]
    pairs = db.execute(
        select(Item, Link.target_id).join(Link, Link.source_id == Item.id)
        .where(Link.target_id.in_(scope_ids), Link.type_key == sem.planned_link, Link.deleted_at.is_(None),
               Item.deleted_at.is_(None)).order_by(Item.type_key, Item.seq)
    ).all()
    rows: list[Item] = []
    planned_in: dict[uuid.UUID, uuid.UUID] = {}
    for it, target in pairs:
        if it.id not in planned_in:
            rows.append(it)
            planned_in[it.id] = target
    est_key, cap_key = sem.estimate_field, sem.capacity_field
    by_category: dict[str, int] = defaultdict(int)
    done_ids: set[uuid.UUID] = set()
    est_total = est_done = 0.0
    for it in rows:
        st = _state(project, it)
        by_category[st.category if st else "none"] += 1
        est = _num(it.fields.get(est_key))
        est_total += est
        if st and st.category in DONE:
            done_ids.add(it.id)
            est_done += est
    start, due = _date(release.fields.get("start_date")), _date(release.fields.get("due_date"))
    today = utcnow().date()
    rel_state = _state(project, release)
    total, done = len(rows), len(done_ids)
    finished = bool(rel_state and rel_state.category in ("closed", "obsolete"))
    expected = None
    if start and due and due > start and not finished:
        expected = max(0.0, min(1.0, (today - start).days / (due - start).days))
    # by estimate only when everything is estimated — otherwise unestimated work would count as nothing
    all_estimated = bool(rows) and all(_num(it.fields.get(est_key)) > 0 for it in rows)
    progress = (est_done / est_total) if est_total and all_estimated else (done / total if total else 0.0)
    status = ("done" if finished else "overdue" if due and due < today and progress < 1
              else "at_risk" if expected is not None and total and progress + 0.15 < expected else "on_track")
    capacity = _num(release.fields.get(cap_key))
    parent = next((p for p, kids in tree.items() if release.id in kids), None)
    children = sorted(db.execute(select(Item).where(Item.id.in_(tree.get(release.id, [])),
                                                    Item.deleted_at.is_(None))).scalars(),
                      key=lambda c: (str(c.fields.get("start_date") or c.fields.get("due_date") or "9999"), c.seq))
    children_ids = [c.id for c in children]
    keys = {c.id: c.key for c in children}
    if parent:
        keys[parent] = db.execute(select(Item.key).where(Item.id == parent)).scalar()
    out: dict[str, Any] = {
        "key": release.key, "title": release.title, "kind": release.fields.get("kind") or "release",
        "state": release.state, "state_label": rel_state.label if rel_state else release.state,
        "state_color": rel_state.color if rel_state else None,
        "start_date": release.fields.get("start_date"), "due_date": release.fields.get("due_date"),
        "goal": release.fields.get("goal"), "total": total, "done": done,
        "progress": round(progress, 3), "expected": expected, "status": status, "by_category": dict(by_category),
        "estimate": round(est_total, 2), "estimate_done": round(est_done, 2), "capacity": capacity or None,
        "load": round(est_total / capacity, 3) if capacity else None,
        "parent": keys.get(parent) if parent else None,
        "children": [keys[c] for c in children_ids if c in keys],
    }
    if with_items:
        users = UserDirectory(db)
        users.preload({i.owner_id for i in rows})
        plan_keys = dict(db.execute(select(Item.id, Item.key).where(Item.id.in_(scope_ids))).all())
        out["items"] = []
        for it in rows:
            st = _state(project, it)
            t = project.model.item_type(it.type_key)
            out["items"].append({"key": it.key, "title": it.title, "type_key": it.type_key,
                                 "type_label": t.label if t else it.type_key, "state": st.label if st else it.state,
                                 "state_category": st.category if st else None, "state_color": st.color if st else None,
                                 "version": it.version_label, "owner": users.ref(it.owner_id),
                                 "done": it.id in done_ids, "estimate": it.fields.get(est_key),
                                 "plan": plan_keys.get(planned_in[it.id])})
        out["child_plans"] = [plan_of(db, project, child, with_items=False, tree=tree) for child in children]
        out["burnup"] = _burnup(db, project, rows, start, due, today, est_key)
    return out


def _burnup(db: Session, project: Project, rows: list[Item], start: date | None, due: date | None, today: date,
            est_key: str) -> list[dict[str, Any]]:
    """Per day: items and estimate done (burn-up) and remaining (burn-down) from the plan start to today/due."""
    events = db.execute(
        select(WorkflowEvent.item_id, WorkflowEvent.to_state, WorkflowEvent.created_at)
        .where(WorkflowEvent.item_id.in_([i.id for i in rows])).order_by(WorkflowEvent.created_at)
    ).all() if rows else []
    type_of = {i.id: i.type_key for i in rows}
    est = {i.id: _num(i.fields.get(est_key)) for i in rows}
    reached: dict[uuid.UUID, date] = {}
    for iid, to_state, at in events:
        if _done(project, type_of[iid], to_state):
            reached.setdefault(iid, at.date())
        elif iid in reached:
            reached.pop(iid)
    first = min([start] + list(reached.values()) if start else list(reached.values()) or [today])
    last = max(today, due) if due else today
    if (last - first).days > 400:
        first = last - timedelta(days=400)
    total, total_est = len(rows), sum(est.values())
    series, day = [], first
    while day <= last:
        done_n = sum(1 for d in reached.values() if d <= day)
        done_e = sum(est[i] for i, d in reached.items() if d <= day)
        series.append({"date": day.isoformat(), "done": done_n, "scope": total, "remaining": total - done_n,
                       "done_estimate": round(done_e, 2), "scope_estimate": round(total_est, 2),
                       "remaining_estimate": round(total_est - done_e, 2), "future": day > today})
        day += timedelta(days=1)
    return series


@router.get("/plans", summary="Plans (releases, iterations, milestones) with progress, load and schedule status")
def plans(project_key: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    sem = project.model.semantics
    t = project.model.item_type(sem.release_type) if sem.release_type else None
    if t is None or project.model.link_type(sem.planned_link) is None:
        return {"enabled": False, "releases": []}
    releases = db.execute(select(Item).where(Item.project_id == project.id, Item.type_key == t.key,
                                             Item.deleted_at.is_(None))).scalars().all()
    tree = _sub_plans(db, project)
    out = [plan_of(db, project, r, with_items=False, tree=tree) for r in releases]
    out.sort(key=lambda r: (r["start_date"] or r["due_date"] or "9999", r["key"]))
    plannable = list(project.model.link_type(sem.planned_link).sources)
    return {"enabled": True, "type": t.key, "type_label": t.label, "releases": out, "plannable_types": plannable,
            "estimate_field": sem.estimate_field, "hierarchy": project.model.link_type(sem.subplan_link) is not None}


@router.get("/plans/{release_key}", summary="One plan with its planned items, sub-plans and burn-up/burn-down")
def plan(project_key: str, release_key: str, user: User = Depends(current_user),
         db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    release = items_svc.get_item(db, project, release_key)
    return plan_of(db, project, release, with_items=True)


# --- timeline ---------------------------------------------------------------------------------------------------


def _prev_workday(d: date) -> date:
    d -= timedelta(days=1)
    while d.weekday() >= 5:  # a Friday finish before a Monday start leaves no slack
        d -= timedelta(days=1)
    return d


def _slack(nodes: dict[str, dict[str, Any]], preds: dict[str, list[str]], deadline: dict[str, date]) -> None:
    """Total slack in days with fixed dates: how far a node could slip before a successor or its deadline moves.
    Negative slack = the successor already starts before this node finishes (or the deadline is missed)."""
    succs: dict[str, list[str]] = defaultdict(list)
    for n, ps in preds.items():
        for p in ps:
            succs[p].append(n)
    late_finish: dict[str, date] = {}

    def lf(n: str, depth: int = 0) -> date:
        if n in late_finish:
            return late_finish[n]
        node = nodes[n]
        limit = deadline.get(n, node["_due"])
        if depth < 200:
            for s in succs.get(n, []):
                sn = nodes[s]
                duration = (sn["_due"] - sn["_start"]).days
                late_start = lf(s, depth + 1) - timedelta(days=duration)
                limit = min(limit, late_start if sn["kind"] == "milestone" else _prev_workday(late_start))
        late_finish[n] = limit
        return limit

    for n, node in nodes.items():
        node["slack"] = _workdays(node["_due"], lf(n))


def _workdays(a: date, b: date) -> int:
    """Working days (Mon–Fri) from a to b: positive if b is later, negative if earlier, 0 on the same day."""
    if a == b:
        return 0
    sign, lo, hi = (1, a, b) if b > a else (-1, b, a)
    n, d = 0, lo
    while d < hi:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return sign * n


@router.get("/timeline", summary="Gantt data: plans and tasks with dates, progress, dependencies, slack, baseline")
def timeline(project_key: str, baseline: uuid.UUID | None = None, user: User = Depends(current_user),
             db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    sem = project.model.semantics
    types = [t for t in (sem.release_type, sem.task_type) if t and project.model.item_type(t)]
    if not types:
        return {"enabled": False, "rows": []}
    items = db.execute(select(Item).where(Item.project_id == project.id, Item.type_key.in_(types),
                                          Item.deleted_at.is_(None)).order_by(Item.seq)).scalars().all()
    ids = {i.id: i for i in items}
    tree = _sub_plans(db, project)
    parent_of = {c: p for p, kids in tree.items() for c in kids}
    planned = dict(db.execute(select(Link.source_id, Link.target_id).where(
        Link.source_id.in_(list(ids)), Link.type_key == sem.planned_link, Link.deleted_at.is_(None))).all()) \
        if ids else {}
    deps: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    if project.model.link_type(sem.dependency_link) and ids:
        for src, tgt in db.execute(select(Link.source_id, Link.target_id).where(
                Link.source_id.in_(list(ids)), Link.type_key == sem.dependency_link, Link.deleted_at.is_(None))):
            if tgt in ids:
                deps[src].append(tgt)
    users = UserDirectory(db)
    users.preload({i.owner_id for i in items})
    rows: list[dict[str, Any]] = []
    for it in items:
        st = _state(project, it)
        is_task = it.type_key == sem.task_type
        kind = "task" if is_task else (it.fields.get("kind") or "release")
        if is_task:
            progress = 1.0 if st and st.category in DONE else _num(it.fields.get("progress")) / 100
        else:
            progress = plan_of(db, project, it, with_items=False, tree=tree)["progress"]
        parent_id = parent_of.get(it.id) if not is_task else planned.get(it.id)
        start, due = _date(it.fields.get("start_date")), _date(it.fields.get("due_date"))
        if kind == "milestone" and due and not start:
            start = due
        rows.append({
            "key": it.key, "title": it.title, "type_key": it.type_key, "kind": kind,
            "start_date": start.isoformat() if start else None, "due_date": due.isoformat() if due else None,
            "progress": round(progress, 3), "state": it.state, "state_label": st.label if st else it.state,
            "state_category": st.category if st else None, "color": st.color if st else None,
            "frozen": bool(st and st.frozen), "owner": users.ref(it.owner_id),
            "parent": ids[parent_id].key if parent_id in ids else None,
            "depends_on": [ids[d].key for d in deps.get(it.id, [])],
            "_start": start, "_due": due, "_id": it.id,
        })
    dated = {r["key"]: r for r in rows if r["_start"] and r["_due"]}
    preds = {k: [d for d in r["depends_on"] if d in dated] for k, r in dated.items()}
    deadline = {}
    for k, r in dated.items():
        plan_key = r["parent"]
        if r["kind"] == "task" and plan_key in dated:
            deadline[k] = dated[plan_key]["_due"]
    _slack(dated, preds, deadline)
    conflicts = []
    for k, ps in preds.items():
        for p in ps:
            if dated[k]["_start"] <= dated[p]["_due"] and dated[k]["kind"] != "milestone":
                conflicts.append({"item": k, "depends_on": p,
                                  "message": f"{k} starts {dated[k]['_start']} but {p} finishes {dated[p]['_due']}"})
            elif dated[k]["kind"] == "milestone" and dated[k]["_due"] < dated[p]["_due"]:
                conflicts.append({"item": k, "depends_on": p,
                                  "message": f"Milestone {k} ({dated[k]['_due']}) is before {p} finishes"})
    linked = {k for k, ps in preds.items() if ps} | {p for ps in preds.values() for p in ps}
    for r in rows:
        r["critical"] = r["key"] in dated and r.get("slack", 1) <= 0 and (r["key"] in linked or r["kind"] == "task")
    base: dict[str, Any] = {}
    if baseline is not None:
        from almlight.modules.baselines.models import Baseline, BaselineItem

        bl = db.get(Baseline, baseline)
        if bl is not None and bl.project_id == project.id:
            versions = db.execute(select(BaselineItem.item_id, ItemVersion.fields).join(
                ItemVersion, ItemVersion.id == BaselineItem.version_id).where(
                BaselineItem.baseline_id == bl.id, BaselineItem.item_id.in_(list(ids)))).all()
            for iid, fields in versions:
                base[ids[iid].key] = {"start_date": fields.get("start_date"), "due_date": fields.get("due_date")}
    for r in rows:
        r.pop("_start"), r.pop("_due"), r.pop("_id")
        r["baseline"] = base.get(r["key"])
    starts = [r["start_date"] for r in rows if r["start_date"]]
    dues = [r["due_date"] for r in rows if r["due_date"]]
    return {"enabled": True, "rows": rows, "conflicts": conflicts, "today": utcnow().date().isoformat(),
            "range": [min(starts + dues) if starts or dues else None, max(starts + dues) if starts or dues else None],
            "task_type": sem.task_type if project.model.item_type(sem.task_type or "") else None,
            "release_type": sem.release_type, "dependency_link": sem.dependency_link
            if project.model.link_type(sem.dependency_link) else None}
