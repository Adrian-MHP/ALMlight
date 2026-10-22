"""Document branches: a copy of a structural sub-tree that can later be merged back (3-way)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from almlight.core.db import Base, created_at_col, uuid_pk


class Branch(Base):
    __tablename__ = "branches"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    source_root_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("items.id"), nullable=False)
    branch_root_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("items.id"), nullable=False, unique=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_col()
    last_merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BranchItem(Base):
    """Pairs a source item with its copy and records their common ancestor (merge base).

    The base is a version of either side: initially the source version that was copied; after a merge into the
    source it is the merged branch version, after an update from the source it is the source version (git-like).
    """

    __tablename__ = "branch_items"

    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), primary_key=True
    )
    branch_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("items.id"), primary_key=True)
    source_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("items.id"), nullable=False, index=True
    )
    base_side: Mapped[str] = mapped_column(String(8), nullable=False, default="source")  # source | branch
    base_version_no: Mapped[int] = mapped_column(Integer, nullable=False)
