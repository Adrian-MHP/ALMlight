"""notifications, subscriptions, saved queries, file check-outs, Word templates, test step results, user preferences

Revision ID: d5f2e3a4b6c7
Revises: c4e1d2f3a5b6
Create Date: 2026-10-23 12:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'd5f2e3a4b6c7'
down_revision: str | None = 'c4e1d2f3a5b6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('users', sa.Column('email_notifications', sa.Boolean(), server_default='true', nullable=False))
    op.add_column('users', sa.Column('auth_provider', sa.String(length=32), server_default='local', nullable=False))
    op.add_column('test_records', sa.Column('step_results', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_table(
        'subscriptions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('item_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['item_id'], ['items.id'], name=op.f('fk_subscriptions_item_id_items'),
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_subscriptions_project_id_projects'),
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_subscriptions_user_id_users'),
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_subscriptions')),
        sa.UniqueConstraint('user_id', 'item_id', name='uq_subscriptions_user_item'),
    )
    op.create_index(op.f('ix_subscriptions_user_id'), 'subscriptions', ['user_id'], unique=False)
    op.create_index(op.f('ix_subscriptions_project_id'), 'subscriptions', ['project_id'], unique=False)
    op.create_index(op.f('ix_subscriptions_item_id'), 'subscriptions', ['item_id'], unique=False)
    op.create_table(
        'notifications',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=True),
        sa.Column('kind', sa.String(length=32), nullable=False),
        sa.Column('title', sa.String(length=300), nullable=False),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('item_key', sa.String(length=40), nullable=True),
        sa.Column('actor_name', sa.String(length=128), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('emailed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_notifications_project_id_projects'),
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_notifications_user_id_users'),
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_notifications')),
    )
    op.create_index('ix_notifications_user_unread', 'notifications', ['user_id', 'read_at'], unique=False)
    op.create_table(
        'saved_queries',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('owner_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('query', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('shared', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_saved_queries_owner_id_users')),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_saved_queries_project_id_projects'),
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_saved_queries')),
    )
    op.create_index(op.f('ix_saved_queries_project_id'), 'saved_queries', ['project_id'], unique=False)
    op.create_table(
        'file_checkouts',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('item_id', sa.UUID(), nullable=False),
        sa.Column('attachment_id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('checked_out_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['item_id'], ['items.id'], name=op.f('fk_file_checkouts_item_id_items'),
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_file_checkouts_project_id_projects'),
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_file_checkouts_user_id_users'),
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_file_checkouts')),
        sa.UniqueConstraint('item_id', 'attachment_id', name='uq_file_checkouts_item_attachment'),
    )
    op.create_index(op.f('ix_file_checkouts_project_id'), 'file_checkouts', ['project_id'], unique=False)
    op.create_index(op.f('ix_file_checkouts_item_id'), 'file_checkouts', ['item_id'], unique=False)
    op.create_index(op.f('ix_file_checkouts_user_id'), 'file_checkouts', ['user_id'], unique=False)
    op.create_table(
        'doc_templates',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('size', sa.Integer(), nullable=False),
        sa.Column('info', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_doc_templates_created_by_users')),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_doc_templates_project_id_projects'),
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_doc_templates')),
    )
    op.create_index(op.f('ix_doc_templates_project_id'), 'doc_templates', ['project_id'], unique=False)


def downgrade() -> None:
    op.drop_table('doc_templates')
    op.drop_table('file_checkouts')
    op.drop_table('saved_queries')
    op.drop_index('ix_notifications_user_unread', table_name='notifications')
    op.drop_table('notifications')
    op.drop_table('subscriptions')
    op.drop_column('test_records', 'step_results')
    op.drop_column('users', 'auth_provider')
    op.drop_column('users', 'email_notifications')
