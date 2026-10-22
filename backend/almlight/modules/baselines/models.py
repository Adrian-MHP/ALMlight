"""Baselines: immutable, named snapshots of item versions and links (ISO 10007 configuration baseline)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from almlight.core.db import Base, created_at_col, uuid_pk


class Baseline(Base):
    __tablename__ = "baselines"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    scope_root_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("items.id"))
    revision_rule: Mapped[str] = mapped_column(String(16), nullable=False)  # latest | released
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    link_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_col()


class BaselineItem(Base):
    __tablename__ = "baseline_items"

    baseline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("baselines.id", ondelete="CASCADE"), primary_key=True
    )
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("items.id"), primary_key=True)
    version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("item_versions.id"), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    revision: Mapped[str] = mapped_column(String(8), nullable=False)
    iteration: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str | None] = mapped_column(String(50))


class BaselineLink(Base):
    __tablename__ = "baseline_links"

    id: Mapped[uuid.UUID] = uuid_pk()
    baseline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("baselines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    link_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    type_key: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    position: Mapped[float | None] = mapped_column(Float)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    applicability: Mapped[str | None] = mapped_column(Text)
    suspect: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
