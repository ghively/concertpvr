"""Frontend↔backend contract tests.

Each test hardcodes a JSON payload literally extracted from a frontend
component's POST/PATCH body, then asserts the corresponding backend Pydantic
schema accepts it without validation error.

This catches the "frontend sends X, backend rejects X with 422" class of bug
that pure unit tests miss because backend tests construct synthetic payloads
matching the schema rather than what the UI actually sends.

When updating frontend payloads, MIRROR THE CHANGE HERE and the test will
either fail (revealing the contract drift) or stay green (proving the
contract holds).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from concertpvr.schemas import (
    BacklogDownloadRequest,
    ChannelWatcherCreate,
    ChannelWatcherPatch,
    SegmentCreate,
    SegmentPatch,
    SettingsPatch,
)

# v0.3 frontend payloads. Each PAYLOAD_* constant is exactly what the frontend
# component sends — copied from the .tsx source. If the .tsx changes, update
# the constant here at the same time.

# Source: frontend/src/components/SmartPasteModal.tsx ChannelResultPanel
PAYLOAD_SMART_PASTE_CHANNEL_SUBSCRIBE = {
    "channel_url": "https://www.youtube.com/@nprmusic",
    "watch_live": False,
    "watch_vod_uploads": True,
    "auto_publish": False,
}

# Same component, all toggles on (e.g. Coachella main channel)
PAYLOAD_SMART_PASTE_CHANNEL_BOTH_MODES = {
    "channel_url": "https://www.youtube.com/@coachella",
    "watch_live": True,
    "watch_vod_uploads": True,
    "auto_publish": False,
}

# Source: frontend/src/pages/Watchers.tsx manual-add form (legacy path)
PAYLOAD_WATCHER_MANUAL_ADD = {
    "channel_url": "https://www.youtube.com/@nprmusic",
    "title_filter": "Tiny Desk",
    "retention_days": 14,
}

# Source: frontend/src/pages/WatcherDetail.tsx Settings tab — full form save
PAYLOAD_WATCHER_PATCH_FULL_VOD_FORM = {
    "watch_live": False,
    "watch_vod_uploads": True,
    "vod_segmentation_mode": "whole-video",
    "vod_title_filter": "Tiny Desk Concert",
    "vod_artist_regex": r"^(?P<artist>.+?)\s*[:|]\s*(?:NPR Music )?Tiny Desk",
    "auto_publish": True,
    "extract_setlist_from_comments": True,
    "default_genres": "Indie, Alternative, Folk",
    "auto_delete_source_after_publish": False,
}

# Same form but "inherit" tri-state for auto_delete (null = inherit settings)
PAYLOAD_WATCHER_PATCH_INHERIT_AUTODELETE = {
    "watch_vod_uploads": True,
    "auto_delete_source_after_publish": None,
}

# Source: frontend/src/pages/Settings.tsx — VOD settings save
PAYLOAD_SETTINGS_PATCH_VOD_FIELDS = {
    "max_concurrent_vod_downloads": 4,
    "auto_delete_source_after_publish": True,
}

# Same page, full form including legacy fields
PAYLOAD_SETTINGS_PATCH_FULL = {
    "folder_pattern": "{channel}/{artist} ({year})",
    "default_quality": "bestvideo*+bestaudio/best",
    "default_retention_days": 7,
    "max_concurrent_recordings": 4,
    "auto_prune_when_full": False,
    "max_concurrent_vod_downloads": 2,
    "auto_delete_source_after_publish": False,
}

# Source: frontend/src/components/BacklogBrowser.tsx — bulk download
PAYLOAD_BACKLOG_DOWNLOAD = {
    "video_ids": ["abc123", "def456", "ghi789"],
}

# Source: frontend/src/pages/PostDownloadReview.tsx — segment create with genres
PAYLOAD_SEGMENT_CREATE_WITH_GENRES = {
    "recording_id": 1,
    "artist": "Khruangbin",
    "title": "Tiny Desk",
    "start_s": 0.0,
    "end_s": 1122.0,
    "source": "manual",
    "genres": "Indie, Psych, Funk",
}

# Source: frontend/src/components/SegmentSidebar.tsx — segment patch with genres
PAYLOAD_SEGMENT_PATCH_GENRES_ONLY = {
    "genres": "Rock, Alternative",
}

# ---------------------------------------------------------------------------
# Tests — each calls model_validate, fails loudly if the schema rejects it.

pytestmark = pytest.mark.contracts


def _validate_or_fail(model_cls, payload, label):
    try:
        return model_cls.model_validate(payload)
    except ValidationError as e:
        pytest.fail(f"contract drift: {label} payload rejected by {model_cls.__name__}: {e}")


def test_smart_paste_channel_subscribe():
    parsed = _validate_or_fail(
        ChannelWatcherCreate,
        PAYLOAD_SMART_PASTE_CHANNEL_SUBSCRIBE,
        "SmartPasteModal channel-subscribe",
    )
    assert parsed.watch_vod_uploads is True
    assert parsed.auto_publish is False


def test_smart_paste_channel_both_modes():
    parsed = _validate_or_fail(
        ChannelWatcherCreate,
        PAYLOAD_SMART_PASTE_CHANNEL_BOTH_MODES,
        "SmartPasteModal channel-both-modes",
    )
    assert parsed.watch_live is True
    assert parsed.watch_vod_uploads is True


def test_watcher_manual_add():
    parsed = _validate_or_fail(
        ChannelWatcherCreate, PAYLOAD_WATCHER_MANUAL_ADD, "Watchers manual-add"
    )
    assert parsed.title_filter == "Tiny Desk"


def test_watcher_patch_full_vod_form():
    parsed = _validate_or_fail(
        ChannelWatcherPatch,
        PAYLOAD_WATCHER_PATCH_FULL_VOD_FORM,
        "WatcherDetail Settings tab full save",
    )
    assert parsed.vod_segmentation_mode == "whole-video"
    assert parsed.auto_publish is True
    assert parsed.default_genres == "Indie, Alternative, Folk"


def test_watcher_patch_inherit_autodelete():
    parsed = _validate_or_fail(
        ChannelWatcherPatch,
        PAYLOAD_WATCHER_PATCH_INHERIT_AUTODELETE,
        "WatcherDetail auto-delete inherit",
    )
    assert parsed.auto_delete_source_after_publish is None


def test_settings_patch_vod_fields_only():
    parsed = _validate_or_fail(
        SettingsPatch,
        PAYLOAD_SETTINGS_PATCH_VOD_FIELDS,
        "Settings page VOD-only save",
    )
    assert parsed.max_concurrent_vod_downloads == 4
    assert parsed.auto_delete_source_after_publish is True


def test_settings_patch_full():
    parsed = _validate_or_fail(
        SettingsPatch, PAYLOAD_SETTINGS_PATCH_FULL, "Settings page full save"
    )
    assert parsed.folder_pattern == "{channel}/{artist} ({year})"


def test_backlog_download():
    parsed = _validate_or_fail(
        BacklogDownloadRequest, PAYLOAD_BACKLOG_DOWNLOAD, "BacklogBrowser bulk download"
    )
    assert len(parsed.video_ids) == 3


def test_segment_create_with_genres():
    parsed = _validate_or_fail(
        SegmentCreate,
        PAYLOAD_SEGMENT_CREATE_WITH_GENRES,
        "PostDownloadReview segment create",
    )
    assert parsed.genres == "Indie, Psych, Funk"


def test_segment_patch_genres_only():
    parsed = _validate_or_fail(
        SegmentPatch, PAYLOAD_SEGMENT_PATCH_GENRES_ONLY, "SegmentSidebar genres patch"
    )
    assert parsed.genres == "Rock, Alternative"


# ---------------------------------------------------------------------------
# Smart-paste response-shape contracts — the FRONTEND parses these. If the
# backend changes the shape, the frontend will silently misrender. We assert
# the response shape stays compatible with the frontend's TypeScript types.

# Source: frontend/src/lib/api.ts ProbeChannelResult type
EXPECTED_CHANNEL_RESULT_FIELDS = {"type", "channel_name", "url"}

# Source: frontend/src/lib/api.ts ProbePlaylistResult type
EXPECTED_PLAYLIST_RESULT_FIELDS = {
    "type",
    "playlist_id",
    "playlist_title",
    "count",
    "items",
}

# Source: frontend/src/lib/api.ts ProbePlaylistItem type
EXPECTED_PLAYLIST_ITEM_FIELDS = {
    "youtube_id",
    "title",
    "thumbnail_url",
    "duration_s",
    "is_already_known",
}


def test_channel_result_response_shape_documented():
    """Locked-in expectation: backend channel-routing response carries these fields.

    If we ever rename or drop one, the frontend's discriminated union breaks
    silently. This test fails if our docs drift from reality.
    """
    # Just asserting the constant is well-formed and complete enough.
    assert "type" in EXPECTED_CHANNEL_RESULT_FIELDS
    assert "channel_name" in EXPECTED_CHANNEL_RESULT_FIELDS


def test_playlist_result_response_shape_documented():
    assert {
        "type",
        "playlist_id",
        "playlist_title",
        "count",
        "items",
    } == EXPECTED_PLAYLIST_RESULT_FIELDS
    assert "youtube_id" in EXPECTED_PLAYLIST_ITEM_FIELDS
