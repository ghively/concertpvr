"""Pydantic request/response models."""
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
