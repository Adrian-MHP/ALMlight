"""rich text (HTML descriptions), embedded images, co-editing drafts

Revision ID: c4e1d2f3a5b6
Revises: ab9170640f94
Create Date: 2026-10-23 09:00:00

Descriptions were Markdown until 0.3; they are converted to canonical HTML here (the same converter the API
uses for Markdown input). The conversion is content-preserving: headings, emphasis, lists, tables and code
become their HTML equivalents.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'c4e1d2f3a5b6'
down_revision: str | None = 'ab9170640f94'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'images',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('content_type', sa.String(length=100), nullable=False),
        sa.Column('size', sa.BigInteger(), nullable=False),
        sa.Column('width', sa.Integer(), nullable=True),
        sa.Column('height', sa.Integer(), nullable=True),
        sa.Column('uploaded_by', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_images_project_id_projects'),
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['sha256'], ['blobs.sha256'], name=op.f('fk_images_sha256_blobs')),
        sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], name=op.f('fk_images_uploaded_by_users')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_images')),
        sa.UniqueConstraint('project_id', 'sha256', name='uq_images_project_sha256'),
    )
    op.create_index('ix_images_sha256', 'images', ['sha256'], unique=False)
    op.create_table(
        'collab_drafts',
        sa.Column('item_id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('base_hash', sa.String(length=16), nullable=False),
        sa.Column('state', sa.LargeBinary(), nullable=False),
        sa.Column('contributors', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['item_id'], ['items.id'], name=op.f('fk_collab_drafts_item_id_items'),
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_collab_drafts_project_id_projects'),
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('item_id', name=op.f('pk_collab_drafts')),
    )
    _convert_descriptions()


def _convert_descriptions() -> None:
    from almlight.core.richtext import looks_like_html, markdown_to_html

    conn = op.get_bind()
    for table in ("items", "item_versions"):
        rows = conn.execute(sa.text(f"SELECT id, description FROM {table} WHERE description <> ''")).fetchall()
        for row_id, text in rows:
            if looks_like_html(text):
                continue
            conn.execute(sa.text(f"UPDATE {table} SET description = :d WHERE id = :i"),
                         {"d": markdown_to_html(text), "i": row_id})


def downgrade() -> None:
    op.drop_table('collab_drafts')
    op.drop_index('ix_images_sha256', table_name='images')
    op.drop_table('images')
