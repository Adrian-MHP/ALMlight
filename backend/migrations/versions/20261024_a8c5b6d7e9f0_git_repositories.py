"""git repositories, indexed commits and linked revisions

Revision ID: a8c5b6d7e9f0
Revises: f7b4a5c6d8e9
Create Date: 2026-10-24 09:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'a8c5b6d7e9f0'
down_revision: str | None = 'f7b4a5c6d8e9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'repositories',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('url', sa.Text(), nullable=False),
        sa.Column('provider', sa.String(length=20), nullable=False),
        sa.Column('web_url', sa.Text(), nullable=True),
        sa.Column('default_branch', sa.String(length=255), nullable=True),
        sa.Column('auth_user', sa.String(length=100), nullable=True),
        sa.Column('token_enc', sa.Text(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('refs', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('commit_count', sa.Integer(), nullable=False),
        sa.Column('last_sync_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('next_sync_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_repositories_created_by_users')),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_repositories_project_id_projects'),
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_repositories')),
        sa.UniqueConstraint('project_id', 'name', name='uq_repositories_project_name'),
    )
    op.create_index(op.f('ix_repositories_project_id'), 'repositories', ['project_id'], unique=False)
    op.create_table(
        'repo_commits',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('repository_id', sa.UUID(), nullable=False),
        sa.Column('sha', sa.String(length=64), nullable=False),
        sa.Column('parents', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('author_name', sa.String(length=255), nullable=False),
        sa.Column('author_email', sa.String(length=255), nullable=False),
        sa.Column('authored_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('committer_name', sa.String(length=255), nullable=False),
        sa.Column('committed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('files', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('additions', sa.Integer(), nullable=False),
        sa.Column('deletions', sa.Integer(), nullable=False),
        sa.Column('file_count', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['repository_id'], ['repositories.id'],
                                name=op.f('fk_repo_commits_repository_id_repositories'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_repo_commits')),
        sa.UniqueConstraint('repository_id', 'sha', name='uq_repo_commits_repository_sha'),
    )
    op.create_index('ix_repo_commits_repository_date', 'repo_commits', ['repository_id', 'committed_at'], unique=False)
    op.create_table(
        'commit_links',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('commit_id', sa.UUID(), nullable=False),
        sa.Column('item_id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('source', sa.String(length=16), nullable=False),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['commit_id'], ['repo_commits.id'], name=op.f('fk_commit_links_commit_id_repo_commits'),
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_commit_links_created_by_users')),
        sa.ForeignKeyConstraint(['item_id'], ['items.id'], name=op.f('fk_commit_links_item_id_items'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_commit_links_project_id_projects'),
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_commit_links')),
        sa.UniqueConstraint('commit_id', 'item_id', name='uq_commit_links_commit_item'),
    )
    op.create_index(op.f('ix_commit_links_commit_id'), 'commit_links', ['commit_id'], unique=False)
    op.create_index(op.f('ix_commit_links_item_id'), 'commit_links', ['item_id'], unique=False)


def downgrade() -> None:
    op.drop_table('commit_links')
    op.drop_table('repo_commits')
    op.drop_table('repositories')
