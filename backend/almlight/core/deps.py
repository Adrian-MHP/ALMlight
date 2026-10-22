"""FastAPI dependencies: database session and the authenticated user.

Browsers authenticate with an httpOnly session cookie (SameSite=Lax); integrations send
``Authorization: Bearer alm_...`` personal access tokens.
"""

from __future__ import annotations

import uuid

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from almlight.core.db import get_db
from almlight.core.errors import Forbidden, Unauthorized
from almlight.core.security import API_TOKEN_PREFIX, SESSION_COOKIE, decode_session_token
from almlight.modules.identity.models import User
from almlight.modules.identity.service import user_for_token


def optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token.startswith(API_TOKEN_PREFIX):
            user = user_for_token(db, token)
            if user is None:
                raise Unauthorized("Invalid or expired API token")
            return user
        user_id = decode_session_token(token)
    else:
        cookie = request.cookies.get(SESSION_COOKIE)
        user_id = decode_session_token(cookie) if cookie else None
    if not user_id:
        return None
    try:
        user = db.get(User, uuid.UUID(user_id))
    except ValueError:
        return None
    return user if user and user.is_active else None


def current_user(user: User | None = Depends(optional_user)) -> User:
    if user is None:
        raise Unauthorized("Authentication required")
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise Forbidden("Administrator rights required")
    return user
