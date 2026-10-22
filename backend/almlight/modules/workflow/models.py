from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from almlight.core.db import Base, created_at_col, uuid_pk


class WorkflowEvent(Base):
    """A lifecycle state change of an item (the status accounting record)."""

    __tablename__ = "workflow_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    transition_key: Mapped[str | None] = mapped_column(String(50))
    from_state: Mapped[str | None] = mapped_column(String(50))
    to_state: Mapped[str] = mapped_column(String(50), nullable=False)
    via: Mapped[str] = mapped_column(String(20), nullable=False)  # transition | approval | change_order | revise
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    comment: Mapped[str | None] = mapped_column(Text)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    approval_request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    change_order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    signed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = created_at_col()


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    transition_key: Mapped[str] = mapped_column(String(50), nullable=False)
    from_state: Mapped[str] = mapped_column(String(50), nullable=False)
    to_state: Mapped[str] = mapped_column(String(50), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    required_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    roles: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    signature_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allow_self_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reject_to: Mapped[str | None] = mapped_column(String(50))
    comment: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = created_at_col()
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApprovalVote(Base):
    """One approver's decision. With ``signed`` the user re-entered the password (e-signature)."""

    __tablename__ = "approval_votes"
    __table_args__ = (UniqueConstraint("request_id", "user_id", name="uq_approval_votes_request_user"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approval_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)  # approve | reject
    comment: Mapped[str | None] = mapped_column(Text)
    signed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    meaning: Mapped[str | None] = mapped_column(String(200))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = created_at_col()
