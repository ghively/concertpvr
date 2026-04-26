"""index on schedules.recording_id

Revision ID: 0007_index_schedule_recording
Revises: 0006_auth
Create Date: 2026-04-26
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0007_index_schedule_recording"
down_revision: str | None = "0006_auth"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_schedules_recording_id", "schedules", ["recording_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_schedules_recording_id", table_name="schedules")
