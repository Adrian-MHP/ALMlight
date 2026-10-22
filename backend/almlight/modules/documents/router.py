from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from almlight.core.db import get_db
from almlight.core.deps import current_user
from almlight.core.errors import ValidationFailed
from almlight.core.schemas import UserDirectory
from almlight.modules.collab.router import flush_project
from almlight.modules.documents import service, word_roundtrip
from almlight.modules.identity.models import User
from almlight.modules.io.document_snapshot import build_snapshot, snapshot_json
from almlight.modules.items import service as items_svc
from almlight.modules.items.models import Comment, Item
from almlight.modules.items.router import comment_threads
from almlight.modules.projects.access import get_project

router = APIRouter(prefix="/projects/{project_key}", tags=["documents"])
MAX_DOCX = 50 * 1024 * 1024


class DocState(BaseModel):
    project: str | None = Field(default=None, description="Project key (default: this project)")
    document: str
    at: str | None = Field(default=None, description="ISO timestamp — the document as of this instant")
    baseline: uuid.UUID | None = None
    variant: str | None = None


class CompareIn(BaseModel):
    left: DocState
    right: DocState
    fields: list[str] | None = Field(default=None, description="Only compare these custom fields")


@router.get("/items/{item_key}/document", summary="A document live, as of a point in time, or from a baseline")
def document(project_key: str, item_key: str, at: str | None = None, baseline: uuid.UUID | None = None,
             variant: str | None = None, numbering: bool = True, user: User = Depends(current_user),
             db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    root = items_svc.get_item(db, project, item_key)
    snap = build_snapshot(db, project, root, at=service.parse_at(at), baseline_id=baseline, variant_key=variant,
                          numbering=numbering)
    return snapshot_json(snap)


@router.get("/items/{item_key}/document-history", summary="All changes of a document and its items")
def document_history(project_key: str, item_key: str, limit: int = 500, user: User = Depends(current_user),
                     db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    return service.history(db, project, items_svc.get_item(db, project, item_key), min(limit, 2000))


@router.post("/compare-documents", summary="Compare two document states (revisions, baselines, branches, documents)")
def compare_documents(project_key: str, body: CompareIn, user: User = Depends(current_user),
                      db: Session = Depends(get_db)) -> dict[str, Any]:
    home = get_project(db, project_key, user)

    def snap(side: DocState):
        project = get_project(db, side.project, user) if side.project else home
        root = items_svc.get_item(db, project, side.document)
        return service.snapshot_for(db, project, root, at=side.at, baseline=side.baseline, variant=side.variant)

    return service.compare(db, snap(body.left), snap(body.right), fields=body.fields)


@router.post("/items/{item_key}/import-docx", summary="Word round trip: import edits and comments (dry run first)")
def import_docx(project_key: str, item_key: str, file: UploadFile = File(...), dry_run: bool = Form(default=True),
                user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user, "contributor")
    doc = items_svc.get_item(db, project, item_key)
    content = file.file.read(MAX_DOCX + 1)
    if len(content) > MAX_DOCX:
        raise ValidationFailed("File too large")
    if not dry_run:
        flush_project(project.id)
    result = word_roundtrip.import_docx(db, project, user, doc, file.filename or "review.docx", content,
                                       dry_run=dry_run)
    db.commit()
    return result


@router.get("/items/{item_key}/document-comments", summary="Comment threads of all items in a document")
def document_comments(project_key: str, item_key: str, resolved: bool = True, user: User = Depends(current_user),
                      db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    project = get_project(db, project_key, user)
    root = items_svc.get_item(db, project, item_key)
    snap = build_snapshot(db, project, root, numbering=False)
    ids = [root.id, *[n.item_id for n in snap.walk()]]
    keys = dict(db.execute(select(Item.id, Item.key).where(Item.id.in_(ids))).all())
    comments = db.execute(select(Comment).where(Comment.item_id.in_(ids), Comment.deleted_at.is_(None))
                          .order_by(Comment.created_at)).scalars().all()
    threads = comment_threads(db, list(comments), UserDirectory(db), keys)
    order = {iid: i for i, iid in enumerate(ids)}
    key_order = {keys[i]: order[i] for i in ids if i in keys}
    threads.sort(key=lambda t: (key_order.get(t.item_key or "", 1e9), t.created_at))
    return [t.model_dump(mode="json") for t in threads if resolved or not t.resolved]
