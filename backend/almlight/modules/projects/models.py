from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from almlight.core.db import Base, created_at_col, uuid_pk
from almlight.modules.projects.metamodel import ProjectTemplate, parse_config


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = uuid_pk()
    key: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    template_key: Mapped[str] = mapped_column(String(64), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    config_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_col()
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def model(self) -> ProjectTemplate:
        """The parsed information model, cached per config version."""
        cached = self.__dict__.get("_parsed_cache")
        if cached is None or cached[0] != self.config_version:
            cached = (self.config_version, parse_config(self.config))
            self.__dict__["_parsed_cache"] = cached
        return cached[1]


class ProjectMember(Base):
    __tablename__ = "project_members"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    # working hours per working day available for this project (resource load, levelling)
    hours_per_day: Mapped[float] = mapped_column(Float, nullable=False, default=8.0, server_default="8")
    created_at: Mapped[datetime] = created_at_col()


class ProjectCounter(Base):
    """Per-project, per-prefix sequence for human-readable item keys (e.g. SYS-12)."""

    __tablename__ = "project_counters"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    prefix: Mapped[str] = mapped_column(String(8), primary_key=True)
    next_value: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
