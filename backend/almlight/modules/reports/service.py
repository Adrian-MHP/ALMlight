"""Report CRUD and widget evaluation.

A widget is evaluated independently; an error in one widget (e.g. a type that does not exist in this project's
information model) is returned as that widget's error and does not break the report.
"""

from __future__ import annotations

import io
import uuid
from collections import defaultdict
from datetime import timedelta
from typing import Any

from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from almlight.core.db import utcnow
from almlight.core.errors import DomainError, Forbidden, NotFound, ValidationFailed
from almlight.modules.audit import service as audit
from almlight.modules.identity.models import User
from almlight.modules.items import service as items_svc
from almlight.modules.items.models import Item, ItemVersion
from almlight.modules.links.models import Link
from almlight.modules.projects.access import has_role
from almlight.modules.projects.models import Project
from almlight.modules.reports import kpis
from almlight.modules.reports.models import Report
from almlight.modules.reports.schemas import ItemFilter, ReportIn, Widget
from almlight.modules.reports.templates import TEMPLATES
from almlight.modules.variants import expressions
from almlight.modules.variants import service as variants_svc
from almlight.modules.verification import service as verification
from almlight.modules.workflow.models import WorkflowEvent

MAX_ITEMS = 50_000


# --- CRUD --------------------------------------------------------------------------------------


def visible_reports(db: Session, project: Project, user: User) -> list[Report]:
    rows = db.execute(select(Report).where(Report.project_id == project.id).order_by(Report.title)).scalars().all()
    return [r for r in rows if r.visibility == "project" or r.owner_id == user.id]


def get_report(db: Session, project: Project, user: User, report_id: uuid.UUID) -> Report:
    r = db.get(Report, report_id)
    if r is None or r.project_id != project.id or (r.visibility == "private" and r.owner_id != user.id):
        raise NotFound("Report not found")
    return r


def _check_widgets(widgets: list[Widget]) -> list[dict[str, Any]]:
    ids = [w.id for w in widgets]
    if len(ids) != len(set(ids)):
        raise ValidationFailed("Widget ids must be unique")
    return [w.model_dump(mode="json") for w in widgets]


def create_report(db: Session, project: Project, actor: User, body: ReportIn) -> Report:
    widgets = body.widgets
    if body.template:
        tpl = TEMPLATES.get(body.template)
        if tpl is None:
            raise ValidationFailed(f"Unknown report template '{body.template}'", {"available": sorted(TEMPLATES)})
        widgets = widgets or [Widget.model_validate(w) for w in tpl["widgets"]]
    report = Report(project_id=project.id, title=body.title.strip(), description=body.description,
                    visibility=body.visibility, widgets=_check_widgets(widgets), template_key=body.template,
                    owner_id=actor.id)
    db.add(report)
    db.flush()
    audit.record(db, actor=actor, action="report.created", entity_type="report", entity_id=report.id,
                 project_id=project.id, summary=f"Created report '{report.title}'")
    return report


def _ensure_can_edit(db: Session, project: Project, actor: User, report: Report) -> None:
    if report.owner_id != actor.id and not has_role(db, project, actor, "manager"):
        raise Forbidden("Only the owner or a project manager can change this report")


def update_report(db: Session, project: Project, actor: User, report: Report, body: ReportIn) -> Report:
    _ensure_can_edit(db, project, actor, report)
    report.title = body.title.strip()
    report.description = body.description
    report.visibility = body.visibility
    report.widgets = _check_widgets(body.widgets)
    report.updated_at = utcnow()
    audit.record(db, actor=actor, action="report.updated", entity_type="report", entity_id=report.id,
                 project_id=project.id, summary=f"Updated report '{report.title}'")
    return report


def delete_report(db: Session, project: Project, actor: User, report: Report) -> None:
    _ensure_can_edit(db, project, actor, report)
    db.delete(report)
    audit.record(db, actor=actor, action="report.deleted", entity_type="report", entity_id=report.id,
                 project_id=project.id, summary=f"Deleted report '{report.title}'")


# --- item selection ------------------------------------------------------------------------------


def select_items(db: Session, project: Project, f: ItemFilter) -> list[Item]:
    for t in f.types:
        items_svc.item_type(project, t)
    stmt = items_svc._filtered(project, items_svc.ItemQuery(
        q=f.q, types=f.types or None, states=f.states or None, owner_id=f.owner, suspect=f.suspect,
        field_filters=f.fields or None))
    items = list(db.execute(stmt.order_by(Item.type_key, Item.seq).limit(MAX_ITEMS)).scalars())
    if f.variant:
        variant = items_svc.get_item(db, project, f.variant)
        selection = variants_svc.selection_of(variant)
        items = [i for i in items if _applies(i.applicability, selection)]
    return items


