"""initial schema: settings singleton

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-24
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("emby_url", sa.String(), nullable=True),
        sa.Column("emby_api_key", sa.String(), nullable=True),
        sa.Column("emby_library_path", sa.String(), nullable=True),
        sa.Column("folder_pattern", sa.String(), nullable=False,
                  server_default="{artist} - {festival} ({year})"),
        sa.Column("default_quality", sa.String(), nullable=False,
                  server_default="bestvideo*+bestaudio/best"),
        sa.Column("default_retention_days", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("max_concurrent_recordings", sa.Integer(), nullable=False, server_default="4"),
        sa.Column("auto_prune_when_full", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("yt_dlp_cookies_path", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("settings")
