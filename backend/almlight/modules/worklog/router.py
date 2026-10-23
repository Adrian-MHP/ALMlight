"""Time recording: work records on items and the weekly timesheet.

A work record is the hours one person worked on one item on one day. Records are actuals (not in the future) and do
not change the item (no new version; frozen and released items can be booked on). Spent and remaining effort
(estimate − spent) are shown on the item and feed the resource view of the timeline.

Privacy: everybody sees the total spent on an item; individual records are visible to their author and to project
managers only (works-council friendly default).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from almlight.core.db import get_db, utcnow
from almlight.core.deps import current_user
from almlight.core.errors import Forbidden, NotFound, ValidationFailed
from almlight.core.schemas import UserDirectory
from almlight.modules.audit import service as audit
from almlight.modules.identity.models import User
from almlight.modules.items import service as items_svc
from almlight.modules.items.models import Item
from almlight.modules.projects.access import get_project, has_role
from almlight.modules.projects.models import Project, ProjectMember
from almlight.modules.worklog.models import WorkRecord

router = APIRouter(prefix="/projects/{project_key}", tags=["time recording"])
DONE = ("released", "closed")
MAX_DAY = 24.0


class WorkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    day: date
    hours: float = Field(gt=0, le=MAX_DAY)
    comment: str | None = Field(default=None, max_length=2000)


class WorkPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    day: date | None = None
    hours: float | None = Field(default=None, gt=0, le=MAX_DAY)
    comment: str | None = Field(default=None, max_length=2000)


class CellIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item: str
    day: date
    hours: float = Field(ge=0, le=MAX_DAY)


def spent_by_item(db: Session, item_ids: list[uuid.UUID]) -> dict[uuid.UUID, float]:
    if not item_ids:
        return {}
    rows = db.execute(select(WorkRecord.item_id, func.sum(WorkRecord.hours)).where(
        WorkRecord.item_id.in_(item_ids)).group_by(WorkRecord.item_id)).all()
    return {i: round(float(h), 2) for i, h in rows}


def effort(project: Project, item: Item, spent: float) -> dict[str, Any]:
    """Estimate, spent and remaining effort of an item (remaining 0 when finished)."""
    v = item.fields.get(project.model.semantics.estimate_field)
    estimate = float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else None
    wf = project.model.workflow_for(item.type_key)
    st = wf.state(item.state) if wf else None
    done = bool(st and st.category in DONE)
    remaining = 0.0 if done else (round(max(estimate - spent, 0.0), 2) if estimate is not None else None)
    return {"estimate": estimate, "spent": round(spent, 2), "remaining": remaining, "done": done,
            "over": estimate is not None and spent > estimate}


def _check_day(db: Session, user: User, day: date, hours: float, *, ignore: list[uuid.UUID] | None = None) -> None:
    if day > utcnow().date():
        raise ValidationFailed("Time is recorded for today or earlier days, not for the future")
    q = select(func.coalesce(func.sum(WorkRecord.hours), 0)).where(WorkRecord.user_id == user.id,
                                                                   WorkRecord.day == day)
    if ignore:
        q = q.where(WorkRecord.id.notin_(ignore))
    booked = float(db.execute(q).scalar_one())
    if booked + hours > MAX_DAY + 1e-9:
        raise ValidationFailed(f"{day} would have {booked + hours:g} h — a day has at most {MAX_DAY:g} h")


def _record_out(r: WorkRecord, users: UserDirectory, me: User, manager: bool) -> dict[str, Any]:
    return {"id": str(r.id), "user": users.ref(r.user_id), "day": r.day.isoformat(), "hours": r.hours,
            "comment": r.comment, "created_at": r.created_at.isoformat(),
            "can_edit": r.user_id == me.id or manager}


def _audit(db: Session, user: User, project: Project, item: Item, action: str, summary: str,
           details: dict[str, Any]) -> None:
    audit.record(db, actor=user, action=action, entity_type="item", entity_id=item.id, project_id=project.id,
                 summary=summary, details=details, related_ids=[item.id])


@router.get("/items/{item_key}/work", summary="Time recorded on an item: totals, and the records you may see")
def item_work(project_key: str, item_key: str, user: User = Depends(current_user),
              db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    item = items_svc.get_item(db, project, item_key)
    manager = has_role(db, project, user, "manager")
    records = db.execute(select(WorkRecord).where(WorkRecord.item_id == item.id)
                         .order_by(WorkRecord.day.desc(), WorkRecord.created_at.desc())).scalars().all()
    users = UserDirectory(db)
    users.preload({r.user_id for r in records})
    spent = sum(r.hours for r in records)
    visible = [r for r in records if manager or r.user_id == user.id]
    by_user: dict[uuid.UUID, float] = defaultdict(float)
    for r in records:
        by_user[r.user_id] += r.hours
    out = {**effort(project, item, spent), "records": [_record_out(r, users, user, manager) for r in visible],
           "mine": round(sum(r.hours for r in records if r.user_id == user.id), 2),
           "can_record": has_role(db, project, user, "contributor"), "all_visible": manager}
    if manager:
        out["by_user"] = [{"user": users.ref(u), "hours": round(h, 2)}
                          for u, h in sorted(by_user.items(), key=lambda x: -x[1])]
    return out


@router.post("/items/{item_key}/work", status_code=201, summary="Record time on an item")
def record_work(project_key: str, item_key: str, body: WorkIn, user: User = Depends(current_user),
                db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user, "contributor")
    item = items_svc.get_item(db, project, item_key)
    _check_day(db, user, body.day, body.hours)
    r = WorkRecord(project_id=project.id, item_id=item.id, user_id=user.id, day=body.day,
                   hours=round(body.hours, 2), comment=(body.comment or "").strip() or None)
    db.add(r)
    db.flush()
    _audit(db, user, project, item, "work.recorded", f"Recorded {r.hours:g} h on {item.key} ({r.day})",
           {"record": str(r.id), "day": r.day.isoformat(), "hours": r.hours})
    db.commit()
    return _record_out(r, UserDirectory(db), user, False)


def _own_record(db: Session, project: Project, user: User, record_id: uuid.UUID) -> tuple[WorkRecord, Item]:
    r = db.get(WorkRecord, record_id)
    if r is None or r.project_id != project.id:
        raise NotFound("Work record not found")
    if r.user_id != user.id and not has_role(db, project, user, "manager"):
        raise Forbidden("Only the author or a project manager can change a work record")
    return r, db.get(Item, r.item_id)  # type: ignore[return-value]


@router.patch("/work/{record_id}", summary="Change a work record (author or manager)")
def change_work(project_key: str, record_id: uuid.UUID, body: WorkPatch, user: User = Depends(current_user),
                db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user, "contributor")
    r, item = _own_record(db, project, user, record_id)
    sent = body.model_dump(exclude_unset=True)
    day, hours = sent.get("day") or r.day, sent.get("hours") or r.hours
    author = db.get(User, r.user_id)
    _check_day(db, author, day, hours, ignore=[r.id])  # type: ignore[arg-type]
    before = {"day": r.day.isoformat(), "hours": r.hours, "comment": r.comment}
    r.day, r.hours = day, round(hours, 2)
    if "comment" in sent:
        r.comment = (body.comment or "").strip() or None
    r.updated_at = utcnow()
    _audit(db, user, project, item, "work.changed", f"Changed time record on {item.key}: {r.hours:g} h ({r.day})",
           {"record": str(r.id), "before": before, "after": {"day": r.day.isoformat(), "hours": r.hours,
                                                            "comment": r.comment}})
    db.commit()
    return _record_out(r, UserDirectory(db), user, True)


@router.delete("/work/{record_id}", summary="Delete a work record (author or manager)")
def delete_work(project_key: str, record_id: uuid.UUID, user: User = Depends(current_user),
                db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user, "contributor")
    r, item = _own_record(db, project, user, record_id)
    _audit(db, user, project, item, "work.deleted", f"Deleted time record on {item.key} ({r.hours:g} h, {r.day})",
           {"record": str(r.id), "day": r.day.isoformat(), "hours": r.hours, "user": str(r.user_id)})
    db.delete(r)
    db.commit()
    return {"ok": True}


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _hours_per_day(db: Session, project: Project, user_id: uuid.UUID) -> float:
    m = db.get(ProjectMember, (project.id, user_id))
    return m.hours_per_day if m is not None else 8.0


@router.get("/timesheet", summary="A person's week: hours per item and day (own week; managers any member)")
def timesheet(project_key: str, week: date | None = None, user_name: str | None = Query(default=None, alias="user"),
              user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    who = user
    if user_name and user_name not in ("me", user.username):
        if not has_role(db, project, user, "manager"):
            raise Forbidden("Only project managers can see other people's timesheets")
        who = db.execute(select(User).where(User.username == user_name)).scalar_one_or_none()
        if who is None:
            raise NotFound(f"User '{user_name}' not found")
    start = _monday(week or utcnow().date())
    days = [start + timedelta(days=i) for i in range(7)]
    records = db.execute(select(WorkRecord).where(
        WorkRecord.project_id == project.id, WorkRecord.user_id == who.id, WorkRecord.day >= days[0],
        WorkRecord.day <= days[-1])).scalars().all()
    sem = project.model.semantics
    item_ids = {r.item_id for r in records}
    open_tasks = []
    if sem.task_type and project.model.item_type(sem.task_type):
        for t in db.execute(select(Item).where(Item.project_id == project.id, Item.type_key == sem.task_type,
                                               Item.owner_id == who.id, Item.deleted_at.is_(None))).scalars():
            s, d = t.fields.get("start_date"), t.fields.get("due_date")
            wf = project.model.workflow_for(t.type_key)
            st = wf.state(t.state) if wf else None
            if st and st.category in DONE:
                continue
            if (not s or str(s) <= days[-1].isoformat()) and (not d or str(d) >= days[0].isoformat()):
                open_tasks.append(t.id)
    ids = list(item_ids | set(open_tasks))
    items = {i.id: i for i in db.execute(select(Item).where(Item.id.in_(ids), Item.deleted_at.is_(None))).scalars()} \
        if ids else {}
    spent = spent_by_item(db, list(items))
    cells: dict[uuid.UUID, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for r in records:
        cells[r.item_id][r.day.isoformat()] += r.hours
    rows = []
    for iid, it in items.items():
        hours = {k: round(v, 2) for k, v in cells.get(iid, {}).items()}
        wf = project.model.workflow_for(it.type_key)
        st = wf.state(it.state) if wf else None
        rows.append({"key": it.key, "title": it.title, "type_key": it.type_key,
                     "state_label": st.label if st else it.state, "hours": hours,
                     "total": round(sum(hours.values()), 2), **effort(project, it, spent.get(iid, 0.0))})
    rows.sort(key=lambda r: (-r["total"], r["key"]))
    totals = {d.isoformat(): round(sum(r["hours"].get(d.isoformat(), 0) for r in rows), 2) for d in days}
    hpd = _hours_per_day(db, project, who.id)
    return {"week": start.isoformat(), "days": [d.isoformat() for d in days], "today": utcnow().date().isoformat(),
            "user": UserDirectory(db).ref(who.id), "editable": who.id == user.id
            and has_role(db, project, user, "contributor"), "rows": rows, "totals": totals,
            "total": round(sum(totals.values()), 2), "hours_per_day": hpd, "capacity": hpd * 5}


@router.put("/timesheet", summary="Set your hours for one item on one day (replaces that day's records; 0 clears)")
def set_cell(project_key: str, body: CellIn, user: User = Depends(current_user),
             db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user, "contributor")
    item = items_svc.get_item(db, project, body.item)
    existing = db.execute(select(WorkRecord).where(WorkRecord.item_id == item.id, WorkRecord.user_id == user.id,
                                                   WorkRecord.day == body.day)).scalars().all()
    before = round(sum(r.hours for r in existing), 2)
    hours = round(body.hours, 2)
    if hours == before:
        return {"item": item.key, "day": body.day.isoformat(), "hours": hours}
    if hours > 0:
        _check_day(db, user, body.day, hours, ignore=[r.id for r in existing])
    comment = next((r.comment for r in existing if r.comment), None)
    for r in existing:
        db.delete(r)
    if hours > 0:
        db.add(WorkRecord(project_id=project.id, item_id=item.id, user_id=user.id, day=body.day, hours=hours,
                          comment=comment))
    db.flush()
    _audit(db, user, project, item, "work.recorded" if hours else "work.deleted",
           f"Timesheet: {hours:g} h on {item.key} ({body.day})",
           {"day": body.day.isoformat(), "hours": hours, "before": before})
    db.commit()
    return {"item": item.key, "day": body.day.isoformat(), "hours": hours}
