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
from almlight.modules.collab.router import flush_project
from almlight.modules.identity.models import User
from almlight.modules.io import archive, reqif, reqif_import, tabular
from almlight.modules.io.document_export import render_docx, render_pdf
from almlight.modules.items import service as items_svc
from almlight.modules.projects.access import get_project

router = APIRouter(tags=["import-export"])
MAX_IMPORT = 50 * 1024 * 1024


def _download(content: bytes, filename: str, media_type: str) -> Response:
    return Response(content, media_type=media_type,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


class ExportFilter:
    """The item list's filter, so that "Export" delivers exactly the current view (all pages)."""

    def __init__(self, type: list[str] | None = Query(default=None), q: str | None = None,
                 state: list[str] | None = Query(default=None), suspect: bool | None = None,
                 link_type: str | None = None, link_dir: str = Query(default="out", pattern="^(out|in)$"),
                 link_exists: bool | None = None, planned_in: str | None = None,
                 cond: str | None = Query(default=None, description="JSON conditions as in the item list"),
                 ql: str | None = Query(default=None, description="Query language as in the item list"),
                 sort: str = "key") -> None:
        self.types = type
        self.args = dict(q=q, state=state, suspect=suspect, link_type=link_type, link_dir=link_dir,
                         link_exists=link_exists, planned_in=planned_in, cond=cond, ql=ql, sort=sort)

    def query(self, project: Any, user: User) -> items_svc.ItemQuery | None:
        from almlight.modules.items import query as item_query

        a = self.args
        conditions = item_query.parse_conditions(a["cond"])
        q = a["q"]
        if a["ql"]:
            text, more = item_query.parse_query(project, a["ql"])
            q = " ".join(x for x in (q, text) if x) or None
            conditions += more
        if not (q or a["state"] or a["suspect"] or a["link_type"] or a["planned_in"] or conditions):
            return None
        return items_svc.ItemQuery(q=q, types=self.types, states=a["state"], suspect=a["suspect"] or None,
                                   link_type=a["link_type"], link_dir=a["link_dir"], link_exists=a["link_exists"],
                                   planned_in=a["planned_in"], conditions=conditions or None, user_id=user.id,
                                   sort=a["sort"], limit=tabular.MAX_ROWS)


@router.get("/projects/{project_key}/export.csv", summary="Items as CSV (optionally filtered like the item list)")
def export_csv(project_key: str, f: ExportFilter = Depends(), user: User = Depends(current_user),
               db: Session = Depends(get_db)) -> Response:
    project = get_project(db, project_key, user)
    content = tabular.export_csv(db, project, f.types, f.query(project, user))
    return _download(content, f"{project.key}-{date.today()}.csv", "text/csv")


@router.get("/projects/{project_key}/export.xlsx", summary="Items as Excel (optionally filtered like the item list)")
def export_xlsx(project_key: str, f: ExportFilter = Depends(), user: User = Depends(current_user),
                db: Session = Depends(get_db)) -> Response:
    project = get_project(db, project_key, user)
    content = tabular.export_xlsx(db, project, f.types, f.query(project, user))
    return _download(content, f"{project.key}-{date.today()}.xlsx",
                     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.post("/projects/{project_key}/import", summary="Import items from CSV or Excel (dry run by default)")
def import_items(project_key: str, file: UploadFile = File(...), dry_run: bool = Form(default=True),
                 default_type: str | None = Form(default=None), user: User = Depends(current_user),
                 db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user, "contributor")
    content = file.file.read(MAX_IMPORT + 1)
    if len(content) > MAX_IMPORT:
        raise ValidationFailed("File too large")
    if not dry_run:
        flush_project(project.id)
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
def project_reqif(project_key: str, format: str = Query(default="auto", pattern="^(auto|reqif|reqifz)$"),
                  user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    project = get_project(db, project_key, user)
    content, ext, media = reqif.export_package(db, project, None, format)
    return _download(content, f"{project.key}-requirements.{ext}", media)


@router.get("/projects/{project_key}/items/{item_key}/reqif", summary="ReqIF export of a specification "
            "(.reqifz when it contains images)")
def item_reqif(project_key: str, item_key: str, format: str = Query(default="auto", pattern="^(auto|reqif|reqifz)$"),
               user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    project = get_project(db, project_key, user)
    root = items_svc.get_item(db, project, item_key)
    content, ext, media = reqif.export_package(db, project, root, format)
    return _download(content, f"{root.key}.{ext}", media)


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
    if not dry_run:
        flush_project(project.id)
    result = reqif_import.import_reqif(db, project, user, file.filename or "import.reqif", content, dry_run=dry_run,
                                       type_mapping=maps.get("types"), relation_mapping=maps.get("relations"),
                                       default_type=default_type)
    db.commit()
    return result


def _snapshot(db: Session, project, item_key: str, baseline: uuid.UUID | None, at: str | None = None,
              variant: str | None = None, numbering: bool = True):
    from almlight.modules.documents.service import parse_at
    from almlight.modules.io.document_snapshot import build_snapshot

    root = items_svc.get_item(db, project, item_key)
    return build_snapshot(db, project, root, at=parse_at(at), baseline_id=baseline, variant_key=variant,
                          numbering=numbering)


@router.get("/projects/{project_key}/items/{item_key}/export.docx", summary="Word export of a document")
def export_docx(project_key: str, item_key: str, baseline: uuid.UUID | None = None, at: str | None = None,
                variant: str | None = None, fields: bool = True, links: bool = True, numbering: bool = True,
                roundtrip: str | None = Query(default=None, description="edit | comments: prepare for Word round trip"),
                template: uuid.UUID | None = Query(default=None, description="A Word template of the project"),
                user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    project = get_project(db, project_key, user)
    if roundtrip and (roundtrip not in ("edit", "comments") or baseline or at or variant):
        raise ValidationFailed("Round trip export: roundtrip=edit|comments, only for the live, unfiltered document")
    layout = None
    if template is not None:
        from almlight.modules.doctemplates.router import template_bytes

        layout = template_bytes(db, project.id, template)
    snap = _snapshot(db, project, item_key, baseline, at, variant, numbering)
    suffix = f"-review-{roundtrip}" if roundtrip else ""
    return _download(render_docx(snap, include_fields=fields, include_links=links, roundtrip=roundtrip,
                                 template=layout, author=user.display_name),
                     f"{snap.root.key}-{snap.root.version}{suffix}.docx",
                     "application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@router.get("/projects/{project_key}/items/{item_key}/export.pdf", summary="PDF export of a document")
def export_pdf(project_key: str, item_key: str, baseline: uuid.UUID | None = None, at: str | None = None,
               variant: str | None = None, fields: bool = True, links: bool = True, numbering: bool = True,
               user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    project = get_project(db, project_key, user)
    snap = _snapshot(db, project, item_key, baseline, at, variant, numbering)
    return _download(render_pdf(snap, include_fields=fields, include_links=links),
                     f"{snap.root.key}-{snap.root.version}.pdf", "application/pdf")
