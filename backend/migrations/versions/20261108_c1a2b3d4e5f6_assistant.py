"""AI assistant: conversations and their messages

Revision ID: c1a2b3d4e5f6
Revises: b9d6c7e8f1a0
Create Date: 2026-11-08 09:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'c1a2b3d4e5f6'
down_revision: str | None = 'b9d6c7e8f1a0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'assistant_threads',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('pending', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_assistant_threads_project_id_projects'),
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_assistant_threads_user_id_users')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_assistant_threads')),
    )
    op.create_index(op.f('ix_assistant_threads_project_id'), 'assistant_threads', ['project_id'])
    op.create_index(op.f('ix_assistant_threads_user_id'), 'assistant_threads', ['user_id'])
    op.create_table(
        'assistant_messages',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('thread_id', sa.UUID(), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(length=16), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['thread_id'], ['assistant_threads.id'],
                                name=op.f('fk_assistant_messages_thread_id_assistant_threads'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_assistant_messages')),
    )
    op.create_index('ix_assistant_messages_thread_seq', 'assistant_messages', ['thread_id', 'seq'])


def downgrade() -> None:
    op.drop_table('assistant_messages')
    op.drop_table('assistant_threads')
