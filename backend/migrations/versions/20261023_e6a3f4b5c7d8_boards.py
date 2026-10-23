"""kanban boards

Revision ID: e6a3f4b5c7d8
Revises: d5f2e3a4b6c7
Create Date: 2026-10-23 14:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'e6a3f4b5c7d8'
down_revision: str | None = 'd5f2e3a4b6c7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'boards',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('owner_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('shared', sa.Boolean(), nullable=False),
        sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_boards_owner_id_users')),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_boards_project_id_projects'),
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_boards')),
    )
    op.create_index(op.f('ix_boards_project_id'), 'boards', ['project_id'], unique=False)


def downgrade() -> None:
    op.drop_table('boards')
