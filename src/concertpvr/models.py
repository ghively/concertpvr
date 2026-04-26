"""SQLAlchemy models.

Phase 1 defines only the `settings` singleton. Future phases append tables:
  - Phase 2: streams, watch_subscriptions, recordings
  - Phase 3: schedules
  - Phase 4: segments, setlists
  - Phase 5: channel_watchers
"""

from __future__ import annotations

import datetime as _dt

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


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


class Stream(Base):
    __tablename__ = "streams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)  # channel|video|live
    youtube_id: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    url: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    channel_name: Mapped[str] = mapped_column(String, nullable=False)
    thumbnail_url: Mapped[str | None] = mapped_column(String, nullable=True)
    added_at: Mapped[_dt.datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: _dt.datetime.now(_dt.UTC)
    )

    subscription = relationship(
        "WatchSubscription", back_populates="stream", uselist=False, cascade="all, delete-orphan"
    )
    recordings = relationship("Recording", back_populates="stream", cascade="all, delete-orphan")


class WatchSubscription(Base):
    __tablename__ = "watch_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stream_id: Mapped[int] = mapped_column(
        ForeignKey("streams.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    title_filter: Mapped[str | None] = mapped_column(String, nullable=True)
    quality_cap: Mapped[str | None] = mapped_column(String, nullable=True)
    retention_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)

    stream = relationship("Stream", back_populates="subscription")


class Recording(Base):
    __tablename__ = "recordings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stream_id: Mapped[int] = mapped_column(
        ForeignKey("streams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    started_at: Mapped[_dt.datetime] = mapped_column(DateTime, nullable=False)
    ended_at: Mapped[_dt.datetime | None] = mapped_column(DateTime, nullable=True)
    path: Mapped[str] = mapped_column(String, nullable=False)
    duration_s: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="recording")
    is_buffer: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error: Mapped[str | None] = mapped_column(String, nullable=True)

    stream = relationship("Stream", back_populates="recordings")


class Schedule(Base):
    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stream_id: Mapped[int] = mapped_column(
        ForeignKey("streams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    starts_at: Mapped[_dt.datetime] = mapped_column(DateTime, nullable=False)
    ends_at: Mapped[_dt.datetime] = mapped_column(DateTime, nullable=False)
    artist: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    recording_id: Mapped[int | None] = mapped_column(
        ForeignKey("recordings.id", ondelete="SET NULL"), nullable=True
    )

    stream = relationship("Stream")
    recording = relationship("Recording")
