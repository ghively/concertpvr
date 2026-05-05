"""channel_watchers table

Revision ID: 0005_channel_watchers
Revises: 0004_segments_setlists
Create Date: 2026-04-26
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_channel_watchers"
down_revision: str | None = "0004_segments_setlists"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "channel_watchers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("channel_url", sa.String(), nullable=False, unique=True),
        sa.Column("channel_name", sa.String(), nullable=False),
        sa.Column("avatar_url", sa.String(), nullable=True),
        sa.Column("title_filter", sa.String(), nullable=True),
        sa.Column("quality_cap", sa.String(), nullable=True),
        sa.Column("retention_days", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("last_polled", sa.DateTime(), nullable=True),
        sa.Column("last_live_id", sa.String(), nullable=True),
        sa.Column("added_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("channel_watchers")
