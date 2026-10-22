from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from almlight.core.config import get_settings
from almlight.core.db import get_db
from almlight.core.deps import admin_user, current_user
from almlight.core.schemas import Ok
from almlight.core.security import SESSION_COOKIE, create_session_token
from almlight.modules.identity import service
from almlight.modules.identity.models import ApiToken, User
from almlight.modules.projects.models import Project, ProjectMember

router = APIRouter(tags=["identity"])


class LoginIn(BaseModel):
    username: str
    password: str


class MeOut(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str
    email: str | None
    is_admin: bool
    projects: dict[str, str] = Field(description="Project key -> role")


class UserOut(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str
    email: str | None
    is_admin: bool
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None


class UserIn(BaseModel):
    username: str
    display_name: str
    password: str
    email: str | None = None
    is_admin: bool = False


class UserPatch(BaseModel):
    display_name: str | None = None
    email: str | None = None
    is_admin: bool | None = None
    is_active: bool | None = None
    password: str | None = None


class PasswordIn(BaseModel):
    current_password: str
    new_password: str


class TokenIn(BaseModel):
    name: str
    days: int | None = Field(default=365, ge=1, le=3650)


class TokenOut(BaseModel):
    id: uuid.UUID
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None


class TokenCreated(TokenOut):
    token: str = Field(description="Shown once. Store it securely.")


def _me(db: Session, user: User) -> MeOut:
    if user.is_admin:
        projects = {k: "manager" for k in db.execute(select(Project.key)).scalars()}
    else:
        projects = dict(db.execute(
            select(Project.key, ProjectMember.role).join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(ProjectMember.user_id == user.id)
        ).all())
    return MeOut(id=user.id, username=user.username, display_name=user.display_name, email=user.email,
                 is_admin=user.is_admin, projects=projects)


def _user_out(u: User) -> UserOut:
    return UserOut(id=u.id, username=u.username, display_name=u.display_name, email=u.email, is_admin=u.is_admin,
                   is_active=u.is_active, created_at=u.created_at, last_login_at=u.last_login_at)


@router.post("/auth/login", response_model=MeOut)
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)) -> MeOut:
    user = service.authenticate(db, body.username, body.password)
    db.commit()
    settings = get_settings()
    response.set_cookie(SESSION_COOKIE, create_session_token(str(user.id)), httponly=True, samesite="lax",
                        secure=settings.cookie_secure, max_age=settings.session_hours * 3600, path="/")
    return _me(db, user)


@router.post("/auth/logout", response_model=Ok)
def logout(response: Response) -> Ok:
    response.delete_cookie(SESSION_COOKIE, path="/")
    return Ok()


@router.get("/auth/me", response_model=MeOut)
def me(user: User = Depends(current_user), db: Session = Depends(get_db)) -> MeOut:
    return _me(db, user)


@router.post("/auth/password", response_model=Ok)
def change_password(body: PasswordIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Ok:
    service.change_password(db, user, body.current_password, body.new_password)
    db.commit()
    return Ok()


@router.get("/users/directory", summary="Active users (for pickers)")
def directory(_: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    users = db.execute(select(User).where(User.is_active.is_(True)).order_by(User.display_name)).scalars()
    return [{"id": str(u.id), "username": u.username, "display_name": u.display_name} for u in users]


@router.get("/users", response_model=list[UserOut])
def list_users(_: User = Depends(admin_user), db: Session = Depends(get_db)) -> list[UserOut]:
    return [_user_out(u) for u in db.execute(select(User).order_by(User.username)).scalars()]


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserIn, actor: User = Depends(admin_user), db: Session = Depends(get_db)) -> UserOut:
    user = service.create_user(db, actor, username=body.username, display_name=body.display_name,
                               password=body.password, email=body.email, is_admin=body.is_admin)
    db.commit()
    return _user_out(user)


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: uuid.UUID, body: UserPatch, actor: User = Depends(admin_user),
                db: Session = Depends(get_db)) -> UserOut:
    user = service.admin_update_user(db, actor, service.get_user(db, user_id), **body.model_dump())
    db.commit()
    return _user_out(user)


@router.get("/auth/tokens", response_model=list[TokenOut])
def list_tokens(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[TokenOut]:
    tokens = db.execute(select(ApiToken).where(ApiToken.user_id == user.id).order_by(ApiToken.created_at.desc()))
    return [TokenOut.model_validate(t, from_attributes=True) for t in tokens.scalars()]


@router.post("/auth/tokens", response_model=TokenCreated, status_code=201)
def create_token(body: TokenIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> TokenCreated:
    token, plain = service.create_token(db, user, body.name, body.days)
    db.commit()
    return TokenCreated(**TokenOut.model_validate(token, from_attributes=True).model_dump(), token=plain)


@router.delete("/auth/tokens/{token_id}", response_model=Ok)
def revoke_token(token_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Ok:
    service.revoke_token(db, user, token_id)
    db.commit()
    return Ok()
