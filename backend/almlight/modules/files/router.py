"""File check-out / check-in, file revisions and their history."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from almlight.core.db import get_db
from almlight.core.deps import current_user
from almlight.core.schemas import UserDirectory
from almlight.modules.files import service
from almlight.modules.identity.models import User
from almlight.modules.items import service as items_svc
from almlight.modules.items.schemas import ItemDetailOut, item_detail
from almlight.modules.projects.access import get_project

router = APIRouter(tags=["files"])
P = "/projects/{project_key}/items/{item_key}/attachments/{attachment_id}"


class CheckoutIn(BaseModel):
    note: str | None = Field(default=None, max_length=500, description="Why the file is checked out")


@router.post(f"{P}/checkout", response_model=ItemDetailOut, summary="Check out a file (exclusive editing lock)")
def checkout(project_key: str, item_key: str, attachment_id: str, body: CheckoutIn | None = None,
             user: User = Depends(current_user), db: Session = Depends(get_db)) -> ItemDetailOut:
    project = get_project(db, project_key, user, "contributor")
    item = items_svc.get_item(db, project, item_key)
    service.checkout(db, project, user, item, attachment_id, body.note if body else None)
    db.commit()
    return item_detail(db, project, item, UserDirectory(db))


@router.delete(f"{P}/checkout", response_model=ItemDetailOut, summary="Cancel a check-out (holder or manager)")
def cancel_checkout(project_key: str, item_key: str, attachment_id: str, user: User = Depends(current_user),
                    db: Session = Depends(get_db)) -> ItemDetailOut:
    project = get_project(db, project_key, user, "contributor")
    item = items_svc.get_item(db, project, item_key)
    service.cancel(db, project, user, item, attachment_id)
    db.commit()
    return item_detail(db, project, item, UserDirectory(db))


@router.post(f"{P}/revisions", response_model=ItemDetailOut, status_code=201,
             summary="Check in a new revision of the file (releases the caller's check-out)")
def check_in(project_key: str, item_key: str, attachment_id: str, file: UploadFile = File(...),
             comment: str | None = Form(default=None), user: User = Depends(current_user),
             db: Session = Depends(get_db)) -> ItemDetailOut:
    project = get_project(db, project_key, user, "contributor")
    item = items_svc.get_item(db, project, item_key)
    items_svc.revise_attachment(db, project, user, item, attachment_id, filename=file.filename,
                                content_type=file.content_type, stream=file.file, comment=comment)
    db.commit()
    return item_detail(db, project, item, UserDirectory(db))


@router.get(f"{P}/history", summary="All revisions of the file, newest first")
def history(project_key: str, item_key: str, attachment_id: str, user: User = Depends(current_user),
            db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    project = get_project(db, project_key, user)
    item = items_svc.get_item(db, project, item_key)
    rows = items_svc.attachment_history(db, item, attachment_id)
    users = UserDirectory(db)
    for r in rows:
        r["uploaded_by"] = users.ref(r.get("uploaded_by"))
    return rows


@router.get("/checkouts/mine", summary="Files I have checked out, in all projects")
def my_checkouts(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return service.mine(db, user)
