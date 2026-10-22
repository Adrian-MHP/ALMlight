"""Live channel: one WebSocket per browser tab.

* **Changes** — every committed change in a subscribed project (from the audit trail) is pushed, so open pages
  refresh themselves and documents show who saved what.
* **Presence** — who is viewing which document or item and who is editing which block (the collaboration
  notifications of enterprise live documents), updated instantly for everybody in the project.

Client messages: ``{"type": "subscribe", "project": "KEY"}``, ``{"type": "presence", "project": "KEY", "doc":
"SPEC-1" | null, "item": "SYS-1" | null, "editing": "SYS-2" | null}``, ``{"type": "ping"}``.
Server messages: ``change`` (an audit event), ``presence`` (``project`` and ``users``), ``pong``, ``error``.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from almlight.core.db import session_factory
from almlight.core.events import bus
from almlight.modules.collab.rooms import CLOSE_UNAUTHORIZED, user_color
from almlight.modules.collab.router import same_origin, ws_user
from almlight.modules.identity.models import User
from almlight.modules.projects.access import project_role
from almlight.modules.projects.models import Project

router = APIRouter(tags=["live"])
_ids = itertools.count(1)


class LiveConn:
    def __init__(self, ws: WebSocket, user_id: str, name: str):
        self.id = next(_ids)
        self.ws, self.user_id, self.name = ws, user_id, name
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self.projects: dict[str, str] = {}  # project id -> key
        self.writer = asyncio.create_task(self._write())

    def push(self, msg: dict[str, Any]) -> None:
        with contextlib.suppress(asyncio.QueueFull):
            self.queue.put_nowait(msg)

    async def _write(self) -> None:
        while True:
            msg = await self.queue.get()
            try:
                await self.ws.send_text(json.dumps(msg, separators=(",", ":")))
            except Exception:  # noqa: BLE001
                return

    def on_event(self, event: dict[str, Any]) -> None:
        key = self.projects.get(event.get("project_id") or "")
        if key:
            self.push({**event, "project": key})


class Hub:
    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.presence: dict[str, dict[int, dict[str, Any]]] = {}  # project id -> conn id -> entry
        self.members: dict[str, set[LiveConn]] = {}

    def bind(self) -> None:
        loop = asyncio.get_running_loop()
        if self.loop is not loop:
            self.loop, self.presence, self.members = loop, {}, {}
        bus.bind(loop)

    def users(self, project_id: str) -> list[dict[str, Any]]:
        return sorted(self.presence.get(project_id, {}).values(), key=lambda e: (e["name"], e["conn"]))

    def broadcast(self, project_id: str, key: str) -> None:
        msg = {"type": "presence", "project": key, "users": self.users(project_id)}
        for c in list(self.members.get(project_id, ())):
            c.push(msg)

    def join(self, conn: LiveConn, project_id: str, key: str) -> None:
        conn.projects[project_id] = key
        self.members.setdefault(project_id, set()).add(conn)
        bus.subscribe(project_id, conn.on_event)
        conn.push({"type": "presence", "project": key, "users": self.users(project_id)})

    def set_presence(self, conn: LiveConn, project_id: str, data: dict[str, Any]) -> None:
        entries = self.presence.setdefault(project_id, {})
        old = entries.get(conn.id)
        entry = {"conn": conn.id, "user_id": conn.user_id, "name": conn.name, "color": user_color(conn.user_id),
                 "doc": _key(data.get("doc")), "item": _key(data.get("item")), "editing": _key(data.get("editing")),
                 "since": old["since"] if old and old.get("doc") == _key(data.get("doc")) else
                 datetime.now(UTC).isoformat()}
        entries[conn.id] = entry
        self.broadcast(project_id, conn.projects[project_id])

    def leave(self, conn: LiveConn) -> None:
        for pid, key in list(conn.projects.items()):
            bus.unsubscribe(pid, conn.on_event)
            self.members.get(pid, set()).discard(conn)
            if self.presence.get(pid, {}).pop(conn.id, None) is not None:
                self.broadcast(pid, key)
        conn.writer.cancel()


hub = Hub()


def _key(value: Any) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 40:
        return None
    return value.upper()


def _project_for(user_id: str, key: str) -> tuple[str, str] | None:
    import uuid

    with session_factory()() as db:
        project = db.execute(select(Project).where(Project.key == key.upper())).scalar_one_or_none()
        user = db.get(User, uuid.UUID(user_id))
        if project is None or project_role(db, project, user) is None:
            return None
        return str(project.id), project.key


@router.websocket("/live")
async def live_socket(ws: WebSocket, token: str | None = None) -> None:
    await ws.accept()
    if not same_origin(ws):
        await ws.close(code=CLOSE_UNAUTHORIZED, reason="cross-site connection refused")
        return
    who = await run_in_threadpool(ws_user, ws, token)
    if who is None:
        await ws.close(code=CLOSE_UNAUTHORIZED, reason="authentication required")
        return
    hub.bind()
    conn = LiveConn(ws, who[0], who[1])
    by_key: dict[str, str] = {}
    try:
        while True:
            raw = await ws.receive_text()
            if len(raw) > 10_000:
                continue
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(msg, dict):
                continue
            kind = msg.get("type")
            if kind == "ping":
                conn.push({"type": "pong"})
            elif kind in ("subscribe", "presence") and isinstance(msg.get("project"), str):
                key = msg["project"].upper()
                if key not in by_key:
                    found = await run_in_threadpool(_project_for, conn.user_id, key)
                    if found is None:
                        conn.push({"type": "error", "message": f"Project {key} not found"})
                        continue
                    by_key[key] = found[0]
                    hub.join(conn, found[0], found[1])
                if kind == "presence":
                    hub.set_presence(conn, by_key[key], msg)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        hub.leave(conn)
