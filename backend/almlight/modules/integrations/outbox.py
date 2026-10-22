"""Transactional outbox: domain events are stored with the change and delivered asynchronously."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from almlight.modules.audit.service import jsonable
from almlight.modules.integrations.models import OutboxEvent


def emit(db: Session, event: str, project_id: uuid.UUID | None, payload: dict[str, Any]) -> None:
    db.add(OutboxEvent(event=event, project_id=project_id, payload=jsonable(payload)))
