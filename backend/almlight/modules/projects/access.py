"""Project-level authorisation.

Roles are ordered: viewer < contributor < reviewer < manager. System administrators act
as managers in every project. Membership is the only source of project access.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from almlight.core.errors import Forbidden, NotFound
from almlight.modules.identity.models import User
from almlight.modules.projects.metamodel import ROLE_RANK
from almlight.modules.projects.models import Project, ProjectMember


def project_role(db: Session, project: Project, user: User | None) -> str | None:
    if user is None:
        return None
    if user.is_admin:
        return "manager"
    cache: dict = db.info.setdefault("role_cache", {})
    key = (project.id, user.id)
    if key not in cache:
        cache[key] = db.execute(
            select(ProjectMember.role).where(ProjectMember.project_id == project.id, ProjectMember.user_id == user.id)
        ).scalar()
    return cache[key]


def has_role(db: Session, project: Project, user: User | None, min_role: str) -> bool:
    role = project_role(db, project, user)
    return role is not None and ROLE_RANK[role] >= ROLE_RANK[min_role]


def require_role(db: Session, project: Project, user: User | None, min_role: str) -> str:
    role = project_role(db, project, user)
    if role is None:
        # Do not reveal that the project exists.
        raise NotFound(f"Project '{project.key}' not found")
    if ROLE_RANK[role] < ROLE_RANK[min_role]:
        raise Forbidden(f"This action needs the '{min_role}' role in project {project.key}", {"role": role})
    return role


def get_project(db: Session, key: str, user: User | None, min_role: str = "viewer") -> Project:
    project = db.execute(select(Project).where(Project.key == key.upper())).scalar_one_or_none()
    if project is None:
        raise NotFound(f"Project '{key}' not found")
    require_role(db, project, user, min_role)
    return project
