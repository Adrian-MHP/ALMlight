from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from almlight.core.db import get_db
from almlight.core.deps import admin_user, current_user, ui_locale
from almlight.core.i18n import tr
from almlight.core.schemas import Ok, UserDirectory
from almlight.modules.audit.models import AuditEntry
from almlight.modules.audit.service import verify_chain
from almlight.modules.identity.models import User
from almlight.modules.identity.service import get_user
from almlight.modules.projects import service
from almlight.modules.projects.access import get_project, project_role, readable
from almlight.modules.projects.metamodel import available_templates, dump_config
from almlight.modules.projects.models import Project, ProjectMember

router = APIRouter(tags=["projects"])


class ProjectIn(BaseModel):
    key: str
    name: str
    template: str = "systems_engineering"
    description: str | None = None


class ProjectPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    open_role: Literal["viewer", "contributor", "reviewer"] | None = Field(
        default=None, description="Role of every signed-in user in this project; null = members only")


class ProjectOut(BaseModel):
    id: uuid.UUID
    key: str
    name: str
    description: str | None
    template_key: str
    config_version: int
    role: str | None
    open_role: str | None = None
    created_at: datetime


class MemberIn(BaseModel):
    user_id: uuid.UUID
    role: str
    hours_per_day: float | None = Field(default=None, ge=0, le=24, description="Working hours per day for this project")


def _out(db: Session, p: Project, user: User) -> ProjectOut:
    return ProjectOut(id=p.id, key=p.key, name=p.name, description=p.description, template_key=p.template_key,
                      config_version=p.config_version, role=project_role(db, p, user), open_role=p.open_role,
                      created_at=p.created_at)


@router.get("/templates")
def templates(_: User = Depends(current_user)) -> list[dict[str, Any]]:
    return [{"key": t.key, "label": t.label, "description": t.description,
             "item_types": [it.label for it in t.item_types]} for t in available_templates().values()]


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[ProjectOut]:
    stmt = select(Project).where(Project.archived_at.is_(None)).order_by(Project.key)
    if not user.is_admin:
        stmt = stmt.where(readable(user))
    return [_out(db, p, user) for p in db.execute(stmt).scalars()]


@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectIn, user: User = Depends(admin_user), db: Session = Depends(get_db)) -> ProjectOut:
    project = service.create_project(db, user, key=body.key, name=body.name, template_key=body.template,
                                     description=body.description)
    db.commit()
    return _out(db, project, user)


@router.get("/projects/{project_key}", response_model=ProjectOut)
def get_one(project_key: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> ProjectOut:
    return _out(db, get_project(db, project_key, user), user)


@router.patch("/projects/{project_key}", response_model=ProjectOut)
def update(project_key: str, body: ProjectPatch, user: User = Depends(current_user),
           db: Session = Depends(get_db)) -> ProjectOut:
    project = get_project(db, project_key, user, "manager")
    service.update_project(db, user, project, name=body.name, description=body.description,
                           open_role=body.open_role if "open_role" in body.model_fields_set else service.UNSET)
    db.commit()
    return _out(db, project, user)


@router.get("/projects/{project_key}/config", summary="The project's information model")
def get_config(project_key: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    project = get_project(db, project_key, user)
    return {"version": project.config_version, "config": dump_config(project.model)}


@router.get("/projects/{project_key}/template-updates", summary="Additions available from the shipped template")
def get_template_updates(project_key: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    project = get_project(db, project_key, user)
    return service.template_updates(project)


@router.post("/projects/{project_key}/template-updates", summary="Take over the template's additions (manager)")
def apply_template_updates(project_key: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    project = get_project(db, project_key, user, "manager")
    applied = service.apply_template_updates(db, user, project)
    db.commit()
    return {"applied": applied, "version": project.config_version}


@router.put("/projects/{project_key}/config")
def put_config(project_key: str, body: dict[str, Any], user: User = Depends(current_user),
               db: Session = Depends(get_db)) -> dict:
    project = get_project(db, project_key, user, "manager")
    service.update_config(db, user, project, body.get("config", body))
    db.commit()
    return {"version": project.config_version, "config": dump_config(project.model)}


@router.get("/projects/{project_key}/stats")
def stats(project_key: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return service.stats(db, get_project(db, project_key, user))


@router.get("/projects/{project_key}/members")
def members(project_key: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    project = get_project(db, project_key, user)
    rows = db.execute(select(ProjectMember, User).join(User, User.id == ProjectMember.user_id)
                      .where(ProjectMember.project_id == project.id).order_by(User.display_name)).all()
    return [{"user_id": str(u.id), "username": u.username, "display_name": u.display_name, "role": m.role,
             "active": u.is_active, "hours_per_day": m.hours_per_day} for m, u in rows]


@router.put("/projects/{project_key}/members", response_model=Ok)
def set_member(project_key: str, body: MemberIn, user: User = Depends(current_user),
               db: Session = Depends(get_db)) -> Ok:
    project = get_project(db, project_key, user, "manager")
    service.set_member(db, user, project, get_user(db, body.user_id), body.role, hours_per_day=body.hours_per_day)
    db.commit()
    return Ok()


@router.delete("/projects/{project_key}/members/{user_id}", response_model=Ok)
def remove_member(project_key: str, user_id: uuid.UUID, user: User = Depends(current_user),
                  db: Session = Depends(get_db)) -> Ok:
    project = get_project(db, project_key, user, "manager")
    service.remove_member(db, user, project, user_id)
    db.commit()
    return Ok()


@router.get("/projects/{project_key}/audit", summary="Audit trail of the project")
def audit_log(project_key: str, action: str | None = None, limit: int = Query(default=100, ge=1, le=1000),
              before_id: int | None = None, user: User = Depends(current_user),
              db: Session = Depends(get_db), locale: str = Depends(ui_locale)) -> list[dict]:
    project = get_project(db, project_key, user)
    stmt = select(AuditEntry).where(AuditEntry.project_id == project.id)
    if action:
        stmt = stmt.where(AuditEntry.action.like(f"{action}%"))
    if before_id:
        stmt = stmt.where(AuditEntry.id < before_id)
    rows = db.execute(stmt.order_by(AuditEntry.id.desc()).limit(limit)).scalars().all()
    return [{"id": e.id, "ts": e.ts.isoformat(), "actor": e.actor_name, "action": e.action,
             "entity_type": e.entity_type, "entity_id": e.entity_id, "summary": tr(e.summary, locale),
             "details": e.details, "hash": e.hash} for e in rows]


@router.get("/admin/audit/verify", summary="Verify the tamper-evident hash chain of the audit trail")
def audit_verify(_: User = Depends(admin_user), db: Session = Depends(get_db)) -> dict:
    return verify_chain(db)


@router.get("/search", summary="Full-text search across all projects you can read")
def search(q: str, limit: int = Query(default=30, ge=1, le=200), user: User = Depends(current_user),
           db: Session = Depends(get_db)) -> list[dict]:
    from almlight.modules.items.schemas import items_out
    from almlight.modules.items.service import ItemQuery, query_items

    stmt = select(Project).where(Project.archived_at.is_(None))
    if not user.is_admin:
        stmt = stmt.where(readable(user))
    users = UserDirectory(db)
    out: list[dict] = []
    for project in db.execute(stmt).scalars():
        items, _ = query_items(db, project, ItemQuery(q=q, limit=limit, sort="-updated"))
        out += [i.model_dump(mode="json") for i in items_out(project, items, users)]
    out.sort(key=lambda r: r["updated_at"], reverse=True)
    return out[:limit]
