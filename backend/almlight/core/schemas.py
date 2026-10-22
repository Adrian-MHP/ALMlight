"""Shared API schemas and serialisation helpers."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from almlight.modules.identity.models import User

T = TypeVar("T")


class UserRef(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class Ok(BaseModel):
    ok: bool = True


class UserDirectory:
    """Request-scoped lookup of user references (avoids N+1 queries when serialising)."""

    def __init__(self, db: Session):
        self.db = db
        self._cache: dict[uuid.UUID, UserRef | None] = {}

    def preload(self, ids: set[uuid.UUID | None]) -> None:
        missing = {i for i in ids if i and i not in self._cache}
        if missing:
            for u in self.db.execute(select(User).where(User.id.in_(missing))).scalars():
                self._cache[u.id] = UserRef(id=u.id, username=u.username, display_name=u.display_name)
            for i in missing:
                self._cache.setdefault(i, None)

    def ref(self, user_id: uuid.UUID | str | None) -> UserRef | None:
        if not user_id:
            return None
        uid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
        if uid not in self._cache:
            self.preload({uid})
        return self._cache.get(uid)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def drop_none(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}
