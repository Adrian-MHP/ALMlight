from __future__ import annotations

import logging
import math
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from almlight.core.config import get_settings
from almlight.core.db import utcnow
from almlight.core.errors import Conflict, NotFound, TooManyRequests, Unauthorized, ValidationFailed
from almlight.core.ratelimit import login_failures
from almlight.core.security import (
    MIN_PASSWORD_LENGTH,
    burn_password_check,
    hash_api_token,
    hash_password,
    new_api_token,
    verify_password,
)
from almlight.modules.audit import service as audit
from almlight.modules.identity.models import ApiToken, User

log = logging.getLogger("almlight.identity")
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,62}$")


def _check_password(password: str) -> None:
    if len(password or "") < MIN_PASSWORD_LENGTH:
        raise ValidationFailed(f"Password must have at least {MIN_PASSWORD_LENGTH} characters")


def create_user(db: Session, actor: User | None, *, username: str, display_name: str, password: str,
                email: str | None = None, is_admin: bool = False) -> User:
    username = (username or "").strip().lower()
    if not USERNAME_RE.match(username):
        raise ValidationFailed("Username: 2-63 characters, lowercase letters, digits, '.', '_' or '-'")
    _check_password(password)
    if db.execute(select(User.id).where(User.username == username)).scalar():
        raise Conflict(f"Username '{username}' is taken")
    user = User(username=username, display_name=(display_name or username).strip()[:128], email=email,
                password_hash=hash_password(password), is_admin=is_admin)
    db.add(user)
    db.flush()
    audit.record(db, actor=actor, action="user.created", entity_type="user", entity_id=user.id,
                 summary=f"Created user {username}{' (admin)' if is_admin else ''}")
    return user


def _limits() -> tuple[int, int]:
    settings = get_settings()
    return settings.login_max_failures, settings.login_window_seconds


def _refuse_while_blocked(*checks: tuple[str, int]) -> None:
    """Refuse an attempt while one of the (key, limit) counters is full; the answer says when to try again."""
    _, window = _limits()
    wait = max((login_failures.retry_after(key, limit, window) for key, limit in checks), default=0)
    if wait:
        raise TooManyRequests(f"Too many failed sign-in attempts. Try again in {math.ceil(wait / 60)} minute(s).",
                              headers={"Retry-After": str(wait)})


def _login_failed(db: Session, user: User | None, name: str, client_ip: str | None) -> None:
    """Count a failed sign-in and record it (only for existing users: guessed names must not fill the audit trail)."""
    limit, window = _limits()
    count = login_failures.record(f"user:{name}", window)
    if client_ip:
        login_failures.record(f"ip:{client_ip}", window)
    if user is None:
        log.warning("Failed sign-in for unknown user %r from %r", name, client_ip)
        return
    audit.record(db, actor=None, actor_name=user.username, action="user.login_failed", entity_type="user",
                 entity_id=user.id, summary=f"Failed sign-in for {user.username}", details={"from": client_ip})
    if limit > 0 and count == limit:
        audit.record(db, actor=None, actor_name=user.username, action="user.login_blocked", entity_type="user",
                     entity_id=user.id, summary=f"Sign-in for {user.username} blocked after repeated failures",
                     details={"failures": count, "minutes": math.ceil(window / 60)})
    db.commit()  # the request fails, but the record must stay


def authenticate(db: Session, username: str, password: str, client_ip: str | None = None) -> User:
    name = (username or "").strip().lower()[:64]
    limit, _ = _limits()
    checks = [(f"user:{name}", limit)]
    if client_ip:
        checks.append((f"ip:{client_ip}", limit * 3))
    _refuse_while_blocked(*checks)
    user = db.execute(select(User).where(User.username == name)).scalar_one_or_none()
    if user is None or not user.is_active:
        burn_password_check(password or "")  # unknown users take as long as wrong passwords
        ok = False
    else:
        ok = verify_password(user.password_hash, password or "")
    if not ok:
        _login_failed(db, user, name, client_ip)
        # Same message for unknown user and wrong password.
        raise Unauthorized("Invalid username or password")
    assert user is not None
    login_failures.clear(f"user:{name}")
    user.last_login_at = utcnow()
    audit.record(db, actor=user, action="user.login", entity_type="user", entity_id=user.id,
                 summary=f"{user.username} signed in")
    return user


