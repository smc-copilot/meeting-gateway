"""add_meeting_oauth_userid_maps

Revision ID: c98b7080a9c8
Revises: 5085e424607f
Create Date: 2026-10-22 10:55:05.157409

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c98b7080a9c8'
down_revision: Union[str, Sequence[str], None] = '5085e424607f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'meeting_oauth_userid_maps',
        sa.Column('open_id', sa.String(length=128), nullable=False),
        sa.Column('userid', sa.String(length=128), nullable=False),
        sa.Column('oauth_sdk_id', sa.String(length=128), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('org_id', sa.String(length=64), nullable=False),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_meeting_oauth_userid_maps_deleted_at'), 'meeting_oauth_userid_maps', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_meeting_oauth_userid_maps_open_id'), 'meeting_oauth_userid_maps', ['open_id'], unique=False)
    op.create_index(op.f('ix_meeting_oauth_userid_maps_org_id'), 'meeting_oauth_userid_maps', ['org_id'], unique=False)
    op.create_index(op.f('ix_meeting_oauth_userid_maps_userid'), 'meeting_oauth_userid_maps', ['userid'], unique=False)
    op.create_index(
        'uq_meeting_oauth_userid_map',
        'meeting_oauth_userid_maps',
        ['org_id', 'open_id'],
        unique=True,
        postgresql_where=sa.text('deleted_at IS NULL'),
        sqlite_where=sa.text('deleted_at IS NULL'),
    )


def downgrade() -> None:
    op.drop_index('uq_meeting_oauth_userid_map', table_name='meeting_oauth_userid_maps')
    op.drop_index(op.f('ix_meeting_oauth_userid_maps_userid'), table_name='meeting_oauth_userid_maps')
    op.drop_index(op.f('ix_meeting_oauth_userid_maps_org_id'), table_name='meeting_oauth_userid_maps')
    op.drop_index(op.f('ix_meeting_oauth_userid_maps_open_id'), table_name='meeting_oauth_userid_maps')
    op.drop_index(op.f('ix_meeting_oauth_userid_maps_deleted_at'), table_name='meeting_oauth_userid_maps')
    op.drop_table('meeting_oauth_userid_maps')
