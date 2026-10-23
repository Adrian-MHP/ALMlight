"""Connectors to tools outside Ariadne: Enterprise Architect, medini analyze, SysML v2 servers (catalogue includes
Git and ReqIF, which have their own pages)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from almlight.core import secretbox
from almlight.core.db import get_db
from almlight.core.deps import current_user, ui_locale
from almlight.core.errors import ValidationFailed
from almlight.core.i18n import tr
from almlight.core.schemas import form_flag
from almlight.modules.audit import service as audit
from almlight.modules.collab.router import flush_project
from almlight.modules.connectors import ea, medini, pipeline, sysml
from almlight.modules.connectors.base import CATALOGUE
from almlight.modules.identity.models import User
from almlight.modules.integrations.models import IntegrationSetting
from almlight.modules.io.router import ExportFilter
from almlight.modules.items import service as items_svc
from almlight.modules.items.models import Item
from almlight.modules.projects.access import get_project
from almlight.modules.projects.models import Project

router = APIRouter(tags=["connectors"])
DRY_RUN = "true (default): preview only; false: apply"
MAX_FILE = 100 * 1024 * 1024


def _read(file: UploadFile) -> bytes:
    content = file.file.read(MAX_FILE + 1)
    if len(content) > MAX_FILE:
        raise ValidationFailed("File too large")
    if not content:
        raise ValidationFailed("The file is empty")
    return content


def _mapping(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        raise ValidationFailed("mapping must be JSON") from None
    if not isinstance(value, dict):
        raise ValidationFailed("mapping must be a JSON object")
    return value


def _localised(result: dict[str, Any], locale: str) -> dict[str, Any]:
    result["warnings"] = [tr(w, locale) for w in result["warnings"]]
    result["errors"] = [tr(e, locale) for e in result["errors"]]
    return result


def _download(content: bytes, name: str, media: str) -> Response:
    return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


def _items(db: Session, project: Project, user: User, f: ExportFilter, types: set[str]) -> list[Item]:
    query = f.query(project, user)
    if query is None:
        rows = db.execute(select(Item).where(Item.project_id == project.id, Item.type_key.in_(types),
                                             Item.deleted_at.is_(None)).order_by(Item.type_key, Item.seq)).scalars()
        return list(rows)
    items, _ = items_svc.query_items(db, project, query, max_limit=5000)
    return [i for i in items if i.type_key in types]


@router.get("/connectors", summary="Available connectors")
def catalogue(_: User = Depends(current_user)) -> list[dict[str, Any]]:
    return CATALOGUE


# --- Enterprise Architect -------------------------------------------------------------------------------------


@router.post("/projects/{project_key}/connectors/ea/import",
             summary="Import an Enterprise Architect model (.qea/.qeax or XMI 2.1); dry run by default")
def ea_import(project_key: str, file: UploadFile = File(...),
              dry_run_raw: str | None = Form(default=None, alias="dry_run", description=DRY_RUN),
              mapping: str | None = Form(default=None, description='{"types": {}, "relations": {}, "document": key}'),
              user: User = Depends(current_user), db: Session = Depends(get_db),
                locale: str = Depends(ui_locale)) -> dict[str, Any]:
    dry_run = form_flag(dry_run_raw, True)
    project = get_project(db, project_key, user, "contributor")
    model = ea.parse(file.filename or "model.xmi", _read(file))
    if not dry_run:
        flush_project(project.id)
    result = pipeline.run_import(db, project, user, model, ea.suggestion(project, model), mapping=_mapping(mapping),
                                 dry_run=dry_run, own_id=ea.own_id)
    db.commit()
    return _localised(result, locale)


@router.get("/projects/{project_key}/connectors/ea/export.xmi", summary="Export items as Enterprise Architect XMI 2.1")
def ea_export(project_key: str, f: ExportFilter = Depends(), user: User = Depends(current_user),
              db: Session = Depends(get_db)) -> Response:
    project = get_project(db, project_key, user)
    items = _items(db, project, user, f, set(ea.TYPE_OUT))
    return _download(ea.export_xmi(db, project, items), f"{project.key}-ea.xmi", "application/xml")


@router.post("/projects/{project_key}/connectors/ea/writeback",
             summary="Write items into a copy of an EA model (.qea): update known elements, add new ones")
def ea_writeback(project_key: str, file: UploadFile = File(...), package: str = Form(...),
                 ql: str | None = Form(default=None), user: User = Depends(current_user),
                 db: Session = Depends(get_db)) -> Response:
    project = get_project(db, project_key, user, "contributor")
    f = ExportFilter(type=None, q=None, state=None, suspect=None, link_type=None, link_dir="out", link_exists=None,
                     planned_in=None, cond=None, ql=ql or None, sort="key")
    items = _items(db, project, user, f, set(ea.TYPE_OUT))
    data, counts = ea.writeback_qea(db, project, _read(file), items, package)
    audit.record(db, actor=user, action="connector.exported", entity_type="project", entity_id=project.id,
                 project_id=project.id, summary=f"Enterprise Architect write-back into {file.filename}: "
                 f"{counts['created']} created, {counts['updated']} updated, {counts['connectors']} connectors",
                 details=counts)
    db.commit()
    name = (file.filename or "model.qea").rsplit(".", 1)[0] + "-ariadne.qea"
    resp = _download(data, name, "application/octet-stream")
    resp.headers["X-Ariadne-Counts"] = json.dumps(counts)
    return resp


# --- medini analyze -------------------------------------------------------------------------------------------


@router.post("/projects/{project_key}/connectors/medini/import",
             summary="Import a medini analyze HARA or FMEA table (.xlsx/.csv); dry run by default")
def medini_import(project_key: str, file: UploadFile = File(...), kind: str = Form(..., pattern="^(hara|fmea)$"),
                  dry_run_raw: str | None = Form(default=None, alias="dry_run", description=DRY_RUN),
                  mapping: str | None = Form(default=None),
                  user: User = Depends(current_user), db: Session = Depends(get_db),
                locale: str = Depends(ui_locale)) -> dict[str, Any]:
    dry_run = form_flag(dry_run_raw, True)
    project = get_project(db, project_key, user, "contributor")
    model = medini.parse(kind, file.filename or f"{kind}.xlsx", _read(file))
    if not dry_run:
        flush_project(project.id)
    result = pipeline.run_import(db, project, user, model, medini.suggestion(project, model),
                                 mapping=_mapping(mapping), dry_run=dry_run)
    db.commit()
    return _localised(result, locale)


@router.get("/projects/{project_key}/connectors/medini/{kind}.xlsx", summary="HARA or FMEA as Excel for medini analyze")
def medini_export(project_key: str, kind: str, user: User = Depends(current_user),
                  db: Session = Depends(get_db)) -> Response:
    project = get_project(db, project_key, user)
    if kind not in ("hara", "fmea"):
        raise ValidationFailed("Choose hara or fmea")
    data = medini.export_hara(db, project) if kind == "hara" else medini.export_fmea(db, project)
    return _download(data, f"{project.key}-{kind}.xlsx",
                     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# --- SysML v2 -------------------------------------------------------------------------------------------------


class SysmlSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_url: str = Field(max_length=500)
    project_id: str | None = Field(default=None, max_length=100)
    token: str | None = Field(default=None, max_length=1000)
    clear_token: bool = False


class SysmlImportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mapping: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = True
    refresh: bool = False


def _sysml_setting(db: Session, project: Project) -> IntegrationSetting | None:
    return db.execute(select(IntegrationSetting).where(IntegrationSetting.project_id == project.id,
                                                       IntegrationSetting.system == "sysml")).scalar_one_or_none()


def _sysml_out(s: IntegrationSetting | None) -> dict[str, Any]:
    if s is None:
        return {"configured": False}
    return {"configured": True, "base_url": s.settings.get("base_url"), "project_id": s.settings.get("project_id"),
            "project_name": s.settings.get("project_name"), "has_token": bool(s.secret)}


@router.get("/projects/{project_key}/connectors/sysml/settings", summary="SysML v2 server of the project")
def sysml_settings(project_key: str, user: User = Depends(current_user),
                   db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    return _sysml_out(_sysml_setting(db, project))


@router.put("/projects/{project_key}/connectors/sysml/settings", summary="Configure the SysML v2 server (manager)")
def sysml_configure(project_key: str, body: SysmlSettingsIn, user: User = Depends(current_user),
                    db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user, "manager")
    base = sysml.check_base(body.base_url)
    s = _sysml_setting(db, project)
    token = body.token or (secretbox.unseal(s.secret) if s and s.secret and not body.clear_token else None)
    names = {p["id"]: p["name"] for p in sysml.list_projects(base, token)}
    if body.project_id and body.project_id not in names:
        raise ValidationFailed("The SysML v2 project does not exist on the server")
    settings = {"base_url": base, "project_id": body.project_id, "project_name": names.get(body.project_id or "")}
    if s is None:
        s = IntegrationSetting(project_id=project.id, system="sysml", enabled=True, secret="", settings=settings)
        db.add(s)
    s.settings = settings
    if body.token:
        s.secret = secretbox.seal(body.token)
    elif body.clear_token:
        s.secret = ""
    audit.record(db, actor=user, action="connector.configured", entity_type="project", entity_id=project.id,
                 project_id=project.id, summary=f"Configured SysML v2 server {base} for {project.key}",
                 details={"base_url": base, "project": settings["project_name"]})
    db.commit()
    return {**_sysml_out(s), "projects": [{"id": k, "name": v} for k, v in names.items()]}


@router.post("/projects/{project_key}/connectors/sysml/import",
             summary="Import from the SysML v2 server; dry run by default")
def sysml_import(project_key: str, body: SysmlImportIn, user: User = Depends(current_user),
                 db: Session = Depends(get_db),
                locale: str = Depends(ui_locale)) -> dict[str, Any]:
    project = get_project(db, project_key, user, "contributor")
    s = _sysml_setting(db, project)
    if s is None or not s.settings.get("project_id"):
        raise ValidationFailed("Configure the SysML v2 server and project first")
    base, pid = s.settings["base_url"], s.settings["project_id"]
    elements, name, _ = sysml.fetch(base, pid, secretbox.unseal(s.secret) if s.secret else None, body.refresh)
    model = sysml.to_model(elements, base, pid, name)
    if not body.dry_run:
        flush_project(project.id)
    result = pipeline.run_import(db, project, user, model, sysml.suggestion(project, model), mapping=body.mapping,
                                 dry_run=body.dry_run)
    db.commit()
    return _localised(result, locale)
