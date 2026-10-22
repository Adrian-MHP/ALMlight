from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from almlight.core.db import get_db
from almlight.core.deps import current_user
from almlight.modules.branches import service
from almlight.modules.branches.models import Branch
from almlight.modules.collab.router import flush_project
from almlight.modules.identity.models import User
from almlight.modules.items import service as items_svc
from almlight.modules.items.models import Item
from almlight.modules.projects.access import get_project

router = APIRouter(prefix="/projects/{project_key}", tags=["branches"])


class BranchIn(BaseModel):
    name: str
    description: str | None = None


class MergeIn(BaseModel):
    direction: str = Field(description="to_source (branch -> source) or from_source (source -> branch)")
    items: list[str] | None = Field(default=None, description="Branch item keys to merge; default: all")
    resolutions: dict[str, dict[str, str]] = Field(
        default_factory=dict, description="{branch_key: {field: 'branch' | 'source'}} for conflicts")
    include_added: bool = True


def _out(db: Session, b: Branch) -> dict[str, Any]:
    return service.branch_out(b, db.get(Item, b.source_root_id), db.get(Item, b.branch_root_id))


@router.post("/items/{item_key}/branch", status_code=201)
def create_branch(project_key: str, item_key: str, body: BranchIn, user: User = Depends(current_user),
                  db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user, "contributor")
    branch = service.create_branch(db, project, user, items_svc.get_item(db, project, item_key), name=body.name,
                                   description=body.description)
    db.commit()
    return _out(db, branch)


@router.get("/items/{item_key}/branches", summary="Branches of this item, or the branch it is the root of")
def item_branches(project_key: str, item_key: str, user: User = Depends(current_user),
                  db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    project = get_project(db, project_key, user)
    item = items_svc.get_item(db, project, item_key)
    rows = db.execute(select(Branch).where(or_(Branch.source_root_id == item.id, Branch.branch_root_id == item.id))
                      .order_by(Branch.created_at.desc())).scalars().all()
    return [_out(db, b) for b in rows]


@router.get("/branches")
def list_branches(project_key: str, user: User = Depends(current_user), db: Session = Depends(get_db)
                  ) -> list[dict[str, Any]]:
    project = get_project(db, project_key, user)
    rows = db.execute(select(Branch).where(Branch.project_id == project.id).order_by(Branch.created_at.desc()))
    return [_out(db, b) for b in rows.scalars()]


@router.get("/branches/{branch_id}/preview", summary="3-way merge preview")
def merge_preview(project_key: str, branch_id: uuid.UUID, user: User = Depends(current_user),
                  db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    return service.preview(db, project, service.get_branch(db, project, branch_id))


@router.post("/branches/{branch_id}/merge")
def merge(project_key: str, branch_id: uuid.UUID, body: MergeIn, user: User = Depends(current_user),
          db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user, "contributor")
    flush_project(project.id)
    result = service.merge(db, project, user, service.get_branch(db, project, branch_id), direction=body.direction,
                           keys=body.items, resolutions=body.resolutions, include_added=body.include_added)
    db.commit()
    return result
