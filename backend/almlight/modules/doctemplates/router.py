"""Word templates per project: upload (managers), list, download, delete and a sample to start from."""

from __future__ import annotations

import io
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from almlight import PRODUCT
from almlight.core.db import get_db
from almlight.core.deps import current_user
from almlight.core.errors import NotFound, ValidationFailed
from almlight.core.schemas import Ok, UserDirectory
from almlight.modules.audit import service as audit
from almlight.modules.doctemplates.models import DocTemplate
from almlight.modules.identity.models import User
from almlight.modules.io import word_template
from almlight.modules.items import storage
from almlight.modules.items.models import Blob
from almlight.modules.projects.access import get_project

router = APIRouter(prefix="/projects/{project_key}/doc-templates", tags=["import-export"])
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _out(t: DocTemplate, users: UserDirectory) -> dict[str, Any]:
    return {"id": str(t.id), "name": t.name, "filename": t.filename, "size": t.size, **t.info,
            "created_by": users.ref(t.created_by), "created_at": t.created_at.isoformat()}


def template_bytes(db: Session, project_id: uuid.UUID, template_id: uuid.UUID) -> bytes:
    t = db.get(DocTemplate, template_id)
    if t is None or t.project_id != project_id:
        raise NotFound("Word template not found")
    path = storage.blob_path(t.sha256)
    if not path.exists():
        raise NotFound("Template file missing in the file store")
    return path.read_bytes()


@router.get("", summary="Word templates of the project")
def list_templates(project_key: str, user: User = Depends(current_user),
                   db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    project = get_project(db, project_key, user)
    rows = db.execute(select(DocTemplate).where(DocTemplate.project_id == project.id)
                      .order_by(DocTemplate.name)).scalars().all()
    users = UserDirectory(db)
    return [_out(t, users) for t in rows]


@router.get("/sample.docx", summary="A sample template with every placeholder, to start a corporate template from")
def sample(project_key: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    get_project(db, project_key, user)
    return Response(word_template.sample_template(PRODUCT), media_type=DOCX,
                    headers={"Content-Disposition": f'attachment; filename="{PRODUCT}-template.docx"'})


@router.post("", status_code=201, summary="Upload a Word template (.docx/.dotx; manager)")
def upload(project_key: str, file: UploadFile = File(...), name: str = Form(...), user: User = Depends(current_user),
           db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user, "manager")
    name = name.strip()[:120]
    if not name:
        raise ValidationFailed("Give the template a name")
    raw = file.file.read(word_template.MAX_TEMPLATE + 1)
    try:
        content = word_template.normalize(raw)
        info = word_template.inspect(content)
    except word_template.TemplateError as exc:
        raise ValidationFailed(str(exc)) from None
    sha, size = storage.store(io.BytesIO(content))
    db.execute(pg_insert(Blob).values(sha256=sha, size=size, content_type=DOCX)
               .on_conflict_do_nothing(index_elements=["sha256"]))
    filename = (file.filename or "template.docx").replace("/", "_").replace("\\", "_")[:255]
    t = DocTemplate(project_id=project.id, name=name, filename=filename, sha256=sha, size=size, info=info,
                    created_by=user.id)
    db.add(t)
    db.flush()
    audit.record(db, actor=user, action="doc_template.uploaded", entity_type="doc_template", entity_id=t.id,
                 project_id=project.id, summary=f"Uploaded Word template '{name}'", details={"filename": filename})
    db.commit()
    return _out(t, UserDirectory(db))


@router.get("/{template_id}/download", summary="Download a template")
def download(project_key: str, template_id: uuid.UUID, user: User = Depends(current_user),
             db: Session = Depends(get_db)) -> Response:
    project = get_project(db, project_key, user)
    t = db.get(DocTemplate, template_id)
    content = template_bytes(db, project.id, template_id)
    return Response(content, media_type=DOCX, headers={"Content-Disposition": f'attachment; filename="{t.filename}"'})


@router.delete("/{template_id}", response_model=Ok, summary="Delete a template (manager)")
def delete(project_key: str, template_id: uuid.UUID, user: User = Depends(current_user),
           db: Session = Depends(get_db)) -> Ok:
    project = get_project(db, project_key, user, "manager")
    t = db.get(DocTemplate, template_id)
    if t is None or t.project_id != project.id:
        raise NotFound("Word template not found")
    db.delete(t)
    audit.record(db, actor=user, action="doc_template.deleted", entity_type="doc_template", entity_id=t.id,
                 project_id=project.id, summary=f"Deleted Word template '{t.name}'")
    db.commit()
    return Ok()
