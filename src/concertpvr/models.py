"""SQLAlchemy models.

Phase 1 defines only the `settings` singleton. Future phases append tables:
  - Phase 2: streams, watch_subscriptions, recordings
  - Phase 3: schedules
  - Phase 4: segments, setlists
  - Phase 5: channel_watchers
"""
from __future__ import annotations

from sqlalchemy import String, Integer, Boolean
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Settings(Base):
    """Singleton row — always id=1."""

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)

    # Emby integration (nullable until configured)
    emby_url: Mapped[str | None] = mapped_column(String, nullable=True)
    emby_api_key: Mapped[str | None] = mapped_column(String, nullable=True)
    emby_library_path: Mapped[str | None] = mapped_column(String, nullable=True)

    # Publish naming
    folder_pattern: Mapped[str] = mapped_column(
        String, default="{artist} - {festival} ({year})", nullable=False
    )

    # Recording defaults
    default_quality: Mapped[str] = mapped_column(
        String, default="bestvideo*+bestaudio/best", nullable=False
    )
    default_retention_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    max_concurrent_recordings: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    auto_prune_when_full: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # yt-dlp cookies file (nullable)
    yt_dlp_cookies_path: Mapped[str | None] = mapped_column(String, nullable=True)
