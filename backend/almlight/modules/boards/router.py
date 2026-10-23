"""Kanban boards (Polarion boards): items as cards, columns by status or any enum/user field, optional swimlanes,
WIP limits. Moving a card runs the real workflow transition or field change (through the bulk/transition API), so
all lifecycle rules apply. Boards are personal or shared, like saved queries."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from almlight.core.db import get_db, utcnow
from almlight.core.deps import current_user
from almlight.core.errors import Forbidden, NotFound, ValidationFailed
from almlight.core.schemas import Ok, UserDirectory
from almlight.modules.audit import service as audit
from almlight.modules.boards.models import Board
from almlight.modules.identity.models import User
from almlight.modules.items.query import custom_fields, field_info, parse_conditions
from almlight.modules.projects.access import get_project, has_role
from almlight.modules.projects.models import Project

router = APIRouter(prefix="/projects/{project_key}", tags=["boards"])
GROUPINGS_FIXED = ("state", "owner", "release", "type")


class BoardConfig(BaseModel):
    model_config = {"extra": "forbid"}

    types: list[str] = Field(default_factory=list, max_length=30)
    q: str | None = Field(default=None, max_length=500)
    conditions: list[dict[str, Any]] = Field(default_factory=list, max_length=40)
    columns_by: str = "state"
    swimlanes_by: str | None = None
    hidden_columns: list[str] = Field(default_factory=list, max_length=100)
    column_order: list[str] = Field(default_factory=list, max_length=100)
    wip: dict[str, int] = Field(default_factory=dict)
    card_fields: list[str] = Field(default_factory=list, max_length=6)

    @field_validator("wip")
    @classmethod
    def _wip(cls, v: dict[str, int]) -> dict[str, int]:
        if any(n < 0 or n > 999 for n in v.values()):
            raise ValueError("WIP limits are between 0 and 999")
        return v


class BoardIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    shared: bool = False
    config: BoardConfig = Field(default_factory=BoardConfig)


def _check_grouping(project: Project, value: str, what: str) -> None:
    if value in GROUPINGS_FIXED:
        return
    if value.startswith("field."):
        f = custom_fields(project).get(value[6:])
        if f is not None and f.type in ("enum", "user", "boolean"):
            return  # computed enums (e.g. risk level) group cards but cannot be changed by moving them
    raise ValidationFailed(f"{what} must be state, owner, release, type or an enum/user field (field.<key>)")


def validate_config(project: Project, cfg: BoardConfig) -> dict[str, Any]:
    for t in cfg.types:
        if project.model.item_type(t) is None:
            raise ValidationFailed(f"Unknown item type '{t}'")
    for c in parse_conditions(cfg.conditions):
        field_info(project, c.field)
    _check_grouping(project, cfg.columns_by, "Columns")
    if cfg.swimlanes_by:
        _check_grouping(project, cfg.swimlanes_by, "Swimlanes")
        if cfg.swimlanes_by == cfg.columns_by:
            raise ValidationFailed("Columns and swimlanes need different groupings")
    if cfg.columns_by == "release" and project.model.item_type(project.model.semantics.release_type or "") is None:
        raise ValidationFailed("This information model has no release type")
    for f in cfg.card_fields:
        if f not in custom_fields(project):
            raise ValidationFailed(f"Unknown card field '{f}'")
    return cfg.model_dump()


def _normalized(config: dict[str, Any]) -> dict[str, Any]:
    """Stored configs may predate newer options: always return every key with its default."""
    try:
        return BoardConfig.model_validate(config).model_dump()
    except ValueError:
        return {**BoardConfig().model_dump(), **{k: v for k, v in config.items() if k in BoardConfig.model_fields}}


def _out(b: Board, users: UserDirectory, can_edit: bool) -> dict[str, Any]:
    return {"id": str(b.id), "name": b.name, "shared": b.shared, "config": _normalized(b.config),
            "owner": users.ref(b.owner_id), "updated_at": b.updated_at.isoformat(), "can_edit": can_edit}


def _get(db: Session, project: Project, board_id: uuid.UUID, user: User) -> Board:
    b = db.get(Board, board_id)
    if b is None or b.project_id != project.id or (not b.shared and b.owner_id != user.id):
        raise NotFound("Board not found")
    return b


@router.get("/boards", summary="My boards and the shared ones")
def list_boards(project_key: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    project = get_project(db, project_key, user)
    rows = db.execute(select(Board).where(Board.project_id == project.id,
                                          or_(Board.owner_id == user.id, Board.shared.is_(True)))
                      .order_by(Board.name)).scalars().all()
    users = UserDirectory(db)
    manager = has_role(db, project, user, "manager")
    return [_out(b, users, manager or b.owner_id == user.id) for b in rows]


@router.post("/boards", status_code=201, summary="Create a board")
def create_board(project_key: str, body: BoardIn, user: User = Depends(current_user),
                 db: Session = Depends(get_db)) -> dict:
    project = get_project(db, project_key, user)
    if body.shared and not has_role(db, project, user, "contributor"):
        raise Forbidden("Sharing a board needs the contributor role")
    b = Board(project_id=project.id, owner_id=user.id, name=body.name.strip(), shared=body.shared,
              config=validate_config(project, body.config))
    db.add(b)
    db.flush()
    audit.record(db, actor=user, action="board.created", entity_type="board", entity_id=b.id, project_id=project.id,
                 summary=f"Created {'shared ' if b.shared else ''}board '{b.name}'")
    db.commit()
    return _out(b, UserDirectory(db), True)


@router.get("/boards/{board_id}", summary="One board")
def get_board(project_key: str, board_id: uuid.UUID, user: User = Depends(current_user),
              db: Session = Depends(get_db)) -> dict:
    project = get_project(db, project_key, user)
    b = _get(db, project, board_id, user)
    return _out(b, UserDirectory(db), b.owner_id == user.id or has_role(db, project, user, "manager"))


@router.put("/boards/{board_id}", summary="Change a board (owner or manager)")
def update_board(project_key: str, board_id: uuid.UUID, body: BoardIn, user: User = Depends(current_user),
                 db: Session = Depends(get_db)) -> dict:
    project = get_project(db, project_key, user)
    b = _get(db, project, board_id, user)
    if b.owner_id != user.id and not has_role(db, project, user, "manager"):
        raise Forbidden("Only the owner or a project manager can change a shared board")
    if body.shared and not has_role(db, project, user, "contributor"):
        raise Forbidden("Sharing a board needs the contributor role")
    b.name, b.shared, b.config, b.updated_at = (body.name.strip(), body.shared,
                                                validate_config(project, body.config), utcnow())
    db.commit()
    return _out(b, UserDirectory(db), True)


@router.delete("/boards/{board_id}", response_model=Ok, summary="Delete a board (owner or manager)")
def delete_board(project_key: str, board_id: uuid.UUID, user: User = Depends(current_user),
                 db: Session = Depends(get_db)) -> Ok:
    project = get_project(db, project_key, user)
    b = _get(db, project, board_id, user)
    if b.owner_id != user.id and not has_role(db, project, user, "manager"):
        raise Forbidden("Only the owner or a project manager can delete a shared board")
    db.delete(b)
    db.commit()
    return Ok()