def change_password(db: Session, user: User, current: str, new: str) -> None:
    key = f"password:{user.id}"
    limit, window = _limits()
    _refuse_while_blocked((key, limit))  # a stolen session must not be able to guess the current password
    if not verify_password(user.password_hash, current or ""):
        login_failures.record(key, window)
        raise Unauthorized("Current password is incorrect")
    login_failures.clear(key)
    _check_password(new)
    user.password_hash = hash_password(new)
    audit.record(db, actor=user, action="user.password_changed", entity_type="user", entity_id=user.id,
                 summary=f"{user.username} changed the password")


def admin_update_user(db: Session, actor: User, user: User, *, display_name: str | None = None,
                      email: str | None = None, is_admin: bool | None = None, is_active: bool | None = None,
                      password: str | None = None) -> User:
    changes = []
    if display_name is not None:
        user.display_name = display_name.strip()[:128] or user.username
        changes.append("display_name")
    if email is not None:
        user.email = email or None
        changes.append("email")
    if is_admin is not None and is_admin != user.is_admin:
        if user.id == actor.id and not is_admin:
            raise ValidationFailed("You cannot remove your own administrator rights")
        user.is_admin = is_admin
        changes.append("is_admin")
    if is_active is not None and is_active != user.is_active:
        if user.id == actor.id and not is_active:
            raise ValidationFailed("You cannot deactivate yourself")
        user.is_active = is_active
        changes.append("is_active")
    if password:
        _check_password(password)
        user.password_hash = hash_password(password)
        changes.append("password")
    if changes:
        audit.record(db, actor=actor, action="user.updated", entity_type="user", entity_id=user.id,
                     summary=f"Updated user {user.username}: {', '.join(changes)}")
    return user


def get_user(db: Session, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise NotFound("User not found")
    return user


def create_token(db: Session, user: User, name: str, days: int | None = 365) -> tuple[ApiToken, str]:
    name = (name or "").strip()
    if not name:
        raise ValidationFailed("Token name is required")
    plain, prefix, digest = new_api_token()
    token = ApiToken(user_id=user.id, name=name[:128], prefix=prefix, token_hash=digest,
                     expires_at=datetime.now(UTC) + timedelta(days=days) if days else None)
    db.add(token)
    db.flush()
    audit.record(db, actor=user, action="token.created", entity_type="user", entity_id=user.id,
                 summary=f"{user.username} created API token '{token.name}' ({prefix}…)")
    return token, plain


def revoke_token(db: Session, user: User, token_id: uuid.UUID) -> None:
    token = db.get(ApiToken, token_id)
    if token is None or (token.user_id != user.id and not user.is_admin):
        raise NotFound("Token not found")
    token.revoked_at = utcnow()
    audit.record(db, actor=user, action="token.revoked", entity_type="user", entity_id=token.user_id,
                 summary=f"Revoked API token '{token.name}' ({token.prefix}…)")


def user_for_token(db: Session, plain: str) -> User | None:
    token = db.execute(select(ApiToken).where(ApiToken.token_hash == hash_api_token(plain))).scalar_one_or_none()
    if token is None or token.revoked_at is not None:
        return None
    if token.expires_at is not None and token.expires_at < datetime.now(UTC):
        return None
    user = db.get(User, token.user_id)
    if user is None or not user.is_active:
        return None
    if token.last_used_at is None or (utcnow() - token.last_used_at) > timedelta(minutes=5):
        token.last_used_at = utcnow()
        db.commit()
    return user


def ensure_bootstrap_admin(db: Session) -> None:
    """On an empty installation create the first administrator.

    The password comes from ALMLIGHT_ADMIN_PASSWORD or is generated and written to the log once.
    """
    if db.execute(select(func.count()).select_from(User)).scalar_one() > 0:
        return
    settings = get_settings()
    password = settings.admin_password or secrets.token_urlsafe(12)
    create_user(db, None, username=settings.admin_username, display_name="Administrator", password=password,
                is_admin=True)
    db.commit()
    if settings.admin_password:
        log.warning("Created administrator '%s' with the configured password", settings.admin_username)
    else:
        log.warning("Created administrator '%s' with generated password: %s  (change it after first login)",
                    settings.admin_username, password)
