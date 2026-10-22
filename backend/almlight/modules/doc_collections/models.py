"""Collections: a named set of document baselines that belong together (e.g. the specifications of a release).

Like collections in enterprise ALM tools: the same document baseline can be part of several collections; closing a
collection freezes its content; only managers can reopen it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from almlight.core.db import Base, created_at_col, uuid_pk


class Collection(Base):
    __tablename__ = "collections"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")  # open | closed
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_col()
    closed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CollectionEntry(Base):
    __tablename__ = "collection_entries"
    __table_args__ = (UniqueConstraint("collection_id", "document_id", name="uq_collection_entries_doc"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    collection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("collections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("items.id"), nullable=False)
    baseline_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("baselines.id"), nullable=False)
    added_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    added_at: Mapped[datetime] = created_at_col()