def _applies(expr: str | None, selection: set[str]) -> bool:
    try:
        return expressions.applies(expr, selection)
    except Exception:  # noqa: BLE001
        return False


def _merge(a: ItemFilter, b: ItemFilter) -> ItemFilter:
    return ItemFilter(
        types=b.types or a.types, states=b.states or a.states, q=b.q or a.q, fields={**a.fields, **b.fields},
        owner=b.owner or a.owner, suspect=b.suspect if b.suspect is not None else a.suspect,
        variant=b.variant or a.variant,
    )


class _Labels:
    def __init__(self, db: Session, project: Project):
        self.db, self.model = db, project.model
        self._users: dict[uuid.UUID, str] | None = None

    def group_value(self, item: Item, dim: str) -> tuple[str, str]:
        """(key, label) of an item along a dimension: state | type | owner | category | field:<key>."""
        if dim == "state":
            wf = self.model.workflow_for(item.type_key)
            st = wf.state(item.state) if wf else None
            return (item.state or "-", st.label if st else (item.state or "no lifecycle"))
        if dim == "type":
            t = self.model.item_type(item.type_key)
            return (item.type_key, t.label if t else item.type_key)
        if dim == "category":
            t = self.model.item_type(item.type_key)
            return (t.category if t else "other", (t.category if t else "other").capitalize())
        if dim == "owner":
            if self._users is None:
                self._users = {u.id: u.display_name for u in self.db.execute(select(User)).scalars()}
            return (str(item.owner_id), self._users.get(item.owner_id, "unassigned"))
        if dim.startswith("field:"):
            key = dim[6:]
            v = item.fields.get(key)
            if v in (None, "", []):
                return ("-", "not set")
            if isinstance(v, list):
                v = ", ".join(map(str, v))
            t = self.model.item_type(item.type_key)
            fdef = t.field(key) if t else None
            if fdef and fdef.type == "enum":
                return (str(v), next((o.label for o in fdef.options if o.key == v), str(v)))
            if isinstance(v, bool):
                return (str(v).lower(), "Yes" if v else "No")
            return (str(v), str(v))
        raise ValidationFailed(f"Unknown grouping '{dim}' (use state, type, category, owner or field:<key>)")


# --- evaluation ------------------------------------------------------------------------------------


def evaluate(db: Session, project: Project, w: Widget) -> dict[str, Any]:
    try:
        return {"ok": True, **_evaluate(db, project, w)}
    except DomainError as exc:
        return {"ok": False, "error": exc.message}


