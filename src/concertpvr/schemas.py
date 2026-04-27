"""Pydantic request/response models."""

import datetime as _dt
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SegmentationMode = Literal["chapters", "whole-video", "manual"]


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
    # VOD settings (v0.3)
    max_concurrent_vod_downloads: int
    auto_delete_source_after_publish: bool


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

    # VOD settings (v0.3)
    max_concurrent_vod_downloads: int | None = Field(default=None, ge=1, le=8)
    auto_delete_source_after_publish: bool | None = None

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
                channel="Channel",
            )
        except (KeyError, IndexError, ValueError) as e:
            raise ValueError(
                f"folder_pattern uses invalid token: {e}. Allowed tokens: "
                "{artist} {festival} {venue} {year} {date} {title} {channel}"
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
    # VOD metadata (v0.3)
    original_upload_date: _dt.date | None
    description: str | None
    youtube_tags: list[str] | None
    detected_setlist_text: str | None
    detected_setlist_source: str | None
    watcher_id: int | None


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
    # VOD fields (v0.3)
    auto_publish_after_download: bool
    source_deleted: bool


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
    # VOD field (v0.3)
    genres: str | None


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
    # VOD field (v0.3)
    genres: str | None = None


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


class BacklogItem(BaseModel):
    youtube_id: str
    title: str
    url: str
    thumbnail_url: str | None
    upload_date: _dt.date | None
    duration_s: int | None
    # view_count is always None: yt-dlp flat-extract doesn't return view counts cheaply
    view_count: int | None
    state: Literal["downloaded", "queued", "not_downloaded"]


class BacklogDownloadRequest(BaseModel):
    video_ids: list[str]


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
    # VOD fields (v0.3)
    watch_live: bool
    watch_vod_uploads: bool
    vod_segmentation_mode: SegmentationMode
    vod_title_filter: str | None
    vod_artist_regex: str | None
    auto_publish: bool
    extract_setlist_from_comments: bool
    default_genres: str | None
    auto_delete_source_after_publish: bool | None


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
    # VOD fields (v0.3)
    watch_live: bool | None = None
    watch_vod_uploads: bool | None = None
    vod_segmentation_mode: SegmentationMode | None = None
    vod_title_filter: str | None = None
    vod_artist_regex: str | None = None
    auto_publish: bool | None = None
    extract_setlist_from_comments: bool | None = None
    default_genres: str | None = None
    auto_delete_source_after_publish: bool | None = None

    @field_validator("vod_title_filter")
    @classmethod
    def _validate_vod_title_filter(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return v
        try:
            re.compile(v)
        except re.error as e:
            raise ValueError(f"vod_title_filter: invalid regex: {e}") from e
        return v

    @field_validator("vod_artist_regex")
    @classmethod
    def _validate_vod_artist_regex(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return v
        try:
            compiled = re.compile(v)
        except re.error as e:
            raise ValueError(f"vod_artist_regex: invalid regex: {e}") from e
        # If the regex has any groups, it must include a named group "artist".
        if compiled.groups > 0 and "artist" not in compiled.groupindex:
            raise ValueError(
                "vod_artist_regex must include a named group (?P<artist>...) "
                "if it has any capture groups"
            )
        return v
