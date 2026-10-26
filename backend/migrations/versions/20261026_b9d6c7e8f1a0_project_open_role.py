"""projects: role for every signed-in user (open projects)

Revision ID: b9d6c7e8f1a0
Revises: a8c5b6d7e9f0
Create Date: 2026-10-26 16:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'b9d6c7e8f1a0'
down_revision: str | None = 'a8c5b6d7e9f0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('projects', sa.Column('open_role', sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column('projects', 'open_role')
