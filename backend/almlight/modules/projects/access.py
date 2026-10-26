"""Project-level authorisation.

Roles are ordered: viewer < contributor < reviewer < manager. System administrators act
as managers in every project. Access comes from membership, or from the project's ``open_role`` that every
signed-in user holds (example projects, company-wide read access).
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.orm import Session

from almlight.core.errors import Forbidden, NotFound
from almlight.modules.identity.models import User
from almlight.modules.projects.metamodel import ROLE_RANK
from almlight.modules.projects.models import Project, ProjectMember


def best_role(*roles: str | None) -> str | None:
    """The highest of the given roles (None = no role)."""
    held = [r for r in roles if r]
    return max(held, key=lambda r: ROLE_RANK[r]) if held else None


def readable(user: User) -> ColumnElement[bool]:
    """SQL condition for the projects a user can open: a member, or the project is open to every signed-in user."""
    return or_(Project.open_role.is_not(None),
               Project.id.in_(select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)))


def project_role(db: Session, project: Project, user: User | None) -> str | None:
    if user is None:
        return None
    if user.is_admin:
        return "manager"
    cache: dict = db.info.setdefault("role_cache", {})
    key = (project.id, user.id)
    if key not in cache:
        member = db.execute(
            select(ProjectMember.role).where(ProjectMember.project_id == project.id, ProjectMember.user_id == user.id)
        ).scalar()
        cache[key] = best_role(member, project.open_role)  # membership and the open role: the higher one counts
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
