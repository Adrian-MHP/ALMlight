"""REST API of the AI assistant: conversations, questions and the confirmation of proposed changes."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from almlight.core.db import get_db, session_factory
from almlight.core.deps import current_user
from almlight.core.schemas import Ok
from almlight.modules.assistant import llm, service
from almlight.modules.assistant.tools import TOOLS
from almlight.modules.identity.models import User
from almlight.modules.projects.access import get_project, has_role

log = logging.getLogger("almlight.assistant")
router = APIRouter(prefix="/projects/{project_key}/assistant", tags=["assistant"])


class AskIn(BaseModel):
    text: str = Field(max_length=8000, description="The question or instruction")


class ThreadIn(BaseModel):
    model: str | None = Field(default=None, description="Language model for this conversation")


class ConfirmIn(BaseModel):
    approve: bool = Field(description="true applies the proposed changes, false discards them")


@router.get("", summary="Whether the assistant is available, and the person's conversations")
def overview(project_key: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    may_write = has_role(db, project, user, "contributor")
    return {"enabled": llm.enabled(), "model": llm.model_name() if llm.enabled() else None,
            "models": [{"id": m.id, "label": m.label, "provider": m.provider, "local": m.local, "note": m.note}
                       for m in llm.models()],
            "can_change": may_write,
            "tools": [{"name": t.name, "writes": t.writes} for t in TOOLS if may_write or not t.writes],
            "threads": service.threads(db, project, user)}


@router.post("/threads", status_code=201, summary="Start a conversation")
def start(project_key: str, body: ThreadIn | None = None, user: User = Depends(current_user),
          db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    thread = service.create_thread(db, project, user, body.model if body else None)
    db.commit()
    return service.state(db, thread)


@router.get("/threads/{thread_id}", summary="A conversation with its messages")
def read(project_key: str, thread_id: uuid.UUID, user: User = Depends(current_user),
         db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    return service.state(db, service._thread(db, project, user, thread_id))


@router.post("/threads/{thread_id}/messages", summary="Ask the assistant (runs its tools)")
def ask(project_key: str, thread_id: uuid.UUID, body: AskIn, user: User = Depends(current_user),
        db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    thread = service._thread(db, project, user, thread_id)
    result = service.ask(db, project, user, thread, body.text)
    db.commit()
    return result


@router.post("/threads/{thread_id}/confirm", summary="Apply or discard the changes the assistant proposed")
def confirm(project_key: str, thread_id: uuid.UUID, body: ConfirmIn, user: User = Depends(current_user),
            db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    thread = service._thread(db, project, user, thread_id)
    result = service.confirm(db, project, user, thread, body.approve)
    db.commit()
    return result


def _events(project_key: str, thread_id: uuid.UUID, user_id: uuid.UUID, work: str,
            approve: bool = False, text: str = "") -> Iterator[str]:
    """Run the conversation in its own session and report what happens as server-sent events.

    A streaming response outlives the request's session, so this opens its own and closes it at the end.
    """
    import json as _json

    from almlight.core.errors import DomainError
    from almlight.modules.identity.models import User as UserModel

    def line(event: dict[str, Any]) -> str:
        return f"data: {_json.dumps(event, ensure_ascii=False, default=str)}\n\n"

    with session_factory()() as db:
        try:
            user = db.get(UserModel, user_id)
            project = get_project(db, project_key, user)
            thread = service._thread(db, project, user, thread_id)
            steps = (service.ask_stream(db, project, user, thread, text) if work == "ask"
                     else service.confirm_stream(db, project, user, thread, approve))
            for event in steps:
                yield line(event)
            db.commit()
            yield line({"type": "done", **service.state(db, thread)})
        except DomainError as exc:
            db.rollback()
            yield line({"type": "error", "message": exc.message})
        except Exception:  # noqa: BLE001 — the browser must learn that it is over
            db.rollback()
            log.exception("assistant stream failed")
            yield line({"type": "error", "message": "The assistant stopped unexpectedly"})


def _stream(generator: Iterator[str]) -> StreamingResponse:
    return StreamingResponse(generator, media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.post("/threads/{thread_id}/stream", summary="Ask the assistant and follow the answer while it is written")
def ask_streaming(project_key: str, thread_id: uuid.UUID, body: AskIn, user: User = Depends(current_user),
                  db: Session = Depends(get_db)) -> StreamingResponse:
    project = get_project(db, project_key, user)  # refuse early, before the stream starts
    service._thread(db, project, user, thread_id)
    return _stream(_events(project_key, thread_id, user.id, "ask", text=body.text))


@router.post("/threads/{thread_id}/confirm-stream",
             summary="Apply or discard the proposals and follow what the assistant says next")
def confirm_streaming(project_key: str, thread_id: uuid.UUID, body: ConfirmIn, user: User = Depends(current_user),
                      db: Session = Depends(get_db)) -> StreamingResponse:
    project = get_project(db, project_key, user)
    service._thread(db, project, user, thread_id)
    return _stream(_events(project_key, thread_id, user.id, "confirm", approve=body.approve))


@router.delete("/threads/{thread_id}", response_model=Ok, summary="Delete a conversation")
def remove(project_key: str, thread_id: uuid.UUID, user: User = Depends(current_user),
           db: Session = Depends(get_db)) -> Ok:
    project = get_project(db, project_key, user)
    service.delete_thread(db, project, user, thread_id)
    db.commit()
    return Ok()
