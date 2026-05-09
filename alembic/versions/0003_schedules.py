"""schedules table

Revision ID: 0003_schedules
Revises: 0002_streams_recordings
Create Date: 2026-04-25
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_schedules"
down_revision: str | None = "0002_streams_recordings"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "schedules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("stream_id", sa.Integer(),
                  sa.ForeignKey("streams.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("ends_at", sa.DateTime(), nullable=False),
        sa.Column("artist", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("recording_id", sa.Integer(),
                  sa.ForeignKey("recordings.id", ondelete="SET NULL"),
                  nullable=True),
    )
    op.create_index("ix_schedules_stream_id", "schedules", ["stream_id"])


def downgrade() -> None:
    op.drop_index("ix_schedules_stream_id", table_name="schedules")
    op.drop_table("schedules")
