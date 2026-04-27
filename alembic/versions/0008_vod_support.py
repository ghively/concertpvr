"""VOD downloads support — additive columns across 5 tables.

Revision ID: 0008_vod_support
Revises: 0007_index_schedule_recording
Create Date: 2026-04-26
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_vod_support"
down_revision: str | None = "0007_index_schedule_recording"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # channel_watchers: 9 columns
    with op.batch_alter_table("channel_watchers") as batch:
        batch.add_column(sa.Column("watch_live", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.add_column(sa.Column("watch_vod_uploads", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("vod_segmentation_mode", sa.String(), nullable=False, server_default="chapters"))
        batch.add_column(sa.Column("vod_title_filter", sa.String(), nullable=True))
        batch.add_column(sa.Column("vod_artist_regex", sa.String(), nullable=True))
        batch.add_column(sa.Column("auto_publish", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("extract_setlist_from_comments", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("default_genres", sa.String(), nullable=True))
        batch.add_column(sa.Column("auto_delete_source_after_publish", sa.Boolean(), nullable=True))

    # streams: 6 columns
    with op.batch_alter_table("streams") as batch:
        batch.add_column(sa.Column("original_upload_date", sa.Date(), nullable=True))
        batch.add_column(sa.Column("description", sa.Text(), nullable=True))
        batch.add_column(sa.Column("youtube_tags", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("detected_setlist_text", sa.Text(), nullable=True))
        batch.add_column(sa.Column("detected_setlist_source", sa.String(), nullable=True))
        batch.add_column(sa.Column("watcher_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_streams_watcher_id", "channel_watchers", ["watcher_id"], ["id"], ondelete="SET NULL",
        )
        batch.create_index("ix_streams_watcher_id", ["watcher_id"])

    # segments: 1 column
    with op.batch_alter_table("segments") as batch:
        batch.add_column(sa.Column("genres", sa.String(), nullable=True))

    # recordings: 2 columns
    with op.batch_alter_table("recordings") as batch:
        batch.add_column(sa.Column("auto_publish_after_download", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("source_deleted", sa.Boolean(), nullable=False, server_default=sa.false()))

    # settings: 2 columns
    with op.batch_alter_table("settings") as batch:
        batch.add_column(sa.Column("max_concurrent_vod_downloads", sa.Integer(), nullable=False, server_default="2"))
        batch.add_column(sa.Column("auto_delete_source_after_publish", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch:
        batch.drop_column("auto_delete_source_after_publish")
        batch.drop_column("max_concurrent_vod_downloads")
    with op.batch_alter_table("recordings") as batch:
        batch.drop_column("source_deleted")
        batch.drop_column("auto_publish_after_download")
    with op.batch_alter_table("segments") as batch:
        batch.drop_column("genres")
    with op.batch_alter_table("streams") as batch:
        batch.drop_index("ix_streams_watcher_id")
        batch.drop_constraint("fk_streams_watcher_id", type_="foreignkey")
        batch.drop_column("watcher_id")
        batch.drop_column("detected_setlist_source")
        batch.drop_column("detected_setlist_text")
        batch.drop_column("youtube_tags")
        batch.drop_column("description")
        batch.drop_column("original_upload_date")
    with op.batch_alter_table("channel_watchers") as batch:
        batch.drop_column("auto_delete_source_after_publish")
        batch.drop_column("default_genres")
        batch.drop_column("extract_setlist_from_comments")
        batch.drop_column("auto_publish")
        batch.drop_column("vod_artist_regex")
        batch.drop_column("vod_title_filter")
        batch.drop_column("vod_segmentation_mode")
        batch.drop_column("watch_vod_uploads")
        batch.drop_column("watch_live")
