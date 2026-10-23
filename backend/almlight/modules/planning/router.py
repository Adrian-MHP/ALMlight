"""Release planning and the timeline.

*Plans* (Polarion Plans): releases, iterations and milestones form a hierarchy (``part_of``); work is planned with
``planned_in``. A plan's scope includes the work of its sub-plans. Per plan: progress by count and by estimate,
capacity and load, expected progress by today, schedule status, burn-up / burn-down.

*Timeline* (Teamcenter Schedule Manager): plans and tasks as a Gantt chart with dependencies (``depends_on``:
finish-to-start, start-to-start, finish-to-finish, start-to-finish, with lag), total slack and the critical path, date
conflicts, the dates of a baseline for comparison, and auto-scheduling along the dependencies.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from almlight.core.db import get_db, utcnow
from almlight.core.deps import current_user
from almlight.core.errors import DomainError
from almlight.core.schemas import UserDirectory
from almlight.modules.identity.models import User
from almlight.modules.items import service as items_svc
from almlight.modules.items.models import Item, ItemVersion
from almlight.modules.links.models import Link
from almlight.modules.planning import schedule as sched
from almlight.modules.projects.access import get_project, require_role
from almlight.modules.projects.models import Project, ProjectMember
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


def _deps(db: Session, project: Project, ids: dict[uuid.UUID, Item]) -> list[tuple[Link, sched.Dep]]:
    sem = project.model.semantics
    if not ids or project.model.link_type(sem.dependency_link) is None:
        return []
    out = []
    for link in db.execute(select(Link).where(Link.source_id.in_(list(ids)), Link.type_key == sem.dependency_link,
                                              Link.deleted_at.is_(None))).scalars():
        if link.target_id not in ids:
            continue
        kind = str(link.attributes.get(sem.dependency_type_attribute) or "fs").lower()
        lag = link.attributes.get(sem.dependency_lag_attribute)
        lag = int(lag) if isinstance(lag, (int, float)) and not isinstance(lag, bool) else 0
        out.append((link, sched.Dep(pred=ids[link.target_id].key, succ=ids[link.source_id].key,
                                    type=kind if kind in sched.DEP_TYPES else "fs",  # type: ignore[arg-type]
                                    lag=lag)))
    return out


def _schedule(db: Session, project: Project) -> tuple[list[dict[str, Any]], dict[uuid.UUID, Item], list[sched.Dep]]:
    """Timeline rows (with internal ``_start``/``_due``/``_id``), the items and the dependencies between them."""
    sem = project.model.semantics
    types = [t for t in (sem.release_type, sem.task_type) if t and project.model.item_type(t)]
    items = db.execute(select(Item).where(Item.project_id == project.id, Item.type_key.in_(types),
                                          Item.deleted_at.is_(None)).order_by(Item.seq)).scalars().all()
    ids = {i.id: i for i in items}
    tree = _sub_plans(db, project)
    parent_of = {c: p for p, kids in tree.items() for c in kids}
    planned = dict(db.execute(select(Link.source_id, Link.target_id).where(
        Link.source_id.in_(list(ids)), Link.type_key == sem.planned_link, Link.deleted_at.is_(None))).all()) \
        if ids else {}
    deps = _deps(db, project, ids)
    by_succ: dict[str, list[tuple[Link, sched.Dep]]] = defaultdict(list)
    for link, d in deps:
        by_succ[d.succ].append((link, d))
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
        mine = by_succ.get(it.key, [])
        rows.append({
            "key": it.key, "title": it.title, "type_key": it.type_key, "kind": kind,
            "start_date": start.isoformat() if start else None, "due_date": due.isoformat() if due else None,
            "progress": round(progress, 3), "state": it.state, "state_label": st.label if st else it.state,
            "state_category": st.category if st else None, "color": st.color if st else None,
            "frozen": bool(st and st.frozen), "owner": users.ref(it.owner_id),
            "estimate": _num(it.fields.get(sem.estimate_field)) or None,
            "parent": ids[parent_id].key if parent_id in ids else None,
            "depends_on": [d.pred for _, d in mine],
            "dependencies": [{"key": d.pred, "type": d.type, "lag": d.lag, "link_id": str(link.id)}
                             for link, d in mine],
            "_start": start, "_due": due, "_id": it.id, "_has_start": bool(it.fields.get("start_date")),
        })
    return rows, ids, [d for _, d in deps]


def _deadlines(dated: dict[str, dict[str, Any]]) -> dict[str, date]:
    """Late-finish limit per task: the due date of the plan it belongs to, else the project finish (the latest finish
    of all dated work) — so only the longest chain of unplanned work is critical, as in Schedule Manager/MS Project."""
    if not dated:
        return {}
    project_end = max(r["_due"] for r in dated.values())
    out = {}
    for k, r in dated.items():
        if r["kind"] == "task":
            plan = dated.get(r["parent"]) if r["parent"] else None
            out[k] = plan["_due"] if plan else project_end
    return out


def _dated(rows: list[dict[str, Any]], deps: list[sched.Dep]) -> tuple[dict[str, dict[str, Any]], list[sched.Dep]]:
    dated = {r["key"]: r for r in rows if r["_start"] and r["_due"]}
    return dated, [d for d in deps if d.pred in dated and d.succ in dated]


@router.get("/timeline", summary="Gantt data: plans and tasks with dates, progress, dependencies, slack, baseline")
def timeline(project_key: str, baseline: uuid.UUID | None = None, user: User = Depends(current_user),
             db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    sem = project.model.semantics
    if not any(t and project.model.item_type(t) for t in (sem.release_type, sem.task_type)):
        return {"enabled": False, "rows": []}
    rows, ids, deps = _schedule(db, project)
    dated, live = _dated(rows, deps)
    sched.slack(dated, live, _deadlines(dated))
    conflicts = [{"item": d.succ, "depends_on": d.pred, "type": d.type, "lag": d.lag,
                  "message": sched.conflict_message(dated, d)} for d in live if sched.violated(dated, d)]
    linked = {d.succ for d in live} | {d.pred for d in live}
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
        for k in ("_start", "_due", "_id", "_has_start"):
            r.pop(k)
        r["baseline"] = base.get(r["key"])
    starts = [r["start_date"] for r in rows if r["start_date"]]
    dues = [r["due_date"] for r in rows if r["due_date"]]
    lt = project.model.link_type(sem.dependency_link)
    return {"enabled": True, "rows": rows, "conflicts": conflicts, "today": utcnow().date().isoformat(),
            "range": [min(starts + dues) if starts or dues else None, max(starts + dues) if starts or dues else None],
            "task_type": sem.task_type if project.model.item_type(sem.task_type or "") else None,
            "release_type": sem.release_type, "dependency_link": sem.dependency_link if lt else None,
            "dependency_types": bool(lt and any(a.key == sem.dependency_type_attribute for a in lt.attributes)),
            "dependency_type_attribute": sem.dependency_type_attribute,
            "dependency_lag_attribute": sem.dependency_lag_attribute}


class ScheduleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["push", "asap"] = "push"
    dry_run: bool = True
    plan: str | None = Field(default=None, description="Only move work planned in this plan (incl. its sub-plans)")


def _fixed(db: Session, project: Project, ids: dict[uuid.UUID, Item], dated: dict[str, dict[str, Any]],
           plan: str | None) -> dict[str, str]:
    """Items that keep their dates when scheduling or levelling, with the reason."""
    scope: set[str] | None = None
    if plan:
        root = items_svc.get_item(db, project, plan)
        tree = _sub_plans(db, project)
        plans = {ids[i].key for i in (root.id, *_descendants(tree, root.id)) if i in ids}
        scope = {k for k, r in dated.items() if r["parent"] in plans or k in plans}
    fixed: dict[str, str] = {}
    for k, r in dated.items():
        if r["kind"] not in ("task", "milestone"):
            fixed[k] = "plans keep their dates"
        elif r["frozen"]:
            fixed[k] = "frozen"
        elif r["state_category"] in DONE:
            fixed[k] = "finished"
        elif r["kind"] == "task" and r["progress"] > 0:
            fixed[k] = "already started"
        elif scope is not None and k not in scope:
            fixed[k] = "outside the chosen plan"
    return fixed


def _apply_moves(db: Session, project: Project, user: User, ids: dict[uuid.UUID, Item],
                 dated: dict[str, dict[str, Any]], old: dict[str, tuple[date, date]],
                 moved: dict[str, tuple[date, date]], note: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Save each move as an ordinary item change (own savepoint); a refused move keeps the old dates."""
    by_key = {i.key: i for i in ids.values()}
    results, summary = [], {"ok": 0, "skipped": 0}
    for k, (start, due) in moved.items():
        r, it = dated[k], by_key[k]
        with_start = r["_has_start"] or r["kind"] == "task"
        fields = {"due_date": due.isoformat()}
        if with_start:
            fields["start_date"] = start.isoformat()
        sp = db.begin_nested()
        try:
            items_svc.update_item(db, project, user, it, items_svc.ContentChange(fields=fields), change_note=note)
            sp.commit()
            status, message = "ok", None
        except DomainError as exc:
            sp.rollback()
            status, message = "skipped", exc.message
            r["_start"], r["_due"] = old[k]
        summary[status] += 1
        o_start, o_due = old[k]
        results.append({"key": k, "title": r["title"], "status": status, "message": message,
                        "shift": sched.workdays(o_due, due),
                        "start_date": [o_start.isoformat() if with_start else None,
                                       start.isoformat() if with_start else None],
                        "due_date": [o_due.isoformat(), due.isoformat()]})
    return results, summary


