"""channel_backlog_cache table — per-watcher full-channel snapshot.

Revision ID: 0009_channel_backlog_cache
Revises: 0008_vod_support
Create Date: 2026-04-27
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_channel_backlog_cache"
down_revision: str | None = "0008_vod_support"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "channel_backlog_cache",
        sa.Column("watcher_id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column(
            "status", sa.String(), nullable=False, server_default="never_fetched"
        ),  # 'never_fetched' | 'fetching' | 'complete' | 'error'
        sa.Column("fetched_at", sa.DateTime(), nullable=True),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("items_json", sa.JSON(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("progress_pct", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(
            ["watcher_id"], ["channel_watchers.id"], ondelete="CASCADE"
        ),
    )


def downgrade() -> None:
    op.drop_table("channel_backlog_cache")
