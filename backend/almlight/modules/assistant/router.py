"""REST API of the AI assistant: conversations, questions and the confirmation of proposed changes."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from almlight.core.db import get_db
from almlight.core.deps import current_user
from almlight.core.schemas import Ok
from almlight.modules.assistant import llm, service
from almlight.modules.assistant.tools import TOOLS
from almlight.modules.identity.models import User
from almlight.modules.projects.access import get_project, has_role

router = APIRouter(prefix="/projects/{project_key}/assistant", tags=["assistant"])


class AskIn(BaseModel):
    text: str = Field(max_length=8000, description="The question or instruction")


class ConfirmIn(BaseModel):
    approve: bool = Field(description="true applies the proposed changes, false discards them")


@router.get("", summary="Whether the assistant is available, and the person's conversations")
def overview(project_key: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    may_write = has_role(db, project, user, "contributor")
    return {"enabled": llm.enabled(), "model": llm.model_name() if llm.enabled() else None,
            "can_change": may_write,
            "tools": [{"name": t.name, "writes": t.writes} for t in TOOLS if may_write or not t.writes],
            "threads": service.threads(db, project, user)}


@router.post("/threads", status_code=201, summary="Start a conversation")
def start(project_key: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = get_project(db, project_key, user)
    thread = service.create_thread(db, project, user)
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


@router.delete("/threads/{thread_id}", response_model=Ok, summary="Delete a conversation")
def remove(project_key: str, thread_id: uuid.UUID, user: User = Depends(current_user),
           db: Session = Depends(get_db)) -> Ok:
    project = get_project(db, project_key, user)
    service.delete_thread(db, project, user, thread_id)
    db.commit()
    return Ok()
