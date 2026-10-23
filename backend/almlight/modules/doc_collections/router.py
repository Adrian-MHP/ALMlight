from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from almlight.core.db import get_db
from almlight.core.deps import current_user, ui_locale
from almlight.core.errors import Conflict
from almlight.core.schemas import Ok, UserDirectory
from almlight.modules.audit import service as audit
from almlight.modules.baselines import service as baselines
from almlight.modules.doc_collections import service
from almlight.modules.doc_collections.models import Collection
from almlight.modules.identity.models import User
from almlight.modules.items import service as items_svc
from almlight.modules.projects.access import get_project

router = APIRouter(prefix="/projects/{project_key}/collections", tags=["collections"])


class CollectionIn(BaseModel):
    name: str
    description: str | None = None


class EntryIn(BaseModel):
    document: str
    baseline: uuid.UUID | None = None


class StatusIn(BaseModel):
    status: str


@router.get("")
def list_collections(project_key: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> list:
    project = get_project(db, project_key, user)
    users = UserDirectory(db)
    rows = db.execute(select(Collection).where(Collection.project_id == project.id)
                      .order_by(Collection.created_at.desc())).scalars()
    return [service.out(db, c, users) for c in rows]


@router.post("", status_code=201)
def create_collection(project_key: str, body: CollectionIn, user: User = Depends(current_user),
                      db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user, "reviewer")
    c = service.create(db, project, user, body.name, body.description)
    db.commit()
    return service.out(db, c, UserDirectory(db))


@router.get("/{collection_id}")
def get_collection(project_key: str, collection_id: uuid.UUID, user: User = Depends(current_user),
                   db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    return service.out(db, service.get_collection(db, project, collection_id), UserDirectory(db))


@router.post("/{collection_id}/documents", summary="Add a document at a baseline (new baseline if none given)")
def add_document(project_key: str, collection_id: uuid.UUID, body: EntryIn, user: User = Depends(current_user),
                 db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user, "reviewer")
    c = service.get_collection(db, project, collection_id)
    doc = items_svc.get_item(db, project, body.document)
    baseline = baselines.get_baseline(db, project, body.baseline) if body.baseline else None
    service.add_document(db, project, user, c, doc, baseline)
    db.commit()
    return service.out(db, c, UserDirectory(db))


@router.delete("/{collection_id}/documents/{entry_id}", response_model=Ok)
def remove_document(project_key: str, collection_id: uuid.UUID, entry_id: uuid.UUID,
                    user: User = Depends(current_user), db: Session = Depends(get_db)) -> Ok:
    project = get_project(db, project_key, user, "reviewer")
    service.remove_document(db, project, user, service.get_collection(db, project, collection_id), entry_id)
    db.commit()
    return Ok()


@router.post("/{collection_id}/status")
def set_status(project_key: str, collection_id: uuid.UUID, body: StatusIn, user: User = Depends(current_user),
               db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user, "reviewer")
    c = service.set_status(db, project, user, service.get_collection(db, project, collection_id), body.status)
    db.commit()
    return service.out(db, c, UserDirectory(db))


@router.delete("/{collection_id}", response_model=Ok)
def delete_collection(project_key: str, collection_id: uuid.UUID, user: User = Depends(current_user),
                      db: Session = Depends(get_db)) -> Ok:
    project = get_project(db, project_key, user, "manager")
    c = service.get_collection(db, project, collection_id)
    if c.status == "closed":
        raise Conflict("Closed collections cannot be deleted")
    db.delete(c)
    audit.record(db, actor=user, action="collection.deleted", entity_type="collection", entity_id=c.id,
                 project_id=project.id, summary=f"Deleted collection '{c.name}'")
    db.commit()
    return Ok()


@router.get("/{collection_id}/export.zip", summary="All documents of the collection at their baselines (PDF or Word)")
def export_collection(project_key: str, collection_id: uuid.UUID, format: str = "pdf",
                      user: User = Depends(current_user), db: Session = Depends(get_db),
                      locale: str = Depends(ui_locale)) -> Response:
    project = get_project(db, project_key, user)
    c = service.get_collection(db, project, collection_id)
    safe = "".join(ch if ch.isalnum() else "-" for ch in c.name)[:40]
    return Response(service.export_zip(db, project, c, format, locale), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{project.key}-{safe}-{date.today()}.zip"'})
