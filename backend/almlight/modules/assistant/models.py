"""Conversations with the AI assistant.

A thread belongs to one project and one person: the assistant sees exactly what that person may see, because every
tool goes through the normal services with their role. Messages are kept so a conversation survives a reload and
so the audit trail can be followed back to what was asked.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from almlight.core.db import Base, created_at_col, uuid_pk


class AssistantThread(Base):
    __tablename__ = "assistant_threads"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # which language model answers in this conversation ("azure:<deployment>", "ollama:<tag>"); empty = the default
    model: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    # tool calls the model wants to run that change data; they wait for the person's confirmation
    pending: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = created_at_col()


class AssistantMessage(Base):
    __tablename__ = "assistant_messages"
    __table_args__ = (Index("ix_assistant_messages_thread_seq", "thread_id", "seq"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assistant_threads.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user | assistant | tool
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # assistant: the tool calls it made; tool: {"name": ..., "call_id": ..., "arguments": ..., "ok": bool}
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = created_at_col()