def _evaluate(db: Session, project: Project, w: Widget) -> dict[str, Any]:
    if w.type == "markdown":
        return {"text": w.text}
    if w.type == "kpi":
        base = select_items(db, project, w.filter)
        if w.metric == "count":
            value = len(base)
            return {"value": value, "unit": "", "target": w.target,
                    "status": None if w.target is None else ("good" if value >= w.target else "bad")}
        num_filter = _merge(w.filter, w.percent_of or ItemFilter())
        num = len(select_items(db, project, num_filter))
        pct = round(100 * num / len(base)) if base else 0
        return {"value": pct, "unit": "%", "numerator": num, "denominator": len(base), "target": w.target,
                "status": None if w.target is None else ("good" if pct >= w.target else "bad")}
    if w.type == "chart":
        labels = _Labels(db, project)
        items = select_items(db, project, w.filter)
        groups: dict[str, dict[str, Any]] = {}
        stacks: dict[str, str] = {}
        for it in items:
            gk, gl = labels.group_value(it, w.group_by)
            g = groups.setdefault(gk, {"key": gk, "label": gl, "total": 0, "series": defaultdict(int)})
            g["total"] += 1
            if w.stack_by:
                sk, sl = labels.group_value(it, w.stack_by)
                stacks[sk] = sl
                g["series"][sk] += 1
        data = sorted(groups.values(), key=lambda g: -g["total"])
        return {"group_by": w.group_by, "stack_by": w.stack_by, "chart": w.chart, "total": len(items),
                "groups": [{"key": g["key"], "label": g["label"], "total": g["total"], "series": dict(g["series"])}
                           for g in data],
                "stacks": [{"key": k, "label": v} for k, v in stacks.items()]}
    if w.type == "table":
        items = select_items(db, project, w.filter)
        order = {"key": lambda i: (i.type_key, i.seq), "title": lambda i: i.title.lower(),
                 "-updated": lambda i: -i.updated_at.timestamp(), "updated": lambda i: i.updated_at.timestamp(),
                 "state": lambda i: (i.state or "", i.seq)}
        items.sort(key=order.get(w.sort, order["key"]))
        labels = _Labels(db, project)
        rows = []
        for it in items[: w.limit]:
            row: dict[str, Any] = {}
            for col in w.columns:
                if col == "key":
                    row[col] = it.key
                elif col == "title":
                    row[col] = it.title
                elif col == "type":
                    row[col] = labels.group_value(it, "type")[1]
                elif col == "state":
                    row[col] = labels.group_value(it, "state")[1]
                elif col == "version":
                    row[col] = it.version_label
                elif col == "owner":
                    row[col] = labels.group_value(it, "owner")[1]
                elif col == "updated":
                    row[col] = it.updated_at.isoformat()
                elif col == "applicability":
                    row[col] = it.applicability
                elif col.startswith("field:"):
                    row[col] = labels.group_value(it, col)[1]
                else:
                    raise ValidationFailed(f"Unknown column '{col}'")
            rows.append(row)
        return {"columns": w.columns, "rows": rows, "total": len(items)}
    if w.type == "trend":
        return _trend(db, project, w)
    if w.type == "coverage":
        type_key = w.coverage_type or next(
            (t.key for t in project.model.item_types if t.category == "requirement"), None)
        if not type_key:
            raise ValidationFailed("No requirement type to compute coverage for")
        items_svc.item_type(project, type_key)
        cov = verification.coverage(db, project, type_key, w.variant)
        gaps = [r for r in cov["rows"] if r["verification"] != "passed"][:20]
        return {**{k: v for k, v in cov.items() if k != "rows"}, "label": project.model.item_type(type_key).label,
                "gaps": gaps}
    if w.type == "matrix":
        if not (w.rows and w.cols):
            raise ValidationFailed("Choose row and column types for the matrix")
        return _matrix(db, project, w.rows, w.cols)
    if w.type == "maturity":
        rows = verification.maturity(db, project, None, w.variant)
        summary = {k: sum(1 for r in rows if r[k] == "done") for k in ("specified", "realised", "verified",
                                                                         "validated")}
        return {"total": len(rows), "done": summary, "rows": rows[:100]}
    if w.type == "reuse":
        return kpis.reuse(db, project)
    if w.type == "change_lead_time":
        return kpis.change_lead_time(db, project, w.change_types or None, w.interval, w.periods)
    if w.type == "retest_effort":
        return kpis.retest_effort(db, project, w.variant)
    if w.type == "variant_ratio":
        return kpis.variant_ratio(db, project)
    raise ValidationFailed(f"Unknown widget type '{w.type}'")


def _period_starts(interval: str, periods: int) -> list:
    now = utcnow()
    if interval == "month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        out = []
        y, m = start.year, start.month
        for _ in range(periods):
            out.append(start.replace(year=y, month=m))
            m -= 1
            if m == 0:
                y, m = y - 1, 12
        return list(reversed(out))
    start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return [start - timedelta(weeks=i) for i in reversed(range(periods))]


def _trend(db: Session, project: Project, w: Widget) -> dict[str, Any]:
    items = select_items(db, project, w.filter)
    ids = [i.id for i in items]
    starts = _period_starts(w.interval, w.periods)
    trunc = func.date_trunc(w.interval, func.timezone("UTC", Item.created_at))
    series: dict[str, dict[str, int]] = {}
    if not ids:
        return {"periods": [s.date().isoformat() for s in starts], "series": {s: [0] * len(starts) for s in w.series}}

    def bucket(rows: list[tuple[Any, int]]) -> dict[str, int]:
        return {r[0].date().isoformat(): r[1] for r in rows if r[0] is not None}

    if "created" in w.series:
        series["created"] = bucket(db.execute(
            select(trunc, func.count()).where(Item.id.in_(ids)).group_by(trunc)).all())
    if "released" in w.series:
        released_states = {(t.key, s.key) for t in project.model.item_types
                           for wf in [project.model.workflow(t.workflow)] if wf for s in wf.states if s.released}
        rt = func.date_trunc(w.interval, func.timezone("UTC", WorkflowEvent.created_at))
        rows = db.execute(select(rt, WorkflowEvent.to_state, Item.type_key, func.count())
                          .join(Item, Item.id == WorkflowEvent.item_id)
                          .where(WorkflowEvent.item_id.in_(ids)).group_by(rt, WorkflowEvent.to_state, Item.type_key)
                          ).all()
        agg: dict[str, int] = defaultdict(int)
        for period, state, type_key, n in rows:
            if (type_key, state) in released_states and period is not None:
                agg[period.date().isoformat()] += n
        series["released"] = dict(agg)
    if "changed" in w.series:
        vt = func.date_trunc(w.interval, func.timezone("UTC", ItemVersion.created_at))
        series["changed"] = bucket(db.execute(
            select(vt, func.count()).where(ItemVersion.item_id.in_(ids), ItemVersion.version_no > 1)
            .group_by(vt)).all())
    labels = [s.date().isoformat() for s in starts]
    out: dict[str, list[int]] = {}
    for name, counts in series.items():
        values = [counts.get(lbl, 0) for lbl in labels]
        if w.cumulative:
            before = sum(v for k, v in counts.items() if k < labels[0])
            acc = before
            values = [acc := acc + v for v in values]
        out[name] = values
    return {"periods": labels, "series": out, "interval": w.interval, "cumulative": w.cumulative}


