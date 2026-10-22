from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from almlight.core.db import get_db
from almlight.core.deps import current_user
from almlight.core.schemas import UserDirectory
from almlight.modules.baselines import service
from almlight.modules.baselines.models import Baseline
from almlight.modules.identity.models import User
from almlight.modules.items import service as items_svc
from almlight.modules.items.models import Item
from almlight.modules.projects.access import get_project

router = APIRouter(prefix="/projects/{project_key}/baselines", tags=["baselines"])


class BaselineIn(BaseModel):
    name: str
    description: str | None = None
    scope: str | None = None
    revision_rule: str = "latest"


def _out(db: Session, b: Baseline, users: UserDirectory) -> dict[str, Any]:
    scope_key = db.execute(select(Item.key).where(Item.id == b.scope_root_id)).scalar() if b.scope_root_id else None
    return {"id": str(b.id), "name": b.name, "description": b.description, "scope": scope_key,
            "revision_rule": b.revision_rule, "item_count": b.item_count, "link_count": b.link_count,
            "created_by": users.ref(b.created_by), "created_at": b.created_at.isoformat()}


@router.get("")
def list_baselines(project_key: str, user: User = Depends(current_user), db: Session = Depends(get_db)
                   ) -> list[dict[str, Any]]:
    project = get_project(db, project_key, user)
    rows = db.execute(select(Baseline).where(Baseline.project_id == project.id)
                      .order_by(Baseline.created_at.desc())).scalars().all()
    users = UserDirectory(db)
    return [_out(db, b, users) for b in rows]


@router.post("", status_code=201)
def create_baseline(project_key: str, body: BaselineIn, user: User = Depends(current_user),
                    db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user, "reviewer")
    scope = items_svc.get_item(db, project, body.scope) if body.scope else None
    b = service.create_baseline(db, project, user, name=body.name, description=body.description, scope_root=scope,
                                revision_rule=body.revision_rule)
    db.commit()
    return _out(db, b, UserDirectory(db))


@router.get("/{baseline_id}")
def get_baseline(project_key: str, baseline_id: uuid.UUID, user: User = Depends(current_user),
                 db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    b = service.get_baseline(db, project, baseline_id)
    entries = service.baseline_entries(db, b)
    out = _out(db, b, UserDirectory(db))
    out["items"] = [{"id": str(it.id), "key": it.key, "type_key": it.type_key, "title": v.title,
                     "version": v.version_label, "version_no": v.version_no, "state": bi.state,
                     "current_version": it.version_label, "deleted": it.deleted_at is not None}
                    for bi, v, it in entries]
    return out


@router.get("/{baseline_id}/compare")
def compare(project_key: str, baseline_id: uuid.UUID, to: uuid.UUID | None = None,
            user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Compare a baseline with another baseline (``to``) or with the current state."""
    project = get_project(db, project_key, user)
    a = service.get_baseline(db, project, baseline_id)
    b = service.get_baseline(db, project, to) if to else None
    return service.compare(db, project, a, b)
