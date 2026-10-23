"""Version control (Git): connected repositories, indexed commits and commits linked to items
(Polarion "linked revisions")."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from almlight.core.db import Base, created_at_col, uuid_pk


class Repository(Base):
    __tablename__ = "repositories"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_repositories_project_name"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"),
                                                  nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)  # github | gitlab | bitbucket | azure | git
    web_url: Mapped[str | None] = mapped_column(Text)
    default_branch: Mapped[str | None] = mapped_column(String(255))
    auth_user: Mapped[str | None] = mapped_column(String(100))
    token_enc: Mapped[str | None] = mapped_column(Text)  # sealed with core.secretbox; never returned
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    refs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    commit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_col()


class RepoCommit(Base):
    __tablename__ = "repo_commits"
    __table_args__ = (
        UniqueConstraint("repository_id", "sha", name="uq_repo_commits_repository_sha"),
        Index("ix_repo_commits_repository_date", "repository_id", "committed_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    repository_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True),
                                                     ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False)
    sha: Mapped[str] = mapped_column(String(64), nullable=False)
    parents: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    author_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    author_email: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    authored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    committer_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    committed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    files: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    additions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deletions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class CommitLink(Base):
    """A commit linked to an item: found in the commit message (``message``) or linked by hand (``manual``)."""

    __tablename__ = "commit_links"
    __table_args__ = (UniqueConstraint("commit_id", "item_id", name="uq_commit_links_commit_item"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    commit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("repo_commits.id", ondelete="CASCADE"),
                                                 nullable=False, index=True)
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("items.id", ondelete="CASCADE"),
                                               nullable=False, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"),
                                                  nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="message")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_col()
