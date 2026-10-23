"""Live events: committed changes, pushed to connected browsers.

Services record events in the request's session (``audit.record`` does it for every audited change); they are
published only after the transaction commits, and events from rolled-back savepoints (dry runs) are dropped.
Other modules subscribe to post-commit hooks the same way (e.g. live editing sessions restart when an item's
text was changed elsewhere).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session

log = logging.getLogger("almlight.events")

# post-commit hooks: (session info key, callback receiving the collected values)
_hooks: list[tuple[str, Callable[[Any], None]]] = []
_LISTS = ("live_events", "notif_buffer")
_SETS = ("text_changed", "access_changed")
_TRACKED = _LISTS + _SETS


def on_commit(key: str, callback: Callable[[Any], None]) -> None:
    if (key, callback) not in _hooks:
        _hooks.append((key, callback))


class Bus:
    """Fan-out of events to subscribers (live WebSocket connections) on the server's event loop."""

    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.subscribers: dict[str, set[Callable[[dict[str, Any]], None]]] = {}

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        if self.loop is not loop:
            self.loop = loop
            self.subscribers = {}

    def subscribe(self, project_id: str, callback: Callable[[dict[str, Any]], None]) -> None:
        self.subscribers.setdefault(project_id, set()).add(callback)

    def unsubscribe(self, project_id: str, callback: Callable[[dict[str, Any]], None]) -> None:
        subs = self.subscribers.get(project_id)
        if subs:
            subs.discard(callback)
            if not subs:
                self.subscribers.pop(project_id, None)

    def publish(self, events: list[dict[str, Any]]) -> None:
        """Thread-safe: may be called from worker threads (synchronous request handlers)."""
        loop = self.loop
        if loop is None or loop.is_closed():
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            self._dispatch(events)
        else:
            loop.call_soon_threadsafe(self._dispatch, events)

    def _dispatch(self, events: list[dict[str, Any]]) -> None:
        for e in events:
            channel = f"user:{e['user_id']}" if e.get("type") == "notification" else e.get("project_id") or ""
            for cb in list(self.subscribers.get(channel, ())):
                try:
                    cb(e)
                except Exception:  # noqa: BLE001 — one broken subscriber must not stop the others
                    log.exception("live event subscriber failed")


bus = Bus()


def record(db: Session, event_: dict[str, Any]) -> None:
    db.info.setdefault("live_events", []).append(event_)


def _marks(session: Session) -> list[tuple[Any, dict[str, Any]]]:
    return session.info.setdefault("_live_marks", [])


def _snapshot(session: Session) -> dict[str, Any]:
    info = session.info
    return {**{k: len(info.get(k, [])) for k in _LISTS}, **{k: set(info.get(k, set())) for k in _SETS}}


@event.listens_for(Session, "after_transaction_create")
def _txn_created(session: Session, transaction: Any) -> None:
    if transaction.nested:
        _marks(session).append((transaction, _snapshot(session)))


@event.listens_for(Session, "after_soft_rollback")
def _soft_rollback(session: Session, previous_transaction: Any) -> None:
    # SQLAlchemy ends a savepoint (after_transaction_end) before reporting its rollback, so look in both places.
    ended = session.info.get("_live_ended", [])
    snap = None
    for i, (t, s) in enumerate(ended):
        if t is previous_transaction:
            snap = s
            del ended[i]
            break
    if snap is None:
        marks = _marks(session)
        for i in range(len(marks) - 1, -1, -1):
            if marks[i][0] is previous_transaction:
                snap = marks[i][1]
                del marks[i:]
                break
    if snap is not None:
        for k in _LISTS:
            if k in session.info:
                del session.info[k][snap[k]:]
        for k in _SETS:
            session.info[k] = snap[k]
        return
    if not getattr(previous_transaction, "nested", False):
        for key in _TRACKED:
            session.info.pop(key, None)
        _marks(session).clear()
        session.info.pop("_live_ended", None)


@event.listens_for(Session, "after_transaction_end")
def _txn_ended(session: Session, transaction: Any) -> None:
    marks = _marks(session)
    if marks and marks[-1][0] is transaction:
        # keep the snapshot until we know whether the savepoint was committed or rolled back
        session.info.setdefault("_live_ended", []).append(marks.pop())
    elif not transaction.nested:
        session.info.pop("_live_ended", None)


@event.listens_for(Session, "after_commit")
def _after_commit(session: Session) -> None:
    if session.in_nested_transaction():
        return  # SQLAlchemy reports savepoint commits here too; publish only when the transaction really commits
    collected = {key: session.info.pop(key, None) for key in _TRACKED}
    _marks(session).clear()
    session.info.pop("_live_ended", None)
    if collected["live_events"]:
        bus.publish(collected["live_events"])
    for key, callback in _hooks:
        value = collected.get(key)
        if value:
            try:
                callback(value)
            except Exception:  # noqa: BLE001
                log.exception("post-commit hook %s failed", key)
