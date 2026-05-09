"""streams, watch_subscriptions, recordings

Revision ID: 0002_streams_recordings
Revises: 0001_initial
Create Date: 2026-04-25
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_streams_recordings"
down_revision: str | None = "0001_initial"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "streams",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("youtube_id", sa.String(), nullable=False, unique=True),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("channel_name", sa.String(), nullable=False),
        sa.Column("thumbnail_url", sa.String(), nullable=True),
        sa.Column("added_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_streams_youtube_id", "streams", ["youtube_id"], unique=True)

    op.create_table(
        "watch_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("stream_id", sa.Integer(),
                  sa.ForeignKey("streams.id", ondelete="CASCADE"),
                  nullable=False, unique=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("title_filter", sa.String(), nullable=True),
        sa.Column("quality_cap", sa.String(), nullable=True),
        sa.Column("retention_days", sa.Integer(), nullable=False, server_default="7"),
    )

    op.create_table(
        "recordings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("stream_id", sa.Integer(),
                  sa.ForeignKey("streams.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("duration_s", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("fps", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="recording"),
        sa.Column("is_buffer", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("error", sa.String(), nullable=True),
    )
    op.create_index("ix_recordings_stream_id", "recordings", ["stream_id"])


def downgrade() -> None:
    op.drop_index("ix_recordings_stream_id", table_name="recordings")
    op.drop_table("recordings")
    op.drop_table("watch_subscriptions")
    op.drop_index("ix_streams_youtube_id", table_name="streams")
    op.drop_table("streams")
