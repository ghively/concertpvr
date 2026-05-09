"""auth columns on settings

Revision ID: 0006_auth
Revises: 0005_channel_watchers
Create Date: 2026-04-26
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_auth"
down_revision: str | None = "0005_channel_watchers"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("settings", sa.Column("password_hash", sa.String(), nullable=True))
    op.add_column("settings", sa.Column("session_secret", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("settings", "session_secret")
    op.drop_column("settings", "password_hash")