def _remaining(dated: dict[str, dict[str, Any]], live: list[sched.Dep], fixed: dict[str, str]) -> list[dict[str, Any]]:
    out = []
    for d in live:
        if sched.violated(dated, d):
            why = fixed.get(d.succ)
            message = sched.conflict_message(dated, d) + (f" — {d.succ}: {why}" if why else "")
            out.append({"item": d.succ, "depends_on": d.pred, "type": d.type, "message": message})
    return out


@router.post("/timeline/schedule", summary="Auto-schedule: move tasks and milestones so their dependencies hold")
def auto_schedule(project_key: str, body: ScheduleIn, user: User = Depends(current_user),
                  db: Session = Depends(get_db)) -> dict[str, Any]:
    """Forward pass over the dependencies. *push* moves successors later where a dependency is violated; *asap*
    also pulls dependent work in to the earliest date its predecessors allow. Plans (releases, iterations), frozen,
    started and finished items keep their dates. A dry run returns the moves without saving them; applying saves each
    move as an ordinary item change."""
    project = get_project(db, project_key, user)
    require_role(db, project, user, "contributor")
    rows, ids, deps = _schedule(db, project)
    dated, live = _dated(rows, deps)
    fixed = _fixed(db, project, ids, dated, body.plan)
    old = {k: (r["_start"], r["_due"]) for k, r in dated.items()}
    moved = sched.forward(dated, live, set(dated) - set(fixed), body.mode)
    results, summary = _apply_moves(db, project, user, ids, dated, old, moved,
                                    f"Scheduled from dependencies ({body.mode})")
    remaining = _remaining(dated, live, fixed)
    if body.dry_run:
        db.rollback()
    else:
        db.commit()
    return {"dry_run": body.dry_run, "mode": body.mode, "moves": results, "summary": summary,
            "remaining_conflicts": remaining}


