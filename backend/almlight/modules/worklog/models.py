"""Time recording: hours a person worked on an item on a day (Polarion work records, Teamcenter time sheets)."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from almlight.core.db import Base, created_at_col, utcnow, uuid_pk


class WorkRecord(Base):
    __tablename__ = "work_records"
    __table_args__ = (
        Index("ix_work_records_user_day", "user_id", "day"),
        Index("ix_work_records_project_day", "project_id", "day"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"),
                                                  nullable=False)
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("items.id", ondelete="CASCADE"),
                                               nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    hours: Mapped[float] = mapped_column(Float, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
