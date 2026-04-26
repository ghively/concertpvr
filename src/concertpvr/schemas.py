"""Pydantic request/response models."""

import datetime as _dt
from typing import Literal

from pydantic import BaseModel, ConfigDict


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
