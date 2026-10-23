"""Saved queries: store a filter of the item list (incl. traceability gaps) and reuse or share it."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from almlight.core.db import get_db, utcnow
from almlight.core.deps import current_user
from almlight.core.errors import Forbidden, NotFound, ValidationFailed
from almlight.core.schemas import Ok, UserDirectory
from almlight.modules.audit import service as audit
from almlight.modules.identity.models import User
from almlight.modules.items import service as items_svc
from almlight.modules.projects.access import get_project, has_role
from almlight.modules.queries.models import SavedQuery

router = APIRouter(prefix="/projects/{project_key}", tags=["saved queries"])
ALLOWED = {"q", "type", "state", "owner", "suspect", "fields", "sort", "link_type", "link_dir", "link_exists",
           "updated_since", "planned_in", "conditions", "columns"}


class QueryIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    query: dict[str, Any] = Field(default_factory=dict)
    shared: bool = False


def _clean(query: dict[str, Any], project: Any = None) -> dict[str, Any]:
    from almlight.modules.items.query import field_info, parse_conditions

    unknown = set(query) - ALLOWED
    if unknown:
        raise ValidationFailed(f"Unknown query keys {sorted(unknown)}")
    if query.get("conditions"):
        conds = parse_conditions(query["conditions"])
        if project is not None:
            for c in conds:
                field_info(project, c.field)
        query = {**query, "conditions": [c.dump() for c in conds]}
    cols = query.get("columns")
    if cols is not None and (not isinstance(cols, list) or len(cols) > 40 or not all(isinstance(c, str) for c in cols)):
        raise ValidationFailed("columns must be a list of up to 40 column names")
    return {k: v for k, v in query.items() if v not in (None, "", [], {})}


def to_item_query(q: dict[str, Any], limit: int = 50, offset: int = 0,
                  user_id: uuid.UUID | None = None) -> items_svc.ItemQuery:
    from almlight.modules.items.query import parse_conditions

    owner = q.get("owner")
    since = None
    if q.get("updated_since"):
        from almlight.modules.documents.service import parse_at

        v = str(q["updated_since"])
        since = parse_at(v if "T" in v else f"{v}T00:00:00")
    return items_svc.ItemQuery(
        q=q.get("q"), types=q.get("type") or None, states=q.get("state") or None,
        owner_id=uuid.UUID(owner) if owner else None, suspect=q.get("suspect") or None,
        field_filters=q.get("fields") or None, sort=q.get("sort") or "key", limit=limit, offset=offset,
        link_type=q.get("link_type"), link_dir=q.get("link_dir") or "out",
        link_exists=q.get("link_exists") if isinstance(q.get("link_exists"), bool) else None,
        updated_since=since, planned_in=q.get("planned_in"),
        conditions=parse_conditions(q.get("conditions")) or None, user_id=user_id)


def _out(sq: SavedQuery, users: UserDirectory, count: int | None = None, can_edit: bool = True) -> dict[str, Any]:
    return {"id": str(sq.id), "name": sq.name, "query": sq.query, "shared": sq.shared, "owner": users.ref(sq.owner_id),
            "updated_at": sq.updated_at.isoformat(), "count": count, "can_edit": can_edit}


def _get(db: Session, project_id: uuid.UUID, query_id: uuid.UUID, user: User) -> SavedQuery:
    sq = db.get(SavedQuery, query_id)
    if sq is None or sq.project_id != project_id or (not sq.shared and sq.owner_id != user.id):
        raise NotFound("Saved query not found")
    return sq


@router.get("/queries", summary="My saved queries and the shared ones, with current result counts")
def list_queries(project_key: str, counts: bool = True, user: User = Depends(current_user),
                 db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    project = get_project(db, project_key, user)
    rows = db.execute(select(SavedQuery).where(SavedQuery.project_id == project.id,
                                               or_(SavedQuery.owner_id == user.id, SavedQuery.shared.is_(True)))
                      .order_by(SavedQuery.shared, SavedQuery.name)).scalars().all()
    users = UserDirectory(db)
    users.preload({r.owner_id for r in rows})
    manager = has_role(db, project, user, "manager")
    out = []
    for r in rows:
        count = None
        if counts:
            try:
                count = items_svc.query_items(db, project, to_item_query(r.query, limit=1, user_id=user.id))[1]
            except Exception:  # noqa: BLE001 — a query that no longer fits the model shows no count
                count = None
        out.append(_out(r, users, count, can_edit=manager or r.owner_id == user.id))
    return out


@router.post("/queries", status_code=201)
def create_query(project_key: str, body: QueryIn, user: User = Depends(current_user),
                 db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    if body.shared and not has_role(db, project, user, "contributor"):
        raise Forbidden("Sharing a query needs the contributor role")
    sq = SavedQuery(project_id=project.id, owner_id=user.id, name=body.name.strip(), query=_clean(body.query, project),
                    shared=body.shared)
    db.add(sq)
    db.flush()
    audit.record(db, actor=user, action="query.saved", entity_type="query", entity_id=sq.id, project_id=project.id,
                 summary=f"Saved {'shared ' if sq.shared else ''}query '{sq.name}'")
    db.commit()
    return _out(sq, UserDirectory(db))


@router.put("/queries/{query_id}")
def update_query(project_key: str, query_id: uuid.UUID, body: QueryIn, user: User = Depends(current_user),
                 db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    sq = _get(db, project.id, query_id, user)
    if sq.owner_id != user.id and not has_role(db, project, user, "manager"):
        raise Forbidden("Only the owner or a project manager can change a shared query")
    sq.name, sq.query, sq.shared, sq.updated_at = body.name.strip(), _clean(body.query, project), body.shared, utcnow()
    db.commit()
    return _out(sq, UserDirectory(db))


@router.delete("/queries/{query_id}", response_model=Ok)
def delete_query(project_key: str, query_id: uuid.UUID, user: User = Depends(current_user),
                 db: Session = Depends(get_db)) -> Ok:
    project = get_project(db, project_key, user)
    sq = _get(db, project.id, query_id, user)
    if sq.owner_id != user.id and not has_role(db, project, user, "manager"):
        raise Forbidden("Only the owner or a project manager can delete a shared query")
    db.delete(sq)
    db.commit()
    return Ok()
