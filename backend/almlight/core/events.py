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
_TRACKED = ("live_events", "text_changed", "access_changed")


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
            for cb in list(self.subscribers.get(e.get("project_id") or "", ())):
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
    return {"live_events": len(info.get("live_events", [])), "text_changed": set(info.get("text_changed", set())),
            "access_changed": set(info.get("access_changed", set()))}


@event.listens_for(Session, "after_transaction_create")
def _txn_created(session: Session, transaction: Any) -> None:
    if transaction.nested:
        _marks(session).append((transaction, _snapshot(session)))


@event.listens_for(Session, "after_soft_rollback")
def _soft_rollback(session: Session, previous_transaction: Any) -> None:
    marks = _marks(session)
    for i in range(len(marks) - 1, -1, -1):
        if marks[i][0] is previous_transaction:
            snap = marks[i][1]
            del marks[i:]
            if "live_events" in session.info:
                del session.info["live_events"][snap["live_events"]:]
            session.info["text_changed"] = snap["text_changed"]
            session.info["access_changed"] = snap["access_changed"]
            return
    if not getattr(previous_transaction, "nested", False):
        for key in _TRACKED:
            session.info.pop(key, None)
        marks.clear()


@event.listens_for(Session, "after_transaction_end")
def _txn_ended(session: Session, transaction: Any) -> None:
    marks = _marks(session)
    if marks and marks[-1][0] is transaction:
        marks.pop()


@event.listens_for(Session, "after_commit")
def _after_commit(session: Session) -> None:
    collected = {key: session.info.pop(key, None) for key in _TRACKED}
    _marks(session).clear()
    if collected["live_events"]:
        bus.publish(collected["live_events"])
    for key, callback in _hooks:
        value = collected.get(key)
        if value:
            try:
                callback(value)
            except Exception:  # noqa: BLE001
                log.exception("post-commit hook %s failed", key)
