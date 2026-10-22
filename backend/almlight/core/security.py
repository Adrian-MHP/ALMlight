"""Password hashing, session tokens and API tokens."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from almlight.core.config import get_settings

_hasher = PasswordHasher()
SESSION_COOKIE = "almlight_session"
API_TOKEN_PREFIX = "alm_"
MIN_PASSWORD_LENGTH = 8


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def create_session_token(user_id: str) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {"sub": user_id, "iat": now, "exp": now + timedelta(hours=settings.session_hours), "typ": "session"}
    return jwt.encode(payload, settings.resolved_secret_key(), algorithm="HS256")


def decode_session_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, get_settings().resolved_secret_key(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    if payload.get("typ") != "session":
        return None
    return payload.get("sub")


def new_api_token() -> tuple[str, str, str]:
    """Return (plaintext token, display prefix, sha256 hash). Only the hash is stored."""
    token = API_TOKEN_PREFIX + secrets.token_urlsafe(32)
    return token, token[:12], hash_api_token(token)


def hash_api_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
