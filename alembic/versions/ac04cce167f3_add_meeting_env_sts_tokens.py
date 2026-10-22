"""add_meeting_env_sts_tokens

Revision ID: ac04cce167f3
Revises: c98b7080a9c8
Create Date: 2026-10-22 11:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'ac04cce167f3'
down_revision: Union[str, Sequence[str], None] = 'c98b7080a9c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'meeting_env_sts_tokens',
        sa.Column('req_id', sa.String(length=128), nullable=False),
        sa.Column('state', sa.String(length=32), nullable=False),
        sa.Column('token_ciphertext', sa.Text(), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('valid_hours', sa.Integer(), nullable=False),
        sa.Column('requested_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('operator_id', sa.String(length=128), nullable=False),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_meeting_env_sts_tokens_deleted_at'), 'meeting_env_sts_tokens', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_meeting_env_sts_tokens_req_id'), 'meeting_env_sts_tokens', ['req_id'], unique=False)
    op.create_index(
        'uq_meeting_env_sts_token_req',
        'meeting_env_sts_tokens',
        ['req_id'],
        unique=True,
        postgresql_where=sa.text('deleted_at IS NULL'),
        sqlite_where=sa.text('deleted_at IS NULL'),
    )


def downgrade() -> None:
    op.drop_index('uq_meeting_env_sts_token_req', table_name='meeting_env_sts_tokens')
    op.drop_index(op.f('ix_meeting_env_sts_tokens_req_id'), table_name='meeting_env_sts_tokens')
    op.drop_index(op.f('ix_meeting_env_sts_tokens_deleted_at'), table_name='meeting_env_sts_tokens')
    op.drop_table('meeting_env_sts_tokens')
