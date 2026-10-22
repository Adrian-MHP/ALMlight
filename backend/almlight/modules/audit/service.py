from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from almlight.core import events
from almlight.core.db import utcnow
from almlight.modules.audit.models import AuditEntry
from almlight.modules.identity.models import User

GENESIS_HASH = "0" * 64
# Serialises audit writers so the hash chain stays linear. Held until the transaction ends.
_AUDIT_LOCK_KEY = 7_311_000_001


def jsonable(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(v) for v in value]
    return value


def _entry_hash(e: AuditEntry) -> str:
    canonical = json.dumps(
        {
            "ts": e.ts.astimezone(UTC).isoformat(),
            "actor_id": str(e.actor_id) if e.actor_id else None,
            "actor_name": e.actor_name,
            "action": e.action,
            "project_id": str(e.project_id) if e.project_id else None,
            "entity_type": e.entity_type,
            "entity_id": e.entity_id,
            "summary": e.summary,
            "details": e.details,
            "related_ids": sorted(str(r) for r in e.related_ids),
            "prev_hash": e.prev_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def record(
    db: Session,
    *,
    actor: User | None,
    action: str,
    entity_type: str,
    entity_id: Any,
    summary: str,
    project_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
    related_ids: list[uuid.UUID] | None = None,
    actor_name: str | None = None,
) -> AuditEntry:
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _AUDIT_LOCK_KEY})
    prev = db.execute(select(AuditEntry.hash).order_by(AuditEntry.id.desc()).limit(1)).scalar()
    entry = AuditEntry(
        ts=utcnow(),
        actor_id=actor.id if actor else None,
        actor_name=actor_name or (actor.username if actor else "system"),
        action=action,
        project_id=project_id,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        summary=summary,
        details=jsonable(details or {}),
        related_ids=list(dict.fromkeys(related_ids or [])),
        prev_hash=prev or GENESIS_HASH,
    )
    entry.hash = _entry_hash(entry)
    db.add(entry)
    db.flush()
    events.record(db, {"type": "change", "id": entry.id, "project_id": str(project_id) if project_id else None,
                       "action": action, "entity_type": entity_type, "entity_id": entry.entity_id,
                       "summary": summary, "actor": entry.actor_name, "actor_id": str(actor.id) if actor else None,
                       "related_ids": [str(r) for r in entry.related_ids], "ts": entry.ts.isoformat()})
    return entry


def verify_chain(db: Session) -> dict[str, Any]:
    """Recompute every hash in order. Returns the first broken entry, if any."""
    prev = GENESIS_HASH
    checked = 0
    for entry in db.execute(select(AuditEntry).order_by(AuditEntry.id)).scalars():
        checked += 1
        if entry.prev_hash != prev or _entry_hash(entry) != entry.hash:
            return {"ok": False, "checked": checked, "first_broken_id": entry.id}
        prev = entry.hash
    return {"ok": True, "checked": checked, "first_broken_id": None}
