"""Live co-editing sessions ("rooms"): one shared document per item, held by the server.

* Every browser editing an item's title/text connects with the standard Yjs WebSocket provider. Edits are CRDT
  updates: concurrent typing merges character by character, nothing is locked and nothing is lost.
* The server keeps the authoritative copy (pycrdt), relays updates and presence (cursors, names) between the
  participants, and enforces access: viewers and frozen items get a read-only connection.
* A session starts from the item's current text (identified by its content hash). Its state is saved as a
  draft every few seconds (crash safety) and committed as a **new item version** — through the normal item
  service, so history, audit trail, suspect links and webhooks behave as for any other edit — when a
  participant clicks *Save version*, when the last editor has left (after a short grace period), or after an
  idle period. The version records everybody who contributed.
* A change to the text from anywhere else (form, import, restore, merge) first saves the session, then restarts
  it from the new text; a workflow transition does the same and re-checks write access.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

import anyio
from pycrdt import Doc, XmlFragment, create_sync_message, create_update_message, handle_sync_message
from sqlalchemy import select

from almlight.core.config import get_settings
from almlight.core.db import session_factory, utcnow
from almlight.core.errors import DomainError
from almlight.core.richtext import content_hash
from almlight.modules.collab import protocol as p
from almlight.modules.collab.models import CollabDraft
from almlight.modules.collab.serialize import BODY, TITLE, body_html, title_text

log = logging.getLogger("almlight.collab")
CLOSE_RESET = 4001  # the text changed elsewhere (or access changed): reload and reconnect
CLOSE_UNAUTHORIZED = 4401
CLOSE_NOT_FOUND = 4404
CLOSE_STALE = 4409  # the client's start state is outdated: reload and reconnect
PALETTE = ("#e8590c", "#1971c2", "#2f9e44", "#c2255c", "#6741d9", "#0c8599", "#e67700", "#5c940d")


def user_color(user_id: str) -> str:
    return PALETTE[uuid.UUID(user_id).int % len(PALETTE)]


@dataclass(eq=False)
class Conn:
    ws: Any
    user_id: str
    user_name: str
    can_write: bool
    client_ids: set[int] = field(default_factory=set)
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=2000))
    writer: asyncio.Task | None = None

    def push(self, data: bytes) -> None:
        try:
            self.queue.put_nowait(data)
        except asyncio.QueueFull:  # a client that cannot keep up is dropped; it will reconnect and resync
            self.close_soon(1013)

    def close_soon(self, code: int, reason: str = "") -> None:
        with contextlib.suppress(asyncio.QueueFull):
            self.queue.put_nowait(("close", code, reason))

    async def run_writer(self) -> None:
        while True:
            msg = await self.queue.get()
            try:
                if isinstance(msg, tuple):
                    await self.ws.close(code=msg[1], reason=msg[2][:120])
                    return
                await self.ws.send_bytes(msg)
            except Exception:  # noqa: BLE001 — the connection is gone
                return


@dataclass
class ItemAccess:
    item_id: uuid.UUID
    project_id: uuid.UUID
    project_key: str
    item_key: str
    can_write: bool
    content_hash: str


class Room:
    def __init__(self, manager: RoomManager, access: ItemAccess, base_hash: str):
        self.manager = manager
        self.item_id = access.item_id
        self.project_id = access.project_id
        self.project_key = access.project_key
        self.item_key = access.item_key
        self.base_hash = base_hash
        self.doc = Doc()
        self.body = self.doc.get(BODY, type=XmlFragment)
        self.title = self.doc.get(TITLE, type=XmlFragment)
        self.conns: set[Conn] = set()
        self.awareness: dict[int, tuple[int, str]] = {}
        self.contributors: dict[str, int] = {}
        self.names: dict[str, str] = {}
        self.dirty = False
        self.draft_pending = False
        self.failed: str | None = None
        loop = asyncio.get_running_loop()
        self.last_update = loop.time()
        self.last_draft = loop.time()
        self.left_at = loop.time()
        self.lock = asyncio.Lock()
        self._origin: Conn | None = None
        self._pending: list[bytes] = []
        self._sub = self.doc.observe(self._on_update)
        self.timer = asyncio.create_task(self._timer())

    # -- document updates --

    def _on_update(self, event: Any) -> None:
        self._pending.append(event.update)

    def _flush_pending(self, origin: Conn | None) -> None:
        pending, self._pending = self._pending, []
        for update in pending:
            msg = create_update_message(update)
            for c in self.conns:
                if c is not origin:
                    c.push(msg)

    @property
    def writers(self) -> list[Conn]:
        return [c for c in self.conns if c.can_write]

    async def handle(self, conn: Conn, message: bytes) -> None:
        if not message:
            return
        kind = message[0]
        if kind == p.MSG_SYNC:
            sub = message[1] if len(message) > 1 else -1
            if sub == p.SYNC_STEP1:
                reply = handle_sync_message(message[1:], self.doc)
                if reply is not None:
                    conn.push(reply)
            elif sub in (p.SYNC_STEP2, p.SYNC_UPDATE):
                if not conn.can_write:
                    return  # read-only participants cannot change the shared document
                before = self.doc.get_state()
                handle_sync_message(message[1:], self.doc)
                self._flush_pending(conn)
                if self.doc.get_state() != before:
                    self.dirty = True
                    self.failed = None
                    self.draft_pending = True
                    self.last_update = asyncio.get_running_loop().time()
                    self.contributors[conn.user_id] = self.contributors.get(conn.user_id, 0) + 1
                    self.names[conn.user_id] = conn.user_name
        elif kind == p.MSG_AWARENESS:
            r = p.Reader(message[1:])
            entries = p.parse_awareness(r.var_bytes())
            user = {"id": conn.user_id, "name": conn.user_name, "color": user_color(conn.user_id),
                    "canWrite": conn.can_write}
            out = []
            for e in entries:
                conn.client_ids.add(e.client_id)
                state = p.stamp_user(e.state, user)
                if state == "null":
                    self.awareness.pop(e.client_id, None)
                else:
                    self.awareness[e.client_id] = (e.clock, state)
                out.append(p.AwarenessEntry(e.client_id, e.clock, state))
            msg = p.awareness_message(out)
            for c in self.conns:  # echo to everyone, including the sender (keeps the connection alive)
                c.push(msg)
        elif kind == p.MSG_QUERY_AWARENESS:
            conn.push(self.awareness_snapshot())

    def awareness_snapshot(self) -> bytes:
        return p.awareness_message([p.AwarenessEntry(cid, clock, state)
                                    for cid, (clock, state) in self.awareness.items()])

    def participants(self) -> list[dict[str, Any]]:
        seen: dict[str, dict[str, Any]] = {}
        for c in self.conns:
            entry = seen.setdefault(c.user_id, {"id": c.user_id, "name": c.user_name, "color": user_color(c.user_id),
                                                "can_write": False, "connections": 0})
            entry["can_write"] = entry["can_write"] or c.can_write
            entry["connections"] += 1
        return sorted(seen.values(), key=lambda x: x["name"])

    # -- membership --

    def join(self, conn: Conn) -> None:
        self.conns.add(conn)
        conn.writer = asyncio.create_task(conn.run_writer())
        conn.push(create_sync_message(self.doc))
        if self.awareness:
            conn.push(self.awareness_snapshot())

    def leave(self, conn: Conn) -> None:
        self.conns.discard(conn)
        if conn.writer:
            conn.writer.cancel()
        gone = [p.AwarenessEntry(cid, self.awareness[cid][0] + 1, "null") for cid in conn.client_ids
                if cid in self.awareness]
        for cid in conn.client_ids:
            self.awareness.pop(cid, None)
        if gone:
            msg = p.awareness_message(gone)
            for c in self.conns:
                c.push(msg)
        if not self.writers:
            self.left_at = asyncio.get_running_loop().time()

    def close_all(self, code: int, reason: str) -> None:
        for c in list(self.conns):
            c.close_soon(code, reason)

    # -- saving --

    async def _timer(self) -> None:
        settings = get_settings()
        loop = asyncio.get_running_loop()
        try:
            while True:
                await asyncio.sleep(0.25)
                now = loop.time()
                if self.draft_pending and now - self.last_draft >= settings.collab_draft_save_seconds:
                    self.draft_pending = False
                    self.last_draft = now
                    await self.save_draft()
                if self.dirty and not self.failed and (
                        now - self.last_update >= settings.collab_idle_seconds
                        or (not self.writers and now - self.left_at >= settings.collab_leave_grace_seconds)):
                    await self.commit(None, reason="auto")
                if not self.conns and (not self.dirty or self.failed) and \
                        now - self.left_at >= settings.collab_leave_grace_seconds:
                    self.manager.drop(self)
                    return
        except asyncio.CancelledError:
            return

    def state(self) -> tuple[str, str]:
        return title_text(self.title), body_html(self.body)

    async def save_draft(self) -> None:
        state = self.doc.get_update()
        data = (self.item_id, self.project_id, self.base_hash, state, dict(self.contributors))
        try:
            await anyio.to_thread.run_sync(_save_draft, *data)
        except Exception:  # noqa: BLE001
            log.exception("saving the co-editing draft of %s failed", self.item_key)

    async def commit(self, actor_id: str | None, *, reason: str) -> dict[str, Any]:
        """Save the shared text as a new item version (if it differs from the item's current text)."""
        async with self.lock:
            if not self.dirty and actor_id is None:
                return {"saved": False}
            title, html = self.state()
            contributors = dict(self.contributors)
            names = dict(self.names)
            try:
                result = await anyio.to_thread.run_sync(
                    _commit, self.item_id, self.base_hash, title, html, contributors, names, actor_id, reason)
            except DomainError as exc:
                self.failed = exc.message
                log.warning("co-editing session of %s could not be saved: %s", self.item_key, exc.message)
                return {"saved": False, "error": exc.message}
            except Exception as exc:  # noqa: BLE001
                self.failed = str(exc)
                log.exception("co-editing session of %s could not be saved", self.item_key)
                return {"saved": False, "error": "internal error"}
            self.base_hash = result["content_hash"]
            self.dirty = False
            self.draft_pending = False
            self.contributors.clear()
            return result


class RoomManager:
    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.rooms: dict[uuid.UUID, Room] = {}

    def bind(self) -> None:
        loop = asyncio.get_running_loop()
        if self.loop is not loop:  # a new event loop (tests): sessions of an old loop cannot continue
            self.loop = loop
            self.rooms = {}

    def has_room(self, item_id: uuid.UUID) -> bool:
        return item_id in self.rooms

    def join(self, access: ItemAccess, conn: Conn, base: str) -> Room | None:
        """Join the item's session; ``None`` if the client's start state is outdated."""
        self.bind()
        room = self.rooms.get(access.item_id)
        if room is None:
            if base and base != access.content_hash:
                return None
            room = Room(self, access, access.content_hash)
            self.rooms[access.item_id] = room
        elif base and base != room.base_hash:
            return None
        room.join(conn)
        return room

    def drop(self, room: Room) -> None:
        if self.rooms.get(room.item_id) is room:
            del self.rooms[room.item_id]
        room.timer.cancel()
        with contextlib.suppress(Exception):
            room._sub and room.doc.unobserve(room._sub)

    async def commit(self, item_id: uuid.UUID, actor_id: str | None, reason: str) -> dict[str, Any]:
        room = self.rooms.get(item_id)
        if room is None:
            return {"saved": False, "session": False}
        return await room.commit(actor_id, reason=reason)

    async def flush(self, item_id: uuid.UUID) -> None:
        room = self.rooms.get(item_id)
        if room is not None and room.dirty:
            await room.commit(None, reason="flush")

    async def reset(self, item_ids: set[uuid.UUID], reason: str, *, save_first: bool) -> None:
        """Close sessions so their clients reload. Request handlers save sessions *before* changing the text
        (``collab.router.flush``); a session that is still dirty here must not overwrite the newer text — unless
        only its write access changed (``save_first``)."""
        for iid in item_ids:
            room = self.rooms.get(iid)
            if room is None:
                continue
            if room.dirty and save_first:
                await room.commit(None, reason="flush")
            elif room.dirty:
                log.warning("co-editing session of %s discarded: its text was changed elsewhere", room.item_key)
            room.close_all(CLOSE_RESET, reason)
            self.drop(room)
            await anyio.to_thread.run_sync(_delete_draft, iid)

    def reset_threadsafe(self, item_ids: set[uuid.UUID], reason: str, *, save_first: bool = False) -> None:
        loop = self.loop
        if loop is None or loop.is_closed() or not any(i in self.rooms for i in item_ids):
            return
        asyncio.run_coroutine_threadsafe(self.reset(set(item_ids), reason, save_first=save_first), loop)

    def status(self, item_id: uuid.UUID) -> dict[str, Any]:
        room = self.rooms.get(item_id)
        if room is None:
            return {"active": False, "participants": [], "dirty": False}
        return {"active": True, "participants": room.participants(), "dirty": room.dirty,
                "base_hash": room.base_hash, "error": room.failed}


manager = RoomManager()


# --- database work (worker threads) ------------------------------------------------------------------------


def _save_draft(item_id: uuid.UUID, project_id: uuid.UUID, base_hash: str, state: bytes,
                contributors: dict[str, int]) -> None:
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    with session_factory()() as db:
        db.execute(pg_insert(CollabDraft).values(
            item_id=item_id, project_id=project_id, base_hash=base_hash, state=state, contributors=contributors,
            updated_at=utcnow(),
        ).on_conflict_do_update(index_elements=["item_id"], set_={
            "base_hash": base_hash, "state": state, "contributors": contributors, "updated_at": utcnow()}))
        db.commit()


def _delete_draft(item_id: uuid.UUID) -> None:
    with session_factory()() as db:
        db.execute(CollabDraft.__table__.delete().where(CollabDraft.item_id == item_id))
        db.commit()


def _commit(item_id: uuid.UUID, base_hash: str, title: str, html: str, contributors: dict[str, int],
            names: dict[str, str], actor_id: str | None, reason: str) -> dict[str, Any]:
    from almlight.modules.identity.models import User
    from almlight.modules.items import service as items_svc
    from almlight.modules.items.models import Item
    from almlight.modules.projects.models import Project

    with session_factory()() as db:
        item = db.execute(select(Item).where(Item.id == item_id).with_for_update()).scalar_one_or_none()
        if item is None or item.deleted_at is not None:
            raise DomainError("The item no longer exists")
        project = db.get(Project, item.project_id)
        new_title = title or item.title
        current = content_hash(item.title, item.description)
        result: dict[str, Any] = {"saved": False, "version": item.version_label, "content_hash": current}
        if content_hash(new_title, items_svc.richtext.normalize_input(html)) == current:
            db.execute(CollabDraft.__table__.delete().where(CollabDraft.item_id == item_id))
            db.commit()
            return result
        ranked = sorted(contributors, key=lambda u: -contributors[u])
        for u in ranked:
            if u not in names:
                user = db.get(User, uuid.UUID(u))
                names[u] = user.display_name if user else "?"
        author_id = actor_id or (ranked[0] if ranked else None)
        actor = db.get(User, uuid.UUID(author_id)) if author_id else None
        others = [names.get(u, "?") for u in ranked if u != author_id]
        note = "Live co-editing" + (f" with {', '.join(others)}" if others else "")
        if reason == "auto":
            note += " (saved when the session ended)"
        elif reason == "recovered":
            note += " (recovered after a server restart)"
        db.info["collab_source"] = item.id
        before = item.version_no
        items_svc.update_item(db, project, actor, item, items_svc.ContentChange(title=new_title, description=html),
                              change_note=note)
        if base_hash != current:
            log.warning("co-editing session of %s saved over a concurrent change", item.key)
        db.execute(CollabDraft.__table__.delete().where(CollabDraft.item_id == item_id))
        db.commit()
        return {"saved": item.version_no != before, "version": item.version_label,
                "content_hash": content_hash(item.title, item.description),
                "co_authors": [names.get(u, "?") for u in ranked]}


def recover_drafts() -> int:
    """At startup: save drafts of sessions that were interrupted by a restart."""
    with session_factory()() as db:
        drafts = db.execute(select(CollabDraft)).scalars().all()
    recovered = 0
    for d in drafts:
        doc = Doc()
        body, title = doc.get(BODY, type=XmlFragment), doc.get(TITLE, type=XmlFragment)
        try:
            doc.apply_update(d.state)
            res = _commit(d.item_id, d.base_hash, title_text(title), body_html(body), d.contributors,
                          {}, None, "recovered")
            recovered += int(res.get("saved", False))
        except Exception as exc:  # noqa: BLE001
            log.warning("could not recover the co-editing draft of item %s: %s", d.item_id, exc)
            _delete_draft(d.item_id)
    return recovered
