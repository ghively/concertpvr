"""Pydantic request/response models."""

import datetime as _dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


class SettingsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    emby_url: str | None
    emby_api_key: str | None
    emby_library_path: str | None
    folder_pattern: str
    default_quality: str
    default_retention_days: int
    max_concurrent_recordings: int
    auto_prune_when_full: bool
    yt_dlp_cookies_path: str | None


class SettingsPatch(BaseModel):
    """All fields optional — PATCH semantics. Unknown fields rejected."""

    model_config = ConfigDict(extra="forbid")

    emby_url: str | None = None
    emby_api_key: str | None = None
    emby_library_path: str | None = None
    folder_pattern: str | None = None
    default_quality: str | None = None
    default_retention_days: int | None = None
    max_concurrent_recordings: int | None = None
    auto_prune_when_full: bool | None = None
    yt_dlp_cookies_path: str | None = None

    @field_validator("folder_pattern")
    @classmethod
    def _validate_folder_pattern(cls, v: str | None) -> str | None:
        if v is None:
            return v
        try:
            v.format(
                artist="Test",
                festival="Festival",
                venue="Venue",
                year=2026,
                date="2026-01-01",
                title="Title",
            )
        except (KeyError, IndexError, ValueError) as e:
            raise ValueError(
                f"folder_pattern uses invalid token: {e}. Allowed tokens: "
                "{artist} {festival} {venue} {year} {date} {title}"
            ) from e
        return v


class StreamRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: Literal["channel", "video", "live"]
    youtube_id: str
    url: str
    title: str
    channel_name: str
    thumbnail_url: str | None
    added_at: _dt.datetime


class StreamCreate(BaseModel):
    """Payload for POST /api/streams. Just a URL — server probes the rest."""

    model_config = ConfigDict(extra="forbid")

    url: str


class WatchSubscriptionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    stream_id: int
    enabled: bool
    title_filter: str | None
    quality_cap: str | None
    retention_days: int


class WatchSubscriptionPatch(BaseModel):
    """Toggle or update the watch config for a stream."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    title_filter: str | None = None
    quality_cap: str | None = None
    retention_days: int | None = None


class RecordingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    stream_id: int
    started_at: _dt.datetime
    ended_at: _dt.datetime | None
    path: str
    duration_s: int
    size_bytes: int
    width: int | None
    height: int | None
    fps: int | None
    status: Literal["recording", "complete", "failed", "interrupted"]
    is_buffer: bool
    error: str | None


class ScheduleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    stream_id: int
    starts_at: _dt.datetime
    ends_at: _dt.datetime
    artist: str | None
    status: Literal["pending", "running", "complete", "failed", "cancelled"]
    error: str | None
    recording_id: int | None


class ScheduleCreate(BaseModel):
    """Payload for POST /api/schedules. Either pass an existing stream_id, or a url
    that the server will probe (and create a Stream row if absent)."""

    model_config = ConfigDict(extra="forbid")

    stream_id: int | None = None
    url: str | None = None
    starts_at: _dt.datetime
    ends_at: _dt.datetime
    artist: str | None = None


class SchedulePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    starts_at: _dt.datetime | None = None
    ends_at: _dt.datetime | None = None
    artist: str | None = None
    status: Literal["pending", "cancelled"] | None = None  # only these are user-settable


class SegmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    recording_id: int
    artist: str
    title: str | None
    start_s: int
    end_s: int
    source: Literal["chapter", "setlist", "manual"]
    status: Literal["draft", "publishing", "published", "publish_failed"]
    error: str | None
    emby_path: str | None
    poster_path: str | None
    nfo_path: str | None


class SegmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recording_id: int
    artist: str
    title: str | None = None
    start_s: int
    end_s: int
    source: Literal["chapter", "setlist", "manual"] = "manual"


class SegmentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artist: str | None = None
    title: str | None = None
    start_s: int | None = None
    end_s: int | None = None


class SetlistRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    recording_id: int
    artist: str
    start_s: int
    end_s: int


class SetlistEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artist: str
    start_s: int
    end_s: int


class SetlistReplaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entries: list[SetlistEntry]


class PublishOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    festival: str | None = None
    venue: str | None = None
    year: int | None = None


class ChannelWatcherRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    channel_url: str
    channel_name: str
    avatar_url: str | None
    title_filter: str | None
    quality_cap: str | None
    retention_days: int
    enabled: bool
    last_polled: _dt.datetime | None
    last_live_id: str | None
    added_at: _dt.datetime


class ChannelWatcherCreate(BaseModel):
    """Payload — server probes channel_url to populate channel_name + avatar."""

    model_config = ConfigDict(extra="forbid")

    channel_url: str
    title_filter: str | None = None
    quality_cap: str | None = None
    retention_days: int = 7


class ChannelWatcherPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title_filter: str | None = None
    quality_cap: str | None = None
    retention_days: int | None = None
    enabled: bool | None = None
