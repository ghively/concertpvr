"""emby path translation columns + setlistfm api key.

v0.4.1 adds:
- settings.emby_path_local_prefix: the local prefix that publisher writes to
- settings.emby_path_emby_prefix: the corresponding prefix Emby sees
- settings.setlistfm_api_key: optional setlist.fm REST API key for setlist
  detection fallback
- channel_watchers.extract_setlist_from_setlistfm: per-watcher toggle

All nullable / falsy defaults — additive, no data migration.

Revision ID: 0010_emby_path_translation
Revises: 0009_channel_backlog_cache
Create Date: 2026-05-05
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010_emby_path_translation"
down_revision: str | None = "0009_channel_backlog_cache"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "settings", sa.Column("emby_path_local_prefix", sa.String(), nullable=True)
    )
    op.add_column(
        "settings", sa.Column("emby_path_emby_prefix", sa.String(), nullable=True)
    )
    op.add_column(
        "settings", sa.Column("setlistfm_api_key", sa.String(), nullable=True)
    )
    op.add_column(
        "channel_watchers",
        sa.Column(
            "extract_setlist_from_setlistfm",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("channel_watchers", "extract_setlist_from_setlistfm")
    op.drop_column("settings", "setlistfm_api_key")
    op.drop_column("settings", "emby_path_emby_prefix")
    op.drop_column("settings", "emby_path_local_prefix")
