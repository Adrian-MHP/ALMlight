"""Live co-editing endpoints: the Yjs WebSocket of an item and its session status / explicit save."""

from __future__ import annotations

import contextlib
import uuid
from typing import Any

import anyio
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from almlight.core.db import get_db, session_factory
from almlight.core.deps import current_user
from almlight.core.richtext import content_hash
from almlight.core.security import API_TOKEN_PREFIX, SESSION_COOKIE, decode_session_token
from almlight.modules.collab import rooms
from almlight.modules.collab.rooms import (
    CLOSE_NOT_FOUND,
    CLOSE_STALE,
    CLOSE_UNAUTHORIZED,
    Conn,
    ItemAccess,
    manager,
)
from almlight.modules.identity.models import User
from almlight.modules.items import service as items_svc
from almlight.modules.items.lifecycle import is_frozen
from almlight.modules.items.models import Item
from almlight.modules.projects.access import get_project, project_role
from almlight.modules.projects.metamodel import ROLE_RANK
from almlight.modules.projects.models import Project

router = APIRouter(tags=["live editing"])
MAX_MESSAGE = 5 * 1024 * 1024


def ws_user(ws: WebSocket, token: str | None) -> tuple[str, str] | None:
    """(user id, display name) from the session cookie or a ``token`` query parameter (session or API token)."""
    from almlight.modules.identity.service import user_for_token

    with session_factory()() as db:
        raw = token or ws.cookies.get(SESSION_COOKIE)
        if not raw:
            return None
        if raw.startswith(API_TOKEN_PREFIX):
            user = user_for_token(db, raw)
        else:
            uid = decode_session_token(raw)
            try:
                user = db.get(User, uuid.UUID(uid)) if uid else None
            except ValueError:
                user = None
        if user is None or not user.is_active:
            return None
        return str(user.id), user.display_name


def same_origin(ws: WebSocket) -> bool:
    """Browsers send the page's origin: refuse cross-site WebSocket connections (cookies would be sent along)."""
    from almlight.core.config import get_settings

    origin = ws.headers.get("origin")
    if not origin:
        return True  # not a browser
    hosts = {ws.headers.get("host", "")}
    forwarded = ws.headers.get("x-forwarded-host")
    if forwarded:  # behind a reverse proxy that rewrites Host
        hosts.add(forwarded.split(",")[0].strip())
    allowed = {f"{scheme}://{h}" for h in hosts if h for scheme in ("http", "https")} | set(get_settings().cors_origins)
    return origin in allowed


def item_access(item_id: str, user_id: str) -> ItemAccess | None:
    with session_factory()() as db:
        try:
            item = db.get(Item, uuid.UUID(item_id))
        except ValueError:
            return None
        if item is None or item.deleted_at is not None:
            return None
        project = db.get(Project, item.project_id)
        user = db.get(User, uuid.UUID(user_id))
        role = project_role(db, project, user)
        if role is None:
            return None
        can_write = ROLE_RANK[role] >= ROLE_RANK["contributor"] and not is_frozen(project, item)
        return ItemAccess(item.id, project.id, project.key, item.key, can_write,
                          content_hash(item.title, item.description))


@router.websocket("/collab/items/{item_id}")
async def collab_socket(ws: WebSocket, item_id: str, base: str = "", token: str | None = None) -> None:
    await ws.accept()
    if not same_origin(ws):
        await ws.close(code=CLOSE_UNAUTHORIZED, reason="cross-site connection refused")
        return
    who = await run_in_threadpool(ws_user, ws, token)
    if who is None:
        await ws.close(code=CLOSE_UNAUTHORIZED, reason="authentication required")
        return
    access = await run_in_threadpool(item_access, item_id, who[0])
    if access is None:
        await ws.close(code=CLOSE_NOT_FOUND, reason="item not found")
        return
    conn = Conn(ws=ws, user_id=who[0], user_name=who[1], can_write=access.can_write)
    room = manager.join(access, conn, base)
    if room is None:
        await ws.close(code=CLOSE_STALE, reason="the text changed - reload")
        return
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            data = msg.get("bytes")
            if data is None or len(data) > MAX_MESSAGE:
                continue
            try:
                await room.handle(conn, data)
            except (ValueError, IndexError):
                continue  # malformed message
    except WebSocketDisconnect:
        pass
    finally:
        room.leave(conn)


@router.get("/projects/{project_key}/items/{item_key}/collab", summary="Live editing session of an item")
def session_status(project_key: str, item_key: str, user: User = Depends(current_user),
                   db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    item = items_svc.get_item(db, project, item_key)
    return {"item": item.key, "content_hash": content_hash(item.title, item.description), **manager.status(item.id)}


@router.post("/projects/{project_key}/items/{item_key}/collab/save",
             summary="Save the live editing session as a new item version now")
def save_session(project_key: str, item_key: str, user: User = Depends(current_user),
                 db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user, "contributor")
    item = items_svc.get_item(db, project, item_key)
    if not manager.has_room(item.id):
        return {"saved": False, "session": False, "version": item.version_label}
    return anyio.from_thread.run(manager.commit, item.id, str(user.id), "explicit")


def flush(item_id: uuid.UUID) -> None:
    """Save a live session of the item before something else changes it (call from request handlers)."""
    if not manager.has_room(item_id):
        return
    with contextlib.suppress(RuntimeError):  # not in a server worker thread (scripts): nothing to save
        anyio.from_thread.run(manager.flush, item_id)


def flush_item(db: Session, item: Item) -> None:
    """``flush`` and reload the item in the caller's session."""
    if manager.has_room(item.id):
        flush(item.id)
        db.refresh(item)


def flush_project(project_id: uuid.UUID) -> None:
    for room in list(manager.rooms.values()):
        if room.project_id == project_id:
            flush(room.item_id)


def install() -> None:
    """Restart sessions whose text or access changed elsewhere (after the change is committed)."""
    from almlight.core.events import on_commit

    on_commit("text_changed", lambda ids: manager.reset_threadsafe(set(ids), "the text was changed elsewhere"))
    on_commit("access_changed", lambda ids: manager.reset_threadsafe(set(ids), "the lifecycle state changed",
                                                                     save_first=True))


__all__ = ["flush", "flush_project", "install", "router", "rooms"]
