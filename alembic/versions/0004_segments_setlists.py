"""segments + setlists tables, raw_chapters_json on recordings

Revision ID: 0004_segments_setlists
Revises: 0003_schedules
Create Date: 2026-04-26
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_segments_setlists"
down_revision: str | None = "0003_schedules"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("recordings",
                  sa.Column("raw_chapters_json", sa.String(), nullable=True))

    op.create_table(
        "segments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("recording_id", sa.Integer(),
                  sa.ForeignKey("recordings.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("artist", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("start_s", sa.Integer(), nullable=False),
        sa.Column("end_s", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("emby_path", sa.String(), nullable=True),
        sa.Column("poster_path", sa.String(), nullable=True),
        sa.Column("nfo_path", sa.String(), nullable=True),
    )
    op.create_index("ix_segments_recording_id", "segments", ["recording_id"])

    op.create_table(
        "setlists",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("recording_id", sa.Integer(),
                  sa.ForeignKey("recordings.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("artist", sa.String(), nullable=False),
        sa.Column("start_s", sa.Integer(), nullable=False),
        sa.Column("end_s", sa.Integer(), nullable=False),
    )
    op.create_index("ix_setlists_recording_id", "setlists", ["recording_id"])


def downgrade() -> None:
    op.drop_index("ix_setlists_recording_id", table_name="setlists")
    op.drop_table("setlists")
    op.drop_index("ix_segments_recording_id", table_name="segments")
    op.drop_table("segments")
    op.drop_column("recordings", "raw_chapters_json")
