"""Single sign-on with OpenID Connect (authorization code flow with PKCE).

The provider is configured with ``ALMLIGHT_OIDC_ISSUER``, ``…_CLIENT_ID`` and ``…_CLIENT_SECRET``; its endpoints and
keys come from ``/.well-known/openid-configuration``. Users are created on first sign-in (just-in-time) or matched by
username; members of ``ALMLIGHT_OIDC_ADMIN_GROUP`` become administrators. Project roles stay in the application.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from typing import Any

import httpx
import jwt
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from almlight.core.config import get_settings
from almlight.core.db import get_db, utcnow
from almlight.core.errors import Forbidden, NotFound, Unauthorized
from almlight.core.security import SESSION_COOKIE, create_session_token, hash_password
from almlight.modules.audit import service as audit
from almlight.modules.identity.models import User

router = APIRouter(prefix="/auth/oidc", tags=["auth"])
STATE_COOKIE = "almlight_oidc"
_cache: dict[str, tuple[float, Any]] = {}


def enabled() -> bool:
    s = get_settings()
    return bool(s.oidc_issuer and s.oidc_client_id)


def _http_get(url: str) -> dict[str, Any]:
    with httpx.Client(timeout=10.0) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.json()


def _http_post(url: str, data: dict[str, str], auth: tuple[str, str] | None) -> dict[str, Any]:
    with httpx.Client(timeout=10.0) as c:
        r = c.post(url, data=data, auth=auth)
        if r.status_code >= 400:
            raise Unauthorized(f"The identity provider refused the sign-in ({r.status_code})")
        return r.json()


def _cached(key: str, loader, ttl: float = 3600) -> Any:
    hit = _cache.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    value = loader()
    _cache[key] = (time.monotonic() + ttl, value)
    return value


def discovery() -> dict[str, Any]:
    issuer = get_settings().oidc_issuer.rstrip("/")
    return _cached(f"disc:{issuer}", lambda: _http_get(f"{issuer}/.well-known/openid-configuration"))


def _signing_key(kid: str | None, alg: str) -> Any:
    jwks_uri = discovery()["jwks_uri"]

    def find(force: bool = False) -> Any:
        if force:
            _cache.pop(f"jwks:{jwks_uri}", None)
        keys = _cached(f"jwks:{jwks_uri}", lambda: _http_get(jwks_uri))["keys"]
        for k in keys:
            if kid is None or k.get("kid") == kid:
                return jwt.PyJWK.from_dict(k, algorithm=alg).key
        return None

    key = find() or find(force=True)  # keys rotate: reload once
    if key is None:
        raise Unauthorized("Unknown signing key of the identity provider")
    return key


def _redirect_uri(request: Request) -> str:
    base = get_settings().public_url
    if base:
        return base.rstrip("/") + "/api/v1/auth/oidc/callback"
    return str(request.url_for("oidc_callback"))


def _sign(payload: dict[str, Any]) -> str:
    return jwt.encode({**payload, "exp": int(time.time()) + 600, "typ": "oidc_state"},
                      get_settings().resolved_secret_key(), algorithm="HS256")


@router.get("/config", summary="Whether single sign-on is configured (for the sign-in page)")
def config() -> dict[str, Any]:
    return {"enabled": enabled(), "label": get_settings().oidc_label}


@router.get("/login", summary="Start single sign-on")
def login(request: Request, next: str = "/") -> RedirectResponse:  # noqa: A002 — query parameter name
    if not enabled():
        raise NotFound("Single sign-on is not configured")
    s = get_settings()
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    safe_next = next if next.startswith("/") and not next.startswith("//") else "/"
    params = {"response_type": "code", "client_id": s.oidc_client_id, "redirect_uri": _redirect_uri(request),
              "scope": s.oidc_scopes, "state": state, "nonce": nonce, "code_challenge": challenge,
              "code_challenge_method": "S256"}
    url = str(httpx.URL(discovery()["authorization_endpoint"], params=params))
    resp = RedirectResponse(url, status_code=302)
    resp.set_cookie(STATE_COOKIE, _sign({"state": state, "nonce": nonce, "verifier": verifier, "next": safe_next}),
                    httponly=True, samesite="lax", secure=s.cookie_secure, max_age=600, path="/api/v1/auth/oidc")
    return resp


@router.get("/callback", name="oidc_callback", summary="Single sign-on callback")
def callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None,
             db: Session = Depends(get_db)) -> RedirectResponse:
    if error:
        raise Unauthorized(f"Sign-in was not completed: {error}")
    s = get_settings()
    try:
        saved = jwt.decode(request.cookies.get(STATE_COOKIE, ""), s.resolved_secret_key(), algorithms=["HS256"])
    except jwt.PyJWTError:
        raise Unauthorized("The sign-in took too long or was started elsewhere — please try again") from None
    if not code or not state or not secrets.compare_digest(state, saved.get("state", "")):
        raise Unauthorized("Invalid sign-in response")
    meta = discovery()
    tokens = _http_post(meta["token_endpoint"], {
        "grant_type": "authorization_code", "code": code, "redirect_uri": _redirect_uri(request),
        "client_id": s.oidc_client_id, "code_verifier": saved["verifier"],
    }, auth=(s.oidc_client_id, s.oidc_client_secret) if s.oidc_client_secret else None)
    raw = tokens.get("id_token")
    if not raw:
        raise Unauthorized("The identity provider returned no ID token")
    header = jwt.get_unverified_header(raw)
    alg = header.get("alg", "RS256")
    if alg not in ("RS256", "RS384", "RS512", "ES256", "ES384", "PS256"):
        raise Unauthorized(f"Unsupported token algorithm {alg}")
    try:
        claims = jwt.decode(raw, _signing_key(header.get("kid"), alg), algorithms=[alg], audience=s.oidc_client_id,
                            issuer=meta.get("issuer", s.oidc_issuer))
    except jwt.PyJWTError as exc:
        raise Unauthorized(f"Invalid ID token: {exc}") from None
    if claims.get("nonce") != saved.get("nonce"):
        raise Unauthorized("Invalid ID token (nonce)")
    user = provision(db, claims)
    resp = RedirectResponse(saved.get("next") or "/", status_code=302)
    resp.delete_cookie(STATE_COOKIE, path="/api/v1/auth/oidc")
    resp.set_cookie(SESSION_COOKIE, create_session_token(str(user.id)), httponly=True, samesite="lax",
                    secure=s.cookie_secure, max_age=s.session_hours * 3600, path="/")
    return resp


def provision(db: Session, claims: dict[str, Any]) -> User:
    s = get_settings()
    username = str(claims.get(s.oidc_username_claim) or claims.get("email") or claims.get("sub") or "").strip()
    username = username.split("@")[0] if "@" in username and s.oidc_username_claim == "email" else username
    if not username:
        raise Unauthorized("The ID token has no username")
    username = username[:64]
    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    groups = claims.get("groups") or []
    is_admin = bool(s.oidc_admin_group and s.oidc_admin_group in groups)
    name = str(claims.get("name") or username)[:128]
    if user is None:
        if not s.oidc_allow_signup:
            raise Forbidden("Your account is not set up in this application — ask an administrator")
        user = User(username=username, display_name=name, email=claims.get("email"),
                    password_hash=hash_password(secrets.token_urlsafe(32)), is_admin=is_admin, auth_provider="oidc")
        db.add(user)
        db.flush()
        audit.record(db, actor=user, action="user.created", entity_type="user", entity_id=user.id,
                     summary=f"User {username} created by single sign-on", details={"provider": s.oidc_issuer})
    elif not user.is_active:
        raise Forbidden("Your account is deactivated")
    else:
        user.display_name = name or user.display_name
        user.email = claims.get("email") or user.email
        if s.oidc_admin_group:
            user.is_admin = is_admin or (user.is_admin and user.auth_provider == "local")
    user.last_login_at = utcnow()
    db.commit()
    return user


__all__ = ["router", "enabled", "provision"]