# --- resources ----------------------------------------------------------------------------------------------------


def _resource_input(db: Session, project: Project, dated: dict[str, dict[str, Any]], ids: dict[uuid.UUID, Item]):
    """Owner, remaining hours (None = full-time) and hours per day for the dated tasks."""
    from almlight.modules.worklog.router import effort, spent_by_item

    by_key = {i.key: i for i in ids.values()}
    tasks = [k for k, r in dated.items() if r["kind"] == "task"]
    spent = spent_by_item(db, [by_key[k].id for k in tasks])
    owner: dict[str, str | None] = {}
    hours: dict[str, float | None] = {}
    for k in tasks:
        it = by_key[k]
        owner[k] = str(it.owner_id) if it.owner_id else None
        e = effort(project, it, spent.get(it.id, 0.0))
        hours[k] = e["remaining"]
    members = db.execute(select(ProjectMember.user_id, ProjectMember.hours_per_day)
                         .where(ProjectMember.project_id == project.id, ProjectMember.role != "viewer")).all()
    per_day = {str(u): h for u, h in members}  # readers are no resources (unless they own work, then 8 h/day)
    return owner, hours, per_day, spent


def _week_table(load: dict[str, dict[date, float]], start: date, weeks: int, per_day: dict[str, float],
                people: list[str]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for u in people:
        row = []
        for w in range(weeks):
            ws = start + timedelta(days=7 * w)
            planned = sum(load.get(u, {}).get(ws + timedelta(days=i), 0.0) for i in range(7))
            capacity = per_day.get(u, 8.0) * 5
            row.append({"week": ws.isoformat(), "planned": round(planned, 1), "capacity": capacity,
                        "load": round(planned / capacity, 3) if capacity else None})
        out[u] = row
    return out


@router.get("/resources", summary="Resource load: planned hours per person and week against capacity, and actuals")
def resources(project_key: str, start: date | None = None, weeks: int = Query(default=12, ge=1, le=52),
              user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Planned load counts the remaining work of open tasks (estimate − recorded time, in hours), spread evenly over
    their working days from today on; a task without an estimate counts as full-time. Actuals are the recorded hours."""
    from almlight.modules.worklog.models import WorkRecord

    project = get_project(db, project_key, user)
    today = utcnow().date()
    first = start or today
    first -= timedelta(days=first.weekday())
    rows, ids, deps = _schedule(db, project)
    dated, _ = _dated(rows, deps)
    owner, hours, per_day, _ = _resource_input(db, project, dated, ids)
    load: dict[str, dict[date, float]] = defaultdict(lambda: defaultdict(float))
    contrib: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    unassigned: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for k, u in owner.items():
        r = dated[k]
        if r["state_category"] in DONE or hours[k] == 0:
            continue
        cap = per_day.get(u or "", 8.0)
        for day, h in sched.allocation(r["_start"], r["_due"], hours[k], cap, today).items():
            week = (day - timedelta(days=day.weekday())).isoformat()
            if u:
                load[u][day] += h
                contrib[(u, week)][k] += h
            else:
                unassigned[week][k] += h
    last = first + timedelta(days=7 * weeks - 1)
    actual: dict[tuple[str, str], float] = defaultdict(float)
    for uid, day, h in db.execute(select(WorkRecord.user_id, WorkRecord.day, WorkRecord.hours).where(
            WorkRecord.project_id == project.id, WorkRecord.day >= first, WorkRecord.day <= last)):
        actual[(str(uid), (day - timedelta(days=day.weekday())).isoformat())] += h
    people = sorted(set(per_day) | {u for u in owner.values() if u} | {u for u, _ in actual})
    all_members = {str(u) for u in db.execute(select(ProjectMember.user_id).where(
        ProjectMember.project_id == project.id)).scalars()}
    users = UserDirectory(db)
    users.preload({uuid.UUID(u) for u in people})
    table = _week_table(load, first, weeks, per_day, people)
    titles = {k: r["title"] for k, r in dated.items()}
    out_people = []
    for u in people:
        ref = users.ref(u)
        if ref is None:
            continue
        cells = []
        for c in table[u]:
            items = sorted(contrib.get((u, c["week"]), {}).items(), key=lambda x: -x[1])
            cells.append({**c, "actual": round(actual.get((u, c["week"]), 0.0), 2),
                          "items": [{"key": k, "title": titles[k], "hours": round(h, 1)} for k, h in items]})
        if not any(c["planned"] or c["actual"] for c in cells) and u not in per_day:
            continue
        out_people.append({"user": ref, "hours_per_day": per_day.get(u, 8.0), "member": u in all_members,
                           "weeks": cells, "overloaded": sum(1 for c in cells if c["load"] and c["load"] > 1.0001)})
    out_people.sort(key=lambda p: p["user"].display_name.lower())
    week_keys = [(first + timedelta(days=7 * w)).isoformat() for w in range(weeks)]
    return {"start": first.isoformat(), "weeks": week_keys, "today": today.isoformat(), "people": out_people,
            "unassigned": [{"week": w, "planned": round(sum(unassigned.get(w, {}).values()), 1),
                            "items": [{"key": k, "title": titles[k], "hours": round(h, 1)}
                                      for k, h in sorted(unassigned.get(w, {}).items(), key=lambda x: -x[1])]}
                           for w in week_keys]}


class LevelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dry_run: bool = True
    plan: str | None = Field(default=None, description="Only move work planned in this plan (incl. its sub-plans)")


@router.post("/resources/level", summary="Resource levelling: delay tasks until their owners have room")
def level_resources(project_key: str, body: LevelIn, user: User = Depends(current_user),
                    db: Session = Depends(get_db)) -> dict[str, Any]:
    """Greedy levelling (Teamcenter/MS Project style): tasks of overloaded people move later, never earlier, by
    working days and keep their duration and dependencies. Started, frozen and finished work keeps its dates; a dry
    run shows the moves and the overloads that remain."""
    project = get_project(db, project_key, user)
    require_role(db, project, user, "contributor")
    today = utcnow().date()
    rows, ids, deps = _schedule(db, project)
    dated, live = _dated(rows, deps)
    fixed = _fixed(db, project, ids, dated, body.plan)
    owner, hours, per_day, _ = _resource_input(db, project, dated, ids)
    sched.slack(dated, live, _deadlines(dated))
    old = {k: (r["_start"], r["_due"]) for k, r in dated.items()}
    moved, load = sched.level(dated, live, set(dated) - set(fixed), owner, hours, per_day, today)
    results, summary = _apply_moves(db, project, user, ids, dated, old, moved, "Resource levelling")
    users = UserDirectory(db)
    overloads = []
    horizon = max([d for u in load.values() for d in u] or [today])
    first = today - timedelta(days=today.weekday())
    weeks = min(52, (horizon - first).days // 7 + 1)
    for u, cells in _week_table(load, first, weeks, per_day, sorted(load)).items():
        for c in cells:
            if c["load"] and c["load"] > 1.0001:
                ref = users.ref(u)
                overloads.append({"user": ref, "week": c["week"], "planned": c["planned"], "capacity": c["capacity"]})
    remaining = _remaining(dated, live, fixed)
    if body.dry_run:
        db.rollback()
    else:
        db.commit()
    return {"dry_run": body.dry_run, "mode": "level", "moves": results, "summary": summary,
            "remaining_overloads": overloads, "remaining_conflicts": remaining}
