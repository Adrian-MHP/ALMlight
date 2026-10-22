from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from almlight.core.db import get_db
from almlight.core.deps import admin_user, current_user
from almlight.core.errors import ValidationFailed
from almlight.modules.identity.models import User
from almlight.modules.io import archive, reqif, reqif_import, tabular
from almlight.modules.io.document_export import render_docx, render_pdf
from almlight.modules.io.document_snapshot import baseline_snapshot, live_snapshot
from almlight.modules.items import service as items_svc
from almlight.modules.projects.access import get_project

router = APIRouter(tags=["import-export"])
MAX_IMPORT = 50 * 1024 * 1024


def _download(content: bytes, filename: str, media_type: str) -> Response:
    return Response(content, media_type=media_type,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/projects/{project_key}/export.csv")
def export_csv(project_key: str, type: list[str] | None = Query(default=None), user: User = Depends(current_user),
               db: Session = Depends(get_db)) -> Response:
    project = get_project(db, project_key, user)
    return _download(tabular.export_csv(db, project, type), f"{project.key}-{date.today()}.csv", "text/csv")


@router.get("/projects/{project_key}/export.xlsx")
def export_xlsx(project_key: str, type: list[str] | None = Query(default=None), user: User = Depends(current_user),
                db: Session = Depends(get_db)) -> Response:
    project = get_project(db, project_key, user)
    return _download(tabular.export_xlsx(db, project, type), f"{project.key}-{date.today()}.xlsx",
                     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.post("/projects/{project_key}/import", summary="Import items from CSV or Excel (dry run by default)")
def import_items(project_key: str, file: UploadFile = File(...), dry_run: bool = Form(default=True),
                 default_type: str | None = Form(default=None), user: User = Depends(current_user),
                 db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user, "contributor")
    content = file.file.read(MAX_IMPORT + 1)
    if len(content) > MAX_IMPORT:
        raise ValidationFailed("File too large")
    result = tabular.import_table(db, project, user, file.filename or "import.csv", content,
                                  default_type=default_type, dry_run=dry_run)
    db.commit()
    return result


@router.get("/projects/{project_key}/archive", summary="Full project archive (JSON) incl. history")
def export_archive(project_key: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    project = get_project(db, project_key, user, "manager")
    data = archive.export_archive(db, project)
    return _download(json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8"),
                     f"{project.key}-archive-{date.today()}.json", "application/json")


@router.post("/projects/import-archive", summary="Create a project from an archive")
def import_archive(file: UploadFile = File(...), key: str = Form(...), name: str | None = Form(default=None),
                   user: User = Depends(admin_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    content = file.file.read(MAX_IMPORT * 4 + 1)
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        raise ValidationFailed("The archive is not valid JSON") from None
    project = archive.import_archive(db, user, data, new_key=key, new_name=name)
    db.commit()
    return {"key": project.key, "name": project.name}


@router.get("/projects/{project_key}/reqif", summary="ReqIF export of all requirements")
def project_reqif(project_key: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    project = get_project(db, project_key, user)
    return _download(reqif.export_reqif(db, project), f"{project.key}-requirements.reqif", "application/xml")


@router.get("/projects/{project_key}/items/{item_key}/reqif", summary="ReqIF export of a specification")
def item_reqif(project_key: str, item_key: str, user: User = Depends(current_user),
               db: Session = Depends(get_db)) -> Response:
    project = get_project(db, project_key, user)
    root = items_svc.get_item(db, project, item_key)
    return _download(reqif.export_reqif(db, project, root), f"{root.key}.reqif", "application/xml")


@router.post("/projects/{project_key}/import-reqif", summary="Import a ReqIF file (.reqif/.reqifz), dry run by default")
def import_reqif(project_key: str, file: UploadFile = File(...), dry_run: bool = Form(default=True),
                 mapping: str | None = Form(default=None, description='{"types": {...}, "relations": {...}}'),
                 default_type: str | None = Form(default=None), user: User = Depends(current_user),
                 db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user, "contributor")
    content = file.file.read(MAX_IMPORT + 1)
    if len(content) > MAX_IMPORT:
        raise ValidationFailed("File too large")
    try:
        maps = json.loads(mapping) if mapping else {}
    except json.JSONDecodeError:
        raise ValidationFailed("mapping must be JSON") from None
    result = reqif_import.import_reqif(db, project, user, file.filename or "import.reqif", content, dry_run=dry_run,
                                       type_mapping=maps.get("types"), relation_mapping=maps.get("relations"),
                                       default_type=default_type)
    db.commit()
    return result


def _snapshot(db: Session, project, item_key: str, baseline: uuid.UUID | None):
    root = items_svc.get_item(db, project, item_key)
    return baseline_snapshot(db, project, root, baseline) if baseline else live_snapshot(db, project, root)


@router.get("/projects/{project_key}/items/{item_key}/export.docx", summary="Word export of a document")
def export_docx(project_key: str, item_key: str, baseline: uuid.UUID | None = None, fields: bool = True,
                links: bool = True, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    project = get_project(db, project_key, user)
    snap = _snapshot(db, project, item_key, baseline)
    return _download(render_docx(snap, include_fields=fields, include_links=links),
                     f"{snap.root.key}-{snap.root.version}.docx",
                     "application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@router.get("/projects/{project_key}/items/{item_key}/export.pdf", summary="PDF export of a document")
def export_pdf(project_key: str, item_key: str, baseline: uuid.UUID | None = None, fields: bool = True,
               links: bool = True, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    project = get_project(db, project_key, user)
    snap = _snapshot(db, project, item_key, baseline)
    return _download(render_pdf(snap, include_fields=fields, include_links=links),
                     f"{snap.root.key}-{snap.root.version}.pdf", "application/pdf")