def _matrix(db: Session, project: Project, rows_type: str, cols_type: str) -> dict[str, Any]:
    for t in (rows_type, cols_type):
        items_svc.item_type(project, t)
    row_items = db.execute(select(Item).where(Item.project_id == project.id, Item.type_key == rows_type,
                                              Item.deleted_at.is_(None)).order_by(Item.seq)).scalars().all()
    col_items = db.execute(select(Item).where(Item.project_id == project.id, Item.type_key == cols_type,
                                              Item.deleted_at.is_(None)).order_by(Item.seq)).scalars().all()
    rid, cid = {i.id for i in row_items}, {i.id for i in col_items}
    cells = []
    if rid and cid:
        between = ((Link.source_id.in_(rid) & Link.target_id.in_(cid))
                   | (Link.source_id.in_(cid) & Link.target_id.in_(rid)))
        for link in db.execute(select(Link).where(Link.deleted_at.is_(None), between)).scalars():
            r, c = (link.source_id, link.target_id) if link.source_id in rid else (link.target_id, link.source_id)
            cells.append({"row": str(r), "col": str(c), "type": link.type_key, "suspect": link.suspect})
    covered = {c["row"] for c in cells}
    return {"rows": [{"id": str(i.id), "key": i.key, "title": i.title} for i in row_items],
            "cols": [{"id": str(i.id), "key": i.key, "title": i.title} for i in col_items], "cells": cells,
            "rows_covered_pct": round(100 * len(covered) / len(row_items)) if row_items else 0}


# --- export ------------------------------------------------------------------------------------------


def export_xlsx(db: Session, project: Project, report: Report) -> bytes:
    wb = Workbook()
    summary = wb.active
    summary.title = "Report"
    summary.append([report.title])
    summary.append([f"Project {project.key} — generated {utcnow():%Y-%m-%d %H:%M} UTC"])
    summary.append([])
    used_titles: set[str] = {"Report"}
    for raw in report.widgets:
        w = Widget.model_validate(raw)
        data = evaluate(db, project, w)
        title = (w.title or w.type)[:28]
        name, n = title, 2
        while name in used_titles:
            name, n = f"{title[:25]} {n}", n + 1
        used_titles.add(name)
        if not data.get("ok"):
            summary.append([w.title or w.type, "error", data.get("error")])
            continue
        if w.type == "kpi":
            summary.append([w.title or "KPI", data["value"], data.get("unit", "")])
            continue
        if w.type == "markdown":
            continue
        ws = wb.create_sheet(_sheet_name(name))
        for row in _rows_for_sheet(w, data):
            ws.append([_cell(v) for v in row])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _sheet_name(name: str) -> str:
    return "".join(ch for ch in name if ch not in "[]:*?/\\") or "Sheet"


def _cell(v: Any) -> Any:
    if isinstance(v, (list, dict)):
        return ", ".join(map(str, v)) if isinstance(v, list) else str(v)
    return v


def _rows_for_sheet(w: Widget, d: dict[str, Any]) -> list[list[Any]]:
    if w.type == "chart":
        stacks = [s["key"] for s in d["stacks"]]
        out = [[w.group_by, "total", *[s["label"] for s in d["stacks"]]]]
        out += [[g["label"], g["total"], *[g["series"].get(s, 0) for s in stacks]] for g in d["groups"]]
        return out
    if w.type == "table":
        return [d["columns"], *[[r.get(c) for c in d["columns"]] for r in d["rows"]]]
    if w.type == "trend":
        names = list(d["series"])
        return [["period", *names], *[[p, *[d["series"][n][i] for n in names]] for i, p in enumerate(d["periods"])]]
    if w.type == "matrix":
        cols = d["cols"]
        cells = {(c["row"], c["col"]) for c in d["cells"]}
        return [["", *[c["key"] for c in cols]],
                *[[r["key"], *["x" if (r["id"], c["id"]) in cells else "" for c in cols]] for r in d["rows"]]]
    rows = d.get("rows") or d.get("variants") or d.get("gaps") or []
    if not rows:
        return [[k, _cell(v)] for k, v in d.items() if k != "ok"]
    keys = list(rows[0].keys())
    return [keys, *[[r.get(k) for k in keys] for r in rows]]
