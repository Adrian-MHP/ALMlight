"""Check-out locks on files attached to items (exclusive editing, e.g. of CAD models or Office files)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from almlight.core.db import Base, created_at_col, uuid_pk


class FileCheckout(Base):
    __tablename__ = "file_checkouts"
    __table_args__ = (UniqueConstraint("item_id", "attachment_id", name="uq_file_checkouts_item_attachment"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"),
                                                  nullable=False, index=True)
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("items.id", ondelete="CASCADE"),
                                               nullable=False, index=True)
    attachment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
                                               nullable=False, index=True)
    note: Mapped[str | None] = mapped_column(Text)
    checked_out_at: Mapped[datetime] = created_at_col()
