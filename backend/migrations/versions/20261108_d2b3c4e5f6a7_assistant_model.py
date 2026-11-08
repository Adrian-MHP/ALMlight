"""assistant: the model a conversation uses

Revision ID: d2b3c4e5f6a7
Revises: c1a2b3d4e5f6
Create Date: 2026-11-08 18:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'd2b3c4e5f6a7'
down_revision: str | None = 'c1a2b3d4e5f6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('assistant_threads',
                  sa.Column('model', sa.String(length=120), nullable=False, server_default=''))


def downgrade() -> None:
    op.drop_column('assistant_threads', 'model')
