"""time recording, resource capacity per member, user interface language

Revision ID: f7b4a5c6d8e9
Revises: e6a3f4b5c7d8
Create Date: 2026-10-23 18:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'f7b4a5c6d8e9'
down_revision: str | None = 'e6a3f4b5c7d8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'work_records',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('item_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('day', sa.Date(), nullable=False),
        sa.Column('hours', sa.Float(), nullable=False),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['item_id'], ['items.id'], name=op.f('fk_work_records_item_id_items'),
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_work_records_project_id_projects'),
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_work_records_user_id_users')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_work_records')),
    )
    op.create_index(op.f('ix_work_records_item_id'), 'work_records', ['item_id'], unique=False)
    op.create_index('ix_work_records_user_day', 'work_records', ['user_id', 'day'], unique=False)
    op.create_index('ix_work_records_project_day', 'work_records', ['project_id', 'day'], unique=False)
    op.add_column('project_members', sa.Column('hours_per_day', sa.Float(), server_default='8', nullable=False))
    op.add_column('users', sa.Column('locale', sa.String(length=8), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'locale')
    op.drop_column('project_members', 'hours_per_day')
    op.drop_table('work_records')
