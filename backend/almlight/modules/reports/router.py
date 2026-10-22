from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from almlight.core.db import get_db
from almlight.core.deps import current_user
from almlight.core.errors import NotFound
from almlight.core.schemas import Ok, UserDirectory
from almlight.modules.identity.models import User
from almlight.modules.projects.access import get_project
from almlight.modules.reports import kpis, service
from almlight.modules.reports.models import Report
from almlight.modules.reports.schemas import ReportIn, Widget
from almlight.modules.reports.templates import TEMPLATES

router = APIRouter(prefix="/projects/{project_key}", tags=["reports"])


def _out(r: Report, users: UserDirectory, user: User, with_widgets: bool = True) -> dict[str, Any]:
    out = {"id": str(r.id), "title": r.title, "description": r.description, "visibility": r.visibility,
           "template": r.template_key, "owner": users.ref(r.owner_id), "mine": r.owner_id == user.id,
           "created_at": r.created_at.isoformat(), "updated_at": r.updated_at.isoformat(),
           "widget_count": len(r.widgets)}
    if with_widgets:
        out["widgets"] = r.widgets
    return out


@router.get("/report-templates")
def templates(project_key: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    get_project(db, project_key, user)
    return [{"key": k, "title": t["title"], "description": t["description"], "widgets": len(t["widgets"])}
            for k, t in TEMPLATES.items()]


@router.get("/reports")
def list_reports(project_key: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    project = get_project(db, project_key, user)
    users = UserDirectory(db)
    return [_out(r, users, user, with_widgets=False) for r in service.visible_reports(db, project, user)]


@router.post("/reports", status_code=201)
def create_report(project_key: str, body: ReportIn, user: User = Depends(current_user),
                  db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user, "contributor")
    report = service.create_report(db, project, user, body)
    db.commit()
    return _out(report, UserDirectory(db), user)


@router.get("/reports/{report_id}")
def get_report(project_key: str, report_id: uuid.UUID, user: User = Depends(current_user),
               db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    return _out(service.get_report(db, project, user, report_id), UserDirectory(db), user)


@router.put("/reports/{report_id}")
def update_report(project_key: str, report_id: uuid.UUID, body: ReportIn, user: User = Depends(current_user),
                  db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user, "contributor")
    report = service.update_report(db, project, user, service.get_report(db, project, user, report_id), body)
    db.commit()
    return _out(report, UserDirectory(db), user)


@router.delete("/reports/{report_id}", response_model=Ok)
def delete_report(project_key: str, report_id: uuid.UUID, user: User = Depends(current_user),
                  db: Session = Depends(get_db)) -> Ok:
    project = get_project(db, project_key, user, "contributor")
    service.delete_report(db, project, user, service.get_report(db, project, user, report_id))
    db.commit()
    return Ok()


@router.get("/reports/{report_id}/data", summary="Evaluate all widgets of a report")
def report_data(project_key: str, report_id: uuid.UUID, user: User = Depends(current_user),
                db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    report = service.get_report(db, project, user, report_id)
    return {raw["id"]: service.evaluate(db, project, Widget.model_validate(raw)) for raw in report.widgets}


@router.post("/reports/preview-widget", summary="Evaluate a widget definition (report editor preview)")
def preview_widget(project_key: str, widget: Widget, user: User = Depends(current_user),
                   db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    return service.evaluate(db, project, widget)


@router.get("/reports/{report_id}/export.xlsx")
def export_report(project_key: str, report_id: uuid.UUID, user: User = Depends(current_user),
                  db: Session = Depends(get_db)) -> Response:
    project = get_project(db, project_key, user)
    report = service.get_report(db, project, user, report_id)
    safe = "".join(ch if ch.isalnum() else "-" for ch in report.title)[:40]
    return Response(service.export_xlsx(db, project, report),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{project.key}-{safe}-{date.today()}.xlsx"'})


@router.get("/kpis/{name}", summary="KPI data for BI tools: reuse | change-lead-time | retest-effort | variant-ratio")
def kpi(project_key: str, name: str, variant: str | None = None, interval: str = Query(default="month"),
        user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    if name == "reuse":
        return kpis.reuse(db, project)
    if name == "change-lead-time":
        return kpis.change_lead_time(db, project, None, interval if interval in ("week", "month") else "month")
    if name == "retest-effort":
        return kpis.retest_effort(db, project, variant)
    if name == "variant-ratio":
        return kpis.variant_ratio(db, project)
    raise NotFound(f"Unknown KPI '{name}'")
