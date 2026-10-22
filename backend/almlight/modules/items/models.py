"""Items and their immutable versions.

Every engineering object — requirement, system element, test case, change order, document —
is an *item* of a configurable type. Each content change creates an immutable
``ItemVersion``; the item row holds a denormalised copy of the head version for fast
listing and search. Versions carry a revision label (A, B, ...) and an iteration
(1, 2, ...), displayed as ``A.3``: revisions are formal, released generations; iterations
are the working saves in between (the revision/version split used by PLM suites).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from almlight.core.db import Base, created_at_col, utcnow, uuid_pk


class Item(Base):
    __tablename__ = "items"
    __table_args__ = (
        UniqueConstraint("project_id", "key", name="uq_items_project_key"),
        Index("ix_items_project_type", "project_id", "type_key"),
        Index("ix_items_search", "search", postgresql_using="gin"),
        Index("ix_items_fields", "fields", postgresql_using="gin", postgresql_ops={"fields": "jsonb_path_ops"}),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    type_key: Mapped[str] = mapped_column(String(50), nullable=False)
    key: Mapped[str] = mapped_column(String(32), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    fields: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    applicability: Mapped[str | None] = mapped_column(Text)
    attachments: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)

    state: Mapped[str | None] = mapped_column(String(50))
    revision: Mapped[str] = mapped_column(String(8), nullable=False)
    iteration: Mapped[int] = mapped_column(Integer, nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    head_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    released_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_col()
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    search: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('simple'::regconfig, coalesce(key, '') || ' ' || coalesce(title, '') || ' ' || "
            "coalesce(description, ''))",
            persisted=True,
        ),
    )

    @property
    def version_label(self) -> str:
        return f"{self.revision}.{self.iteration}"


class ItemVersion(Base):
    __tablename__ = "item_versions"
    __table_args__ = (UniqueConstraint("item_id", "version_no", name="uq_item_versions_item_no"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    revision: Mapped[str] = mapped_column(String(8), nullable=False)
    iteration: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # create | edit | revise | restore | import

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    fields: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    applicability: Mapped[str | None] = mapped_column(Text)
    attachments: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    state: Mapped[str | None] = mapped_column(String(50))

    change_note: Mapped[str | None] = mapped_column(Text)
    change_order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("items.id"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_col()

    @property
    def version_label(self) -> str:
        return f"{self.revision}.{self.iteration}"


class Blob(Base):
    """Content-addressed file content (SHA-256). Files are immutable and de-duplicated."""

    __tablename__ = "blobs"

    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_type: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = created_at_col()


class Comment(Base):
    """A comment on an item, optionally made in the context of a document; replies form threads.

    Comments imported from a Word round trip keep the reviewer's name in ``external_author`` and the
    Word comment identity in ``external_ref`` (so a second import of the same file adds no duplicates).
    """

    __tablename__ = "comments"

    id: Mapped[uuid.UUID] = uuid_pk()
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("items.id"), index=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("comments.id"), index=True)
    author_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    external_author: Mapped[str | None] = mapped_column(String(200))
    external_ref: Mapped[str | None] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="ui")  # ui | word | reqif
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
