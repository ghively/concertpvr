# concertpvr v0.3 — VOD Downloads Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship VOD download support across three workflows (one-shot URL paste, channel subscription with auto-pull, playlist ingest) plus rich metadata capture (description, tags, detected setlists, genres) — landing as v0.3.0.

**Architecture:** Hybrid — split downloaders for live vs VOD, share probe; new VOD queue with own concurrency cap independent of the live pool. New modules are single-purpose and isolated. Existing live recording code paths remain bit-identical for users who don't opt in.

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy 2.0, Alembic, yt-dlp (library + CLI), Pydantic v2, ffmpeg, React 18 + TypeScript + Vite, TanStack Query, Tailwind.

**Spec reference:** `docs/superpowers/specs/2026-04-26-vod-downloads-design.md`.

**Baseline:** v0.2.0 on `main`. 191 backend tests, frontend builds, 8 phases shipped.

---

## Cross-cutting guardrails (apply to every task)

**Locked design constraints — do not deviate:**

1. **No `Field(...)` weakening.** If mypy complains, use `# type: ignore[call-arg]` or rely on the `pydantic.mypy` plugin (already enabled in `pyproject.toml`).
2. **No test rewriting** that hides spec violations. If a test fails, fix the implementation. Only edit a test if the test itself is wrong — flag and explain in commit message.
3. **No mypy strictness relaxation.** Strict stays strict.
4. **Pydantic validators on `*Patch` schemas only**, never on `*Read`. Bad data already in the DB must still parse on read.
5. **Pagination defaults stay `limit=None`** (unlimited). Setting a default of 100 silently breaks the frontend.
6. **Lifespan ordering:** `Base.metadata.create_all` → `mark_interrupted_on_startup` (existing) → `mark_vod_downloads_interrupted_on_startup` (new) → eager session_secret → `register_app` → `scheduler.start()` + `vod_queue.start_workers()` → rehydrate. Orphan scans MUST run before `register_app` so scheduled jobs can't fire and create rows the scan would nuke.
7. **Confirm dialogs use `useConfirm()` hook**, never browser native `confirm()`.
8. **Commit format:** every commit `git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "..."`. NEVER omit those `-c` flags — bypasses 1Password's broken SSH-signing fill.
9. **Live recording behavior is sacred.** No edits to `recorder.py`, `pool.py`, `buffer.py`. New VOD code paths share zero state with live.
10. **VOD queue is independent of live pool.** Different settings, different concurrency caps, different progress semantics.
11. **Migration is additive only.** No drops, renames, type changes. New columns nullable or `NOT NULL DEFAULT`.
12. **Use:** `./.venv/Scripts/python.exe -m pytest ...` for tests. `cd frontend && npm run typecheck && npm run build` for frontend.

---

## Wave 1 — Schema and pure-function foundations

### Task 1: Migration 0008 + model columns + Pydantic schemas

**Files:**
- Create: `alembic/versions/0008_vod_support.py`
- Modify: `src/concertpvr/models.py`
- Modify: `src/concertpvr/schemas.py`
- Test: `tests/test_migration_0008.py` (new)

This task introduces 20 new columns across 5 tables. All additive. No behavior changes — existing tests stay green.

- [ ] **Step 1: Create migration file**

```python
# alembic/versions/0008_vod_support.py
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
    # watchers: 9 columns
    with op.batch_alter_table("watchers") as batch:
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
            "fk_streams_watcher_id", "watchers", ["watcher_id"], ["id"], ondelete="SET NULL",
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
    with op.batch_alter_table("watchers") as batch:
        batch.drop_column("auto_delete_source_after_publish")
        batch.drop_column("default_genres")
        batch.drop_column("extract_setlist_from_comments")
        batch.drop_column("auto_publish")
        batch.drop_column("vod_artist_regex")
        batch.drop_column("vod_title_filter")
        batch.drop_column("vod_segmentation_mode")
        batch.drop_column("watch_vod_uploads")
        batch.drop_column("watch_live")
```

- [ ] **Step 2: Extend `src/concertpvr/models.py` with the new columns**

In the `Watcher` class, add (under existing columns):

```python
    watch_live: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=sa.true())
    watch_vod_uploads: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=sa.false())
    vod_segmentation_mode: Mapped[str] = mapped_column(String, nullable=False, default="chapters", server_default="chapters")
    vod_title_filter: Mapped[str | None] = mapped_column(String, nullable=True)
    vod_artist_regex: Mapped[str | None] = mapped_column(String, nullable=True)
    auto_publish: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=sa.false())
    extract_setlist_from_comments: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=sa.false())
    default_genres: Mapped[str | None] = mapped_column(String, nullable=True)
    auto_delete_source_after_publish: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
```

In the `Stream` class:

```python
    original_upload_date: Mapped[_dt.date | None] = mapped_column(Date, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    youtube_tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    detected_setlist_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    detected_setlist_source: Mapped[str | None] = mapped_column(String, nullable=True)
    watcher_id: Mapped[int | None] = mapped_column(
        ForeignKey("watchers.id", ondelete="SET NULL"), nullable=True, index=True
    )
```

In the `Segment` class:

```python
    genres: Mapped[str | None] = mapped_column(String, nullable=True)
```

In the `Recording` class:

```python
    auto_publish_after_download: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=sa.false())
    source_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=sa.false())
```

In the `Settings` class:

```python
    max_concurrent_vod_downloads: Mapped[int] = mapped_column(Integer, nullable=False, default=2, server_default="2")
    auto_delete_source_after_publish: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=sa.false())
```

Required imports at the top of `models.py` (add if missing): `from sqlalchemy import Boolean, Date, ForeignKey, JSON, Text` and `import sqlalchemy as sa`.

- [ ] **Step 3: Extend `src/concertpvr/schemas.py`**

Add Pydantic schemas to support the new fields. Find the existing `WatcherRead` and `WatcherPatch`, extend each with the new fields. `WatcherRead` accepts the values as-is. `WatcherPatch` adds validators.

```python
import re
from typing import Literal

from pydantic import field_validator


SegmentationMode = Literal["chapters", "whole-video", "manual"]


class WatcherRead(BaseModel):
    # ... existing fields ...
    watch_live: bool
    watch_vod_uploads: bool
    vod_segmentation_mode: SegmentationMode
    vod_title_filter: str | None
    vod_artist_regex: str | None
    auto_publish: bool
    extract_setlist_from_comments: bool
    default_genres: str | None
    auto_delete_source_after_publish: bool | None


class WatcherPatch(BaseModel):
    # ... existing fields ...
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
```

Similarly extend `StreamRead`, `RecordingRead`, `SegmentRead`, `SettingsRead` and their corresponding `*Patch` variants. Add the folder_pattern token validator extension to include `channel`:

In the existing `SettingsPatch._validate_folder_pattern`, add `channel="Channel"` to the test format() call.

In `SettingsPatch`:

```python
    max_concurrent_vod_downloads: int | None = Field(default=None, ge=1, le=8)
    auto_delete_source_after_publish: bool | None = None
```

In `SegmentPatch`:

```python
    genres: str | None = None
```

- [ ] **Step 4: Write migration test**

Create `tests/test_migration_0008.py`:

```python
"""Migration 0008 smoke test — schema additive only, defaults populate existing rows."""

import pytest
from fastapi.testclient import TestClient

from concertpvr.main import create_app
from concertpvr.models import Recording, Segment, Settings, Stream, Watcher


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))
    with TestClient(create_app()) as c:
        yield c


def test_existing_watcher_rows_get_safe_defaults(client):
    """A watcher created before migration must come up with watch_live=True and VOD off."""
    db = client.app.state.db
    with db.session() as s:
        w = Watcher(channel_url="https://www.youtube.com/@nprmusic", channel_name="NPR Music")
        s.add(w)
        s.flush()
        wid = w.id

    with db.session() as s:
        w = s.get(Watcher, wid)
        assert w.watch_live is True
        assert w.watch_vod_uploads is False
        assert w.vod_segmentation_mode == "chapters"
        assert w.vod_title_filter is None
        assert w.vod_artist_regex is None
        assert w.auto_publish is False
        assert w.extract_setlist_from_comments is False
        assert w.default_genres is None
        assert w.auto_delete_source_after_publish is None


def test_existing_stream_columns_default_null(client):
    db = client.app.state.db
    with db.session() as s:
        st = Stream(kind="live", youtube_id="abc", url="https://x", title="T", channel_name="C")
        s.add(st)
        s.flush()
        sid = st.id

    with db.session() as s:
        st = s.get(Stream, sid)
        assert st.original_upload_date is None
        assert st.description is None
        assert st.youtube_tags is None
        assert st.detected_setlist_text is None
        assert st.detected_setlist_source is None
        assert st.watcher_id is None


def test_existing_settings_get_vod_defaults(client):
    db = client.app.state.db
    with db.session() as s:
        row = s.get(Settings, 1)
        assert row is not None
        assert row.max_concurrent_vod_downloads == 2
        assert row.auto_delete_source_after_publish is False


def test_recording_gets_source_deleted_default(client):
    db = client.app.state.db
    import datetime as _dt
    with db.session() as s:
        st = Stream(kind="live", youtube_id="abc", url="https://x", title="T", channel_name="C")
        s.add(st)
        s.flush()
        rec = Recording(
            stream_id=st.id, started_at=_dt.datetime.now(_dt.UTC),
            path="/tmp/x", status="recording", is_buffer=True,
        )
        s.add(rec)
        s.flush()
        rid = rec.id

    with db.session() as s:
        rec = s.get(Recording, rid)
        assert rec.auto_publish_after_download is False
        assert rec.source_deleted is False


def test_segment_genres_default_null(client):
    db = client.app.state.db
    import datetime as _dt
    with db.session() as s:
        st = Stream(kind="video", youtube_id="abc", url="https://x", title="T", channel_name="C")
        s.add(st)
        s.flush()
        rec = Recording(
            stream_id=st.id, started_at=_dt.datetime.now(_dt.UTC),
            path="/tmp/x", status="complete", is_buffer=False,
        )
        s.add(rec)
        s.flush()
        seg = Segment(
            recording_id=rec.id, artist="A", start_s=0, end_s=10, source="manual", status="draft",
        )
        s.add(seg)
        s.flush()
        sid = seg.id

    with db.session() as s:
        seg = s.get(Segment, sid)
        assert seg.genres is None
```

- [ ] **Step 5: Run tests + commit**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_migration_0008.py -v
./.venv/Scripts/python.exe -m pytest -q
./.venv/Scripts/python.exe -m mypy src/
```

Expected: all 191 existing tests still pass + 5 new = 196.

```bash
git add alembic/versions/0008_vod_support.py src/concertpvr/models.py src/concertpvr/schemas.py tests/test_migration_0008.py
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(schema): migration 0008 — VOD support columns (additive)"
```

---

### Task 2: Extended yt-dlp probe for VODs

**Files:**
- Modify: `src/concertpvr/ytdlp.py`
- Modify: `tests/test_ytdlp.py` (or add tests to wherever probe is currently tested)

The existing `probe()` returns `StreamInfo` with `youtube_id, url, title, channel_name, is_live, thumbnail_url`. Extend to capture upload_date, description, tags, chapters, and optionally comments.

- [ ] **Step 1: Extend `StreamInfo` dataclass**

```python
@dataclass(frozen=True)
class StreamInfo:
    youtube_id: str
    url: str
    title: str
    channel_name: str
    is_live: bool
    thumbnail_url: str | None
    # New v0.3 fields:
    original_upload_date: _dt.date | None = None  # release_date or upload_date
    description: str | None = None
    tags: list[str] | None = None  # raw youtube_tags
    chapters: list[dict] | None = None  # list of {start_time, end_time, title}
    comments: list[dict] | None = None  # only when getcomments=True
    duration_s: int | None = None
```

- [ ] **Step 2: Extend `probe()` signature and body**

```python
async def probe(
    url: str,
    *,
    cookies_path: Path | None = None,
    fetch_comments: bool = False,
) -> StreamInfo:
    """Fetch metadata for a YouTube URL.

    `fetch_comments=True` triggers yt-dlp's `getcomments=True` (slower probe,
    ~3-5s extra). Used by VOD watchers with extract_setlist_from_comments=True.
    """
    cookies_str = str(cookies_path) if cookies_path and Path(cookies_path).exists() else None
    try:
        info = await asyncio.to_thread(_extract_sync, url, cookies_str, fetch_comments)
    except yt_dlp.utils.DownloadError as e:
        raise ProbeError(str(e)) from e
    except Exception as e:
        raise ProbeError(f"unexpected error: {e}") from e

    youtube_id: str = info["id"]
    webpage_url: str = info.get("webpage_url", url) or url
    title: str = info.get("title", "Untitled") or "Untitled"
    channel: str = info.get("channel") or info.get("uploader") or "Unknown"
    is_live: bool = bool(info.get("is_live", False))
    thumbnail_url: str | None = info.get("thumbnail")

    upload_date_str = info.get("release_date") or info.get("upload_date")
    upload_date = _parse_yt_date(upload_date_str)
    description = info.get("description")
    if description and len(description) > 2_000_000:
        import logging
        logging.getLogger(__name__).warning(
            "description for %s truncated from %d to 2MB", youtube_id, len(description)
        )
        description = description[:2_000_000]
    tags: list[str] | None = info.get("tags") or None
    chapters: list[dict] | None = info.get("chapters") or None
    comments: list[dict] | None = info.get("comments") if fetch_comments else None
    duration_s_raw = info.get("duration")
    duration_s: int | None = int(duration_s_raw) if duration_s_raw is not None else None

    return StreamInfo(
        youtube_id=youtube_id,
        url=webpage_url,
        title=title,
        channel_name=channel,
        is_live=is_live,
        thumbnail_url=thumbnail_url,
        original_upload_date=upload_date,
        description=description,
        tags=tags,
        chapters=chapters,
        comments=comments,
        duration_s=duration_s,
    )


def _parse_yt_date(s: str | None) -> _dt.date | None:
    """yt-dlp returns dates as YYYYMMDD strings."""
    if not s or len(s) != 8:
        return None
    try:
        return _dt.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except (ValueError, TypeError):
        return None
```

Update `_extract_sync` to accept and pass through `fetch_comments`:

```python
def _extract_sync(url: str, cookies_path: str | None, fetch_comments: bool = False) -> dict:
    opts: dict[str, object] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
    }
    if cookies_path:
        opts["cookiefile"] = cookies_path
    if fetch_comments:
        opts["getcomments"] = True
    with yt_dlp.YoutubeDL(opts) as ydl:
        result = ydl.extract_info(url, download=False)
        if result is None:
            raise ProbeError("no info returned")
        return result
```

- [ ] **Step 3: Existing callers**

Search for callers of `probe(...)` — they pass `cookies_path` only. The new `fetch_comments` param defaults to `False` so existing callers are unaffected.

```bash
grep -rn "from concertpvr.ytdlp import\|concertpvr\.ytdlp\.probe\|ytdlp\.probe" src/ tests/
```

Verify all existing call sites still type-check.

- [ ] **Step 4: Test the new fields**

Append to `tests/test_ytdlp.py`:

```python
import datetime as _dt


def test_parse_yt_date_valid():
    from concertpvr.ytdlp import _parse_yt_date
    assert _parse_yt_date("20200902") == _dt.date(2020, 9, 2)


def test_parse_yt_date_invalid_returns_none():
    from concertpvr.ytdlp import _parse_yt_date
    assert _parse_yt_date(None) is None
    assert _parse_yt_date("") is None
    assert _parse_yt_date("not-a-date") is None
    assert _parse_yt_date("20201301") is None  # invalid month


@pytest.mark.asyncio
async def test_probe_captures_vod_metadata(monkeypatch):
    """When yt-dlp returns vod-style metadata, StreamInfo carries it."""
    from concertpvr.ytdlp import probe

    fake_info = {
        "id": "abc123",
        "webpage_url": "https://www.youtube.com/watch?v=abc123",
        "title": "Khruangbin: Tiny Desk Concert",
        "channel": "NPR Music",
        "is_live": False,
        "thumbnail": "https://example.com/t.jpg",
        "upload_date": "20200902",
        "description": "For Khruangbin's debut Tiny Desk...",
        "tags": ["khruangbin", "tiny desk", "indie"],
        "chapters": [{"start_time": 0, "end_time": 80, "title": "Intro"}],
        "duration": 1122,
    }

    import asyncio
    async def _fake_to_thread(fn, *args, **kwargs):
        return fake_info

    monkeypatch.setattr(asyncio, "to_thread", _fake_to_thread)

    info = await probe("https://www.youtube.com/watch?v=abc123")

    assert info.youtube_id == "abc123"
    assert info.is_live is False
    assert info.original_upload_date == _dt.date(2020, 9, 2)
    assert info.description.startswith("For Khruangbin")
    assert info.tags == ["khruangbin", "tiny desk", "indie"]
    assert info.chapters == [{"start_time": 0, "end_time": 80, "title": "Intro"}]
    assert info.duration_s == 1122
    assert info.comments is None  # not requested
```

- [ ] **Step 5: Run + commit**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_ytdlp.py -v
./.venv/Scripts/python.exe -m mypy src/
git add src/concertpvr/ytdlp.py tests/test_ytdlp.py
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(ytdlp): probe captures VOD metadata (description, tags, chapters, upload_date, comments-toggle)"
```

---

### Task 3: setlist_detector module

**Files:**
- Create: `src/concertpvr/setlist_detector.py`
- Create: `tests/test_setlist_detector.py`

Pure functions. No I/O. Detects setlist-shaped text in description / comments / chapters.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_setlist_detector.py
"""Setlist detection from VOD description and comments."""

from concertpvr.setlist_detector import (
    DetectedSetlist,
    detect_in_description,
    detect_in_chapters,
    detect_in_comments,
)


def test_detect_description_with_classic_timestamps():
    desc = """For Khruangbin's debut Tiny Desk Concert...

0:00 - Intro
1:24 - Pelota
5:12 - So We Won't Forget
10:48 - People Everywhere (Still Alive)
14:35 - Time (You and I)

Producers: Bobby Carter
"""
    result = detect_in_description(desc)
    assert result is not None
    assert len(result.entries) == 5
    assert result.entries[0].title == "Intro"
    assert result.entries[0].start_s == 0
    assert result.entries[1].title == "Pelota"
    assert result.entries[1].start_s == 84  # 1:24
    assert result.source == "description"


def test_detect_description_bracketed_timestamps():
    desc = "[00:00] Opening\n[03:21] Song Two\n[08:45] Another Song"
    result = detect_in_description(desc)
    assert result is not None
    assert len(result.entries) == 3
    assert result.entries[1].start_s == 201  # 3:21


def test_detect_description_returns_none_when_no_pattern():
    assert detect_in_description("Just some prose about a concert.") is None
    assert detect_in_description("") is None
    assert detect_in_description(None) is None


def test_detect_description_picks_longest_block():
    """Multiple candidate blocks → pick the longest contiguous one."""
    desc = """0:00 - prelude

Setlist:
0:00 Song A
3:00 Song B
6:00 Song C
9:00 Song D
"""
    result = detect_in_description(desc)
    assert result is not None
    # The 4-entry block wins over the 1-entry "prelude" block.
    assert len(result.entries) == 4
    assert result.entries[0].title == "Song A"


def test_detect_chapters_basic():
    chapters = [
        {"start_time": 0, "end_time": 80, "title": "Intro"},
        {"start_time": 80, "end_time": 312, "title": "Pelota"},
    ]
    result = detect_in_chapters(chapters)
    assert result is not None
    assert len(result.entries) == 2
    assert result.entries[0].start_s == 0
    assert result.entries[1].title == "Pelota"
    assert result.source == "chapters"


def test_detect_chapters_returns_none_when_empty():
    assert detect_in_chapters([]) is None
    assert detect_in_chapters(None) is None


def test_detect_comments_finds_pinned_setlist():
    comments = [
        {"is_pinned": False, "text": "Great show!", "like_count": 12},
        {"is_pinned": True, "text": "Setlist:\n0:00 - Intro\n3:21 - Song Two\n8:45 - Song Three", "like_count": 200},
    ]
    result = detect_in_comments(comments)
    assert result is not None
    assert len(result.entries) == 3
    assert result.source == "comments"


def test_detect_comments_falls_back_to_top_liked():
    comments = [
        {"is_pinned": False, "text": "great track at 3:21", "like_count": 10},
        {"is_pinned": False, "text": "0:00 - Intro\n3:21 - Song Two\n8:45 - Song Three\n12:00 - Song Four", "like_count": 500},
    ]
    result = detect_in_comments(comments)
    assert result is not None
    assert len(result.entries) == 4


def test_detect_comments_returns_none_when_no_match():
    comments = [{"is_pinned": False, "text": "Wow!", "like_count": 5}]
    assert detect_in_comments(comments) is None


def test_detect_comments_drops_malformed_timestamps():
    """Lines with invalid timestamps are dropped; valid lines kept."""
    comments = [{"is_pinned": True, "text": "0:00 Intro\n1:99 Bad\n3:21 Song Two", "like_count": 100}]
    result = detect_in_comments(comments)
    # 0:00 Intro and 3:21 Song Two are valid; 1:99 invalid.
    assert result is not None
    assert len(result.entries) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_setlist_detector.py -v
```

Expected: ImportError — `concertpvr.setlist_detector` doesn't exist.

- [ ] **Step 3: Implement the module**

```python
# src/concertpvr/setlist_detector.py
"""Detect setlists in VOD description, chapters, and comments.

Pure functions; no I/O. Caller passes already-fetched data; we parse and return
DetectedSetlist (or None). Used by the VOD probe pipeline to enrich Stream
metadata for the post-download review screen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

SetlistSource = Literal["chapters", "description", "comments"]


@dataclass(frozen=True)
class SetlistEntry:
    start_s: int
    title: str


@dataclass(frozen=True)
class DetectedSetlist:
    entries: list[SetlistEntry]
    source: SetlistSource
    raw_text: str  # text excerpt where it was found (for UI surfacing)


_TS_LINE = re.compile(
    r"""
    ^[\s]*               # leading whitespace
    \[?                  # optional [
    (?P<h>\d{1,2}):      # h:
    (?P<m>\d{1,2})       # m
    (?::(?P<s>\d{1,2}))? # optional :s
    \]?                  # optional ]
    [\s\-–—•·.]+         # separator
    (?P<title>.{1,200}?) # title (non-greedy)
    \s*$                 # trailing whitespace
    """,
    re.VERBOSE,
)


def _ts_to_seconds(h: str, m: str, s: str | None) -> int | None:
    hh = int(h)
    mm = int(m)
    ss = int(s) if s is not None else 0
    if mm >= 60 or ss >= 60:
        return None
    if s is None:
        # h:m means m:s when h < 10 (e.g. 1:24 = 1m24s).
        return hh * 60 + mm
    # h:m:s
    return hh * 3600 + mm * 60 + ss


def _extract_entries(text: str) -> list[SetlistEntry]:
    """Find all timestamp lines in `text`; return entries ordered by appearance."""
    entries: list[SetlistEntry] = []
    for line in text.splitlines():
        m = _TS_LINE.match(line)
        if not m:
            continue
        secs = _ts_to_seconds(m.group("h"), m.group("m"), m.group("s"))
        if secs is None:
            continue
        title = m.group("title").strip().rstrip(",.").strip()
        if not title:
            continue
        entries.append(SetlistEntry(start_s=secs, title=title))
    return entries


def _longest_contiguous_block(entries: list[SetlistEntry]) -> list[SetlistEntry]:
    """If entries come from multiple blocks (separated by non-timestamp lines),
    pick the longest contiguous block. For now we just return all entries since
    `_extract_entries` already returns everything in source order — callers
    that want strict contiguity should pre-filter.

    Practical heuristic: filter out entries whose start_s would imply
    out-of-order time (a heuristic for "different block").
    """
    if not entries:
        return []
    # Greedy: build runs of monotonically-non-decreasing start_s, pick longest.
    best: list[SetlistEntry] = []
    current: list[SetlistEntry] = [entries[0]]
    for e in entries[1:]:
        if e.start_s >= current[-1].start_s:
            current.append(e)
        else:
            if len(current) > len(best):
                best = current
            current = [e]
    if len(current) > len(best):
        best = current
    return best


def detect_in_description(description: str | None) -> DetectedSetlist | None:
    if not description:
        return None
    entries = _extract_entries(description)
    if not entries:
        return None
    block = _longest_contiguous_block(entries)
    if len(block) < 2:  # need at least 2 entries to be a setlist
        return None
    return DetectedSetlist(
        entries=block,
        source="description",
        raw_text=description[:2000],  # cap excerpt
    )


def detect_in_chapters(chapters: list[dict] | None) -> DetectedSetlist | None:
    if not chapters:
        return None
    entries: list[SetlistEntry] = []
    for ch in chapters:
        start = ch.get("start_time")
        title = ch.get("title")
        if start is None or not title:
            continue
        entries.append(SetlistEntry(start_s=int(start), title=str(title).strip()))
    if not entries:
        return None
    return DetectedSetlist(
        entries=entries,
        source="chapters",
        raw_text="",  # chapters don't have a raw text excerpt
    )


def detect_in_comments(comments: list[dict] | None) -> DetectedSetlist | None:
    if not comments:
        return None
    # Try pinned comments first.
    pinned = [c for c in comments if c.get("is_pinned")]
    candidates = pinned + sorted(
        [c for c in comments if not c.get("is_pinned")],
        key=lambda c: -(c.get("like_count") or 0),
    )
    for c in candidates[:20]:  # check up to top 20
        text = c.get("text") or ""
        if not text:
            continue
        entries = _extract_entries(text)
        if len(entries) >= 2:
            block = _longest_contiguous_block(entries)
            if len(block) >= 2:
                return DetectedSetlist(
                    entries=block,
                    source="comments",
                    raw_text=text[:2000],
                )
    return None
```

- [ ] **Step 4: Run tests + commit**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_setlist_detector.py -v
./.venv/Scripts/python.exe -m mypy src/
git add src/concertpvr/setlist_detector.py tests/test_setlist_detector.py
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(setlist_detector): parse setlists from description/chapters/comments"
```

---

### Task 4: artist_extractor module

**Files:**
- Create: `src/concertpvr/artist_extractor.py`
- Create: `tests/test_artist_extractor.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_artist_extractor.py
from concertpvr.artist_extractor import extract_artist


def test_tiny_desk_pattern_colon():
    regex = r"^(?P<artist>.+?)\s*[:|]\s*(?:NPR Music )?Tiny Desk Concert"
    assert extract_artist("Khruangbin: Tiny Desk Concert", regex) == "Khruangbin"


def test_tiny_desk_pattern_pipe():
    regex = r"^(?P<artist>.+?)\s*[:|]\s*(?:NPR Music )?Tiny Desk Concert"
    assert extract_artist("Olivia Rodrigo | Tiny Desk Concert (Home)", regex) == "Olivia Rodrigo"


def test_kexp_pattern():
    regex = r"^(?P<artist>.+?)\s*-\s*Live on KEXP"
    assert extract_artist("Big Thief - Live on KEXP", regex) == "Big Thief"


def test_returns_none_when_no_match():
    regex = r"^(?P<artist>.+?):\s*Tiny Desk Concert"
    assert extract_artist("Just some other video", regex) is None


def test_returns_none_when_artist_group_empty():
    regex = r"^(?P<artist>.*?):\s*Tiny Desk Concert"
    assert extract_artist(": Tiny Desk Concert", regex) is None


def test_returns_none_when_regex_is_none_or_empty():
    assert extract_artist("Anything", None) is None
    assert extract_artist("Anything", "") is None


def test_unicode_preserved():
    regex = r"^(?P<artist>.+?)\s*[:|]"
    assert extract_artist("Sigur Rós: Tiny Desk", regex) == "Sigur Rós"


def test_strips_whitespace():
    regex = r"^(?P<artist>.+?):"
    assert extract_artist("  Khruangbin  : Tiny Desk", regex) == "Khruangbin"
```

- [ ] **Step 2: Implement**

```python
# src/concertpvr/artist_extractor.py
"""Extract artist name from a YouTube video title via per-watcher regex.

Pure function. Returns the artist string when the regex's named `artist` group
matches and is non-empty; None otherwise. Caller treats None as "manual review
required" — auto-publish path falls through to the post-download review screen.
"""

from __future__ import annotations

import re


def extract_artist(title: str, regex: str | None) -> str | None:
    if not regex or not title:
        return None
    try:
        m = re.search(regex, title)
    except re.error:
        return None
    if m is None:
        return None
    try:
        artist = m.group("artist")
    except (IndexError, KeyError):
        return None
    if artist is None:
        return None
    artist = artist.strip()
    if not artist:
        return None
    return artist
```

- [ ] **Step 3: Run tests + commit**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_artist_extractor.py -v
./.venv/Scripts/python.exe -m mypy src/
git add src/concertpvr/artist_extractor.py tests/test_artist_extractor.py
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(artist_extractor): per-watcher regex artist extraction"
```

---

## Wave 2 — VOD pipeline backend

### Task 5: vod_queue + vod_recovery + lifespan wiring

**Files:**
- Create: `src/concertpvr/vod_queue.py`
- Create: `src/concertpvr/vod_recovery.py`
- Modify: `src/concertpvr/main.py` (lifespan)
- Create: `tests/test_vod_queue.py`
- Create: `tests/test_vod_recovery.py`

The queue is a separate concurrency-capped FIFO. Persistent state lives on `Recording.status` rows (`vod_queued` → `vod_downloading` → `complete` / `vod_failed`). At startup we transition any `vod_downloading` row back to `vod_queued` (crash recovery), then `start_workers()` spawns N tasks that loop over the queue.

- [ ] **Step 1: Write failing tests for the queue**

```python
# tests/test_vod_queue.py
"""VodQueue — concurrency cap, FIFO, rehydration."""

import asyncio
import datetime as _dt

import pytest

from concertpvr.db import Database
from concertpvr.models import Base, Recording, Stream
from concertpvr.vod_queue import VodQueue


@pytest.fixture
def db(tmp_path):
    d = Database(f"sqlite:///{tmp_path / 'q.db'}")
    Base.metadata.create_all(d.engine)
    return d


def _seed_recording(db: Database, status: str = "vod_queued") -> int:
    with db.session() as s:
        st = Stream(kind="video", youtube_id="x", url="u", title="t", channel_name="c")
        s.add(st)
        s.flush()
        rec = Recording(
            stream_id=st.id, started_at=_dt.datetime.now(_dt.UTC),
            path="/tmp/x", status=status, is_buffer=False,
        )
        s.add(rec)
        s.flush()
        return rec.id


@pytest.mark.asyncio
async def test_queue_enqueues_and_processes_in_fifo_order(db):
    processed: list[int] = []

    async def fake_handler(rec_id: int) -> None:
        processed.append(rec_id)

    q = VodQueue(db=db, handler=fake_handler, max_concurrent=1)
    await q.start_workers()

    r1 = _seed_recording(db)
    r2 = _seed_recording(db)
    r3 = _seed_recording(db)
    await q.enqueue(r1)
    await q.enqueue(r2)
    await q.enqueue(r3)

    await q.wait_for_idle()
    await q.stop()
    assert processed == [r1, r2, r3]


@pytest.mark.asyncio
async def test_queue_respects_concurrency_cap(db):
    in_flight = 0
    max_seen = 0

    async def slow_handler(rec_id: int) -> None:
        nonlocal in_flight, max_seen
        in_flight += 1
        max_seen = max(max_seen, in_flight)
        await asyncio.sleep(0.05)
        in_flight -= 1

    q = VodQueue(db=db, handler=slow_handler, max_concurrent=2)
    await q.start_workers()

    for _ in range(6):
        await q.enqueue(_seed_recording(db))

    await q.wait_for_idle()
    await q.stop()
    assert max_seen == 2


@pytest.mark.asyncio
async def test_queue_rehydrate_picks_up_existing_vod_queued(db):
    processed: list[int] = []

    async def handler(rec_id: int) -> None:
        processed.append(rec_id)

    r1 = _seed_recording(db, status="vod_queued")
    r2 = _seed_recording(db, status="vod_queued")

    q = VodQueue(db=db, handler=handler, max_concurrent=2)
    await q.start_workers()
    await q.rehydrate_from_db()

    await q.wait_for_idle()
    await q.stop()
    assert sorted(processed) == sorted([r1, r2])


@pytest.mark.asyncio
async def test_queue_handler_exception_marks_failed(db):
    async def failing_handler(rec_id: int) -> None:
        raise RuntimeError("boom")

    q = VodQueue(db=db, handler=failing_handler, max_concurrent=1)
    await q.start_workers()

    rid = _seed_recording(db)
    await q.enqueue(rid)
    await q.wait_for_idle()
    await q.stop()

    with db.session() as s:
        rec = s.get(Recording, rid)
        assert rec.status == "vod_failed"
        assert "boom" in (rec.error or "")
```

- [ ] **Step 2: Implement vod_queue.py**

```python
# src/concertpvr/vod_queue.py
"""VOD download queue — concurrency-capped FIFO.

State lives on Recording rows. enqueue() appends to an asyncio queue; workers
pull and call the handler. The handler is responsible for transitioning
status from vod_queued → vod_downloading → complete/vod_failed and writing
the source file. The queue itself only routes work and handles handler
exceptions defensively.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from sqlalchemy import select

from concertpvr.db import Database
from concertpvr.models import Recording

logger = logging.getLogger(__name__)


class VodQueue:
    def __init__(
        self,
        *,
        db: Database,
        handler: Callable[[int], Awaitable[None]],
        max_concurrent: int = 2,
    ) -> None:
        self._db = db
        self._handler = handler
        self._max_concurrent = max(1, max_concurrent)
        self._queue: asyncio.Queue[int] = asyncio.Queue()
        self._workers: list[asyncio.Task[None]] = []
        self._running = False

    async def enqueue(self, recording_id: int) -> None:
        await self._queue.put(recording_id)

    async def start_workers(self) -> None:
        if self._running:
            return
        self._running = True
        for i in range(self._max_concurrent):
            t = asyncio.create_task(self._worker_loop(i))
            self._workers.append(t)

    async def stop(self) -> None:
        self._running = False
        for _ in self._workers:
            await self._queue.put(-1)  # sentinel
        for t in self._workers:
            try:
                await asyncio.wait_for(t, timeout=5.0)
            except asyncio.TimeoutError:
                t.cancel()
        self._workers.clear()

    async def wait_for_idle(self) -> None:
        await self._queue.join()

    async def rehydrate_from_db(self) -> None:
        with self._db.session() as s:
            rows = list(s.scalars(
                select(Recording).where(Recording.status == "vod_queued").order_by(Recording.id)
            ))
            ids = [r.id for r in rows]
        for rid in ids:
            await self._queue.put(rid)
        if ids:
            logger.info("vod_queue: rehydrated %d queued recording(s)", len(ids))

    async def _worker_loop(self, worker_id: int) -> None:
        while self._running:
            rec_id = await self._queue.get()
            if rec_id == -1:
                self._queue.task_done()
                return
            try:
                await self._handler(rec_id)
            except Exception as e:  # noqa: BLE001
                logger.exception("vod_queue worker %d: handler failed for rec %d", worker_id, rec_id)
                try:
                    with self._db.session() as s:
                        rec = s.get(Recording, rec_id)
                        if rec is not None:
                            rec.status = "vod_failed"
                            rec.error = f"{type(e).__name__}: {e}"[:500]
                except Exception:  # noqa: BLE001
                    logger.exception("vod_queue: failed to record vod_failed status for rec %d", rec_id)
            finally:
                self._queue.task_done()

    def is_idle(self) -> bool:
        return self._queue.empty()
```

- [ ] **Step 3: Write failing test for vod_recovery**

```python
# tests/test_vod_recovery.py
import datetime as _dt

import pytest

from concertpvr.db import Database
from concertpvr.models import Base, Recording, Stream
from concertpvr.vod_recovery import mark_vod_downloads_interrupted_on_startup


@pytest.fixture
def db(tmp_path):
    d = Database(f"sqlite:///{tmp_path / 'r.db'}")
    Base.metadata.create_all(d.engine)
    return d


def test_vod_downloading_rows_become_vod_queued(db):
    with db.session() as s:
        st = Stream(kind="video", youtube_id="x", url="u", title="t", channel_name="c")
        s.add(st)
        s.flush()
        s.add_all([
            Recording(stream_id=st.id, started_at=_dt.datetime.now(_dt.UTC),
                      path="/tmp/a", status="vod_downloading", is_buffer=False),
            Recording(stream_id=st.id, started_at=_dt.datetime.now(_dt.UTC),
                      path="/tmp/b", status="vod_queued", is_buffer=False),
            Recording(stream_id=st.id, started_at=_dt.datetime.now(_dt.UTC),
                      path="/tmp/c", status="complete", is_buffer=False),
        ])

    count = mark_vod_downloads_interrupted_on_startup(db)
    assert count == 1

    with db.session() as s:
        from sqlalchemy import select
        statuses = sorted(r.status for r in s.scalars(select(Recording)))
        # one was vod_downloading → vod_queued. The original vod_queued stays.
        assert statuses == ["complete", "vod_queued", "vod_queued"]
```

- [ ] **Step 4: Implement vod_recovery.py**

```python
# src/concertpvr/vod_recovery.py
"""On startup, transition crashed `vod_downloading` rows back to `vod_queued`.

Mirror of orphan_recovery.py but for the VOD path. Safe because the queue
hasn't started workers yet — any `vod_downloading` row is a real interrupt.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from concertpvr.db import Database
from concertpvr.models import Recording

logger = logging.getLogger(__name__)


def mark_vod_downloads_interrupted_on_startup(db: Database) -> int:
    count = 0
    with db.session() as s:
        rows = list(s.scalars(select(Recording).where(Recording.status == "vod_downloading")))
        for rec in rows:
            rec.status = "vod_queued"
            count += 1
    if count:
        logger.warning(
            "vod_recovery: requeued %d in-flight VOD download(s) interrupted by restart", count,
        )
    return count
```

- [ ] **Step 5: Wire into lifespan in main.py**

In `src/concertpvr/main.py`'s `lifespan(app)`, after the existing `mark_interrupted_on_startup(app.state.db)` call (added in v0.2 T3), insert:

```python
    # VOD recovery: any download stuck in 'vod_downloading' from a prior crash
    # is real (the queue is empty at startup). Requeue it.
    from concertpvr.vod_recovery import mark_vod_downloads_interrupted_on_startup
    mark_vod_downloads_interrupted_on_startup(app.state.db)
```

After `register_app(...)` and `scheduler.start()`, but before any rehydration, wire the queue. The queue handler is created in Task 7 — for now, register a temporary placeholder that just marks status:

```python
    # VOD queue setup. Handler wired in Task 7 (when vod_downloader exists).
    from concertpvr.vod_queue import VodQueue
    from concertpvr.models import Settings as _SettingsModel

    with app.state.db.session() as _s:
        _row = _s.get(_SettingsModel, 1)
        _vod_cap = _row.max_concurrent_vod_downloads if _row else 2

    async def _placeholder_vod_handler(rec_id: int) -> None:
        # Replaced in Task 7 with real download.
        raise RuntimeError("VOD handler not yet wired")

    app.state.vod_queue = VodQueue(
        db=app.state.db, handler=_placeholder_vod_handler, max_concurrent=_vod_cap,
    )
    await app.state.vod_queue.start_workers()
    await app.state.vod_queue.rehydrate_from_db()
```

(Task 7 will replace `_placeholder_vod_handler` with the real one.)

In the shutdown path of `lifespan`, before the existing scheduler.shutdown:

```python
    if hasattr(app.state, "vod_queue"):
        await app.state.vod_queue.stop()
```

- [ ] **Step 6: Run tests + commit**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_vod_queue.py tests/test_vod_recovery.py -v
./.venv/Scripts/python.exe -m pytest -q
./.venv/Scripts/python.exe -m mypy src/
git add src/concertpvr/vod_queue.py src/concertpvr/vod_recovery.py src/concertpvr/main.py tests/test_vod_queue.py tests/test_vod_recovery.py
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(vod_queue): VOD download queue + recovery + lifespan wiring (placeholder handler)"
```

---

### Task 6: vod_downloader module

**Files:**
- Create: `src/concertpvr/vod_downloader.py`
- Create: `tests/test_vod_downloader.py`

Spawns yt-dlp CLI as subprocess, parses progress lines, writes single-file output to staging.

- [ ] **Step 1: Write failing tests with FakeProcessRunner**

```python
# tests/test_vod_downloader.py
"""VOD downloader — yt-dlp subprocess invocation, progress parsing."""

import pytest

from concertpvr.process import FakeProcessRunner
from concertpvr.vod_downloader import VodDownloadError, VodDownloader, VodProgress


@pytest.mark.asyncio
async def test_downloader_invokes_ytdlp_with_correct_args(tmp_path):
    runner = FakeProcessRunner(stdout_lines=[], exit_code=0)
    output_path = tmp_path / "out.mkv"
    dl = VodDownloader(runner=runner)

    await dl.download(
        url="https://www.youtube.com/watch?v=abc",
        output_path=output_path,
        quality_format="bestvideo*+bestaudio/best",
        cookies_path=None,
        on_progress=None,
    )

    args = runner.last_args
    assert args[0] == "yt-dlp"
    assert "--continue" in args
    assert "-f" in args and "bestvideo*+bestaudio/best" in args
    assert "-o" in args
    assert str(output_path) in args[args.index("-o") + 1]
    assert args[-1] == "https://www.youtube.com/watch?v=abc"


@pytest.mark.asyncio
async def test_downloader_passes_cookies_when_set(tmp_path):
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# cookies")
    runner = FakeProcessRunner(stdout_lines=[], exit_code=0)
    dl = VodDownloader(runner=runner)

    await dl.download(
        url="https://x", output_path=tmp_path / "o.mkv",
        quality_format="best", cookies_path=cookies, on_progress=None,
    )

    assert "--cookies" in runner.last_args
    idx = runner.last_args.index("--cookies")
    assert runner.last_args[idx + 1] == str(cookies)


@pytest.mark.asyncio
async def test_downloader_parses_progress_lines(tmp_path):
    progress_events: list[VodProgress] = []

    async def collect(p: VodProgress) -> None:
        progress_events.append(p)

    # yt-dlp emits "[download]  10.5% of   1.20GiB at  2.50MiB/s ETA 03:24"
    runner = FakeProcessRunner(stdout_lines=[
        b"[download]   0.0% of  1.20GiB at Unknown ETA Unknown",
        b"[download]  10.5% of  1.20GiB at  2.50MiB/s ETA 03:24",
        b"[download]  50.0% of  1.20GiB at  3.00MiB/s ETA 01:10",
        b"[download] 100.0% of  1.20GiB",
    ], exit_code=0)

    dl = VodDownloader(runner=runner)
    await dl.download(
        url="https://x", output_path=tmp_path / "o.mkv",
        quality_format="best", cookies_path=None, on_progress=collect,
    )

    assert len(progress_events) >= 3
    assert progress_events[1].pct == pytest.approx(10.5, abs=0.1)
    assert progress_events[1].eta_s == 3 * 60 + 24


@pytest.mark.asyncio
async def test_downloader_raises_on_nonzero_exit(tmp_path):
    runner = FakeProcessRunner(stdout_lines=[b"ERROR: Video unavailable"], exit_code=1)
    dl = VodDownloader(runner=runner)

    with pytest.raises(VodDownloadError) as exc_info:
        await dl.download(
            url="https://x", output_path=tmp_path / "o.mkv",
            quality_format="best", cookies_path=None, on_progress=None,
        )
    assert "Video unavailable" in str(exc_info.value)
```

- [ ] **Step 2: Implement vod_downloader.py**

```python
# src/concertpvr/vod_downloader.py
"""yt-dlp finite-file VOD download wrapper.

Different from recorder.py: targets a single output file, --continue for
resume, expects exit-0 on success. Progress lines have determinate %, eta_s,
and total bytes (vs live where total is unknown).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from concertpvr.process import ProcessRunner

logger = logging.getLogger(__name__)


class VodDownloadError(Exception):
    """yt-dlp exited non-zero when downloading a VOD."""


@dataclass(frozen=True)
class VodProgress:
    pct: float            # 0..100
    bytes_total: int | None
    bitrate_bps: int | None
    eta_s: int | None


_PROGRESS_RE = re.compile(
    r"\[download\]\s+(?P<pct>[\d.]+)%\s+of\s+(?P<total>[\d.]+)(?P<unit>[KMG]?i?B)"
    r"(?:\s+at\s+(?P<rate>[\d.]+|Unknown)(?P<rate_unit>[KMG]?i?B/s)?)?"
    r"(?:\s+ETA\s+(?P<eta>\d+:\d+(?::\d+)?|Unknown))?"
)


def _parse_size(value: str, unit: str) -> int:
    n = float(value)
    mult = 1
    u = unit.upper()
    if u.startswith("K"):
        mult = 1024
    elif u.startswith("M"):
        mult = 1024 ** 2
    elif u.startswith("G"):
        mult = 1024 ** 3
    return int(n * mult)


def _parse_eta(s: str) -> int | None:
    if s == "Unknown":
        return None
    parts = s.split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    return None


def _parse_progress_line(line: str) -> VodProgress | None:
    m = _PROGRESS_RE.search(line)
    if not m:
        return None
    pct = float(m.group("pct"))
    total = _parse_size(m.group("total"), m.group("unit"))
    rate = m.group("rate")
    rate_unit = m.group("rate_unit")
    bitrate = None
    if rate and rate != "Unknown" and rate_unit:
        bitrate = _parse_size(rate, rate_unit) * 8  # bytes/s → bits/s
    eta = _parse_eta(m.group("eta")) if m.group("eta") else None
    return VodProgress(pct=pct, bytes_total=total, bitrate_bps=bitrate, eta_s=eta)


class VodDownloader:
    def __init__(self, *, runner: ProcessRunner) -> None:
        self._runner = runner

    async def download(
        self,
        *,
        url: str,
        output_path: Path,
        quality_format: str,
        cookies_path: Path | None,
        on_progress: Callable[[VodProgress], Awaitable[None]] | None,
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        args: list[str] = [
            "yt-dlp",
            "--continue",
            "--no-part",
            "--no-playlist",
            "-f", quality_format,
            "-o", str(output_path),
        ]
        if cookies_path:
            args.extend(["--cookies", str(cookies_path)])
        args.append(url)

        last_stderr: list[str] = []

        async def stdout_handler(line: bytes) -> None:
            text = line.decode("utf-8", errors="replace").rstrip()
            progress = _parse_progress_line(text)
            if progress and on_progress:
                await on_progress(progress)

        async def stderr_handler(line: bytes) -> None:
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                last_stderr.append(text)
                if len(last_stderr) > 50:
                    last_stderr.pop(0)

        exit_code = await self._runner.run(
            args, on_stdout=stdout_handler, on_stderr=stderr_handler,
        )
        if exit_code != 0:
            tail = "\n".join(last_stderr[-10:]) or "yt-dlp exited %d" % exit_code
            raise VodDownloadError(tail)
```

- [ ] **Step 3: Run + commit**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_vod_downloader.py -v
./.venv/Scripts/python.exe -m mypy src/
git add src/concertpvr/vod_downloader.py tests/test_vod_downloader.py
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(vod_downloader): yt-dlp finite-file download with progress parsing"
```

---

### Task 7: Workflow A — POST /api/streams VOD path + queue handler

**Files:**
- Modify: `src/concertpvr/api/streams.py`
- Modify: `src/concertpvr/main.py` (replace placeholder handler)
- Modify: `tests/test_streams_api.py`

Wire the actual VOD download flow: paste a non-live URL → probe → create Stream(kind=video) + Recording(vod_queued) → enqueue. Queue handler downloads via vod_downloader, runs ffprobe to populate width/height/duration_s, transitions to status=complete.

- [ ] **Step 1: Extend POST /api/streams to handle VOD URLs**

In `src/concertpvr/api/streams.py`, the POST handler currently creates `Stream(kind="video")` for non-live URLs but doesn't wire the recording. Replace the body around the existing `kind = "live" if info.is_live else "video"` block:

```python
@router.post("/streams", status_code=201, response_model=StreamRead)
async def create_stream(
    body: StreamCreate,
    request: Request,
    db: Database = Depends(get_db),
) -> Stream:
    cookies_path = _resolve_cookies_path(db)
    try:
        info = await probe(body.url, cookies_path=cookies_path)
    except ProbeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    kind = "live" if info.is_live else "video"

    with db.session() as s:
        # Dedupe by youtube_id
        existing = s.scalar(select(Stream).where(Stream.youtube_id == info.youtube_id))
        if existing is not None:
            raise HTTPException(status_code=409, detail=f"stream already exists: {info.youtube_id}")

        # For VODs, run setlist detection on description
        detected_text: str | None = None
        detected_source: str | None = None
        if not info.is_live:
            from concertpvr.setlist_detector import detect_in_chapters, detect_in_description
            chap = detect_in_chapters(info.chapters)
            if chap is not None:
                detected_text = ""
                detected_source = "chapters"
            else:
                desc = detect_in_description(info.description)
                if desc is not None:
                    detected_text = desc.raw_text
                    detected_source = "description"

        stream = Stream(
            kind=kind,
            youtube_id=info.youtube_id,
            url=info.url,
            title=info.title,
            channel_name=info.channel_name,
            thumbnail_url=info.thumbnail_url,
            original_upload_date=info.original_upload_date if not info.is_live else None,
            description=info.description if not info.is_live else None,
            youtube_tags=info.tags if not info.is_live else None,
            detected_setlist_text=detected_text,
            detected_setlist_source=detected_source,
        )
        s.add(stream)
        s.flush()
        sid = stream.id

        # For VODs, also create the Recording row + enqueue
        if kind == "video":
            import datetime as _dt
            from concertpvr.models import Recording
            from pathlib import Path
            staging_dir = Path(request.app.state.config.staging_dir)
            output_path = staging_dir / f"vod-{info.youtube_id}.mkv"
            rec = Recording(
                stream_id=sid,
                started_at=_dt.datetime.now(_dt.UTC),
                path=str(output_path),
                status="vod_queued",
                is_buffer=False,
            )
            s.add(rec)
            s.flush()
            rec_id = rec.id

    if kind == "video":
        await request.app.state.vod_queue.enqueue(rec_id)

    with db.session() as s:
        return s.get(Stream, sid)
```

- [ ] **Step 2: Replace placeholder handler in main.py**

In `lifespan`, replace the `_placeholder_vod_handler` from Task 5 with the real handler that downloads + ffprobes + transitions status. Replace the placeholder block:

```python
    from concertpvr.vod_queue import VodQueue
    from concertpvr.vod_downloader import VodDownloader, VodDownloadError, VodProgress
    from concertpvr.process import AsyncSubprocessRunner
    from concertpvr.recording_starter import _resolve_cookies_path
    from concertpvr.models import Recording, Settings as _SettingsModel, Stream
    from concertpvr.ffmpeg import probe_media
    from pathlib import Path
    import datetime as _dt

    with app.state.db.session() as _s:
        _row = _s.get(_SettingsModel, 1)
        _vod_cap = _row.max_concurrent_vod_downloads if _row else 2

    async def _vod_handler(rec_id: int) -> None:
        with app.state.db.session() as s:
            rec = s.get(Recording, rec_id)
            if rec is None:
                return
            stream = s.get(Stream, rec.stream_id)
            if stream is None:
                rec.status = "vod_failed"
                rec.error = "stream missing"
                return
            url = stream.url
            output_path = Path(rec.path)
            settings_row = s.get(_SettingsModel, 1)
            quality = settings_row.default_quality if settings_row else "bestvideo*+bestaudio/best"
            rec.status = "vod_downloading"
        cookies_path = _resolve_cookies_path(app.state.db)

        async def on_progress(p: VodProgress) -> None:
            await app.state.bc.publish(
                f"recordings.{rec_id}.progress",
                {
                    "pct": p.pct,
                    "bytes_total": p.bytes_total,
                    "bitrate_bps": p.bitrate_bps,
                    "eta_s": p.eta_s,
                },
            )

        downloader = VodDownloader(runner=AsyncSubprocessRunner())
        try:
            await downloader.download(
                url=url, output_path=output_path, quality_format=quality,
                cookies_path=cookies_path, on_progress=on_progress,
            )
        except VodDownloadError as e:
            with app.state.db.session() as s:
                rec = s.get(Recording, rec_id)
                if rec is not None:
                    rec.status = "vod_failed"
                    rec.error = str(e)[:500]
            return

        # Run ffprobe to populate width/height/duration_s/size_bytes
        try:
            media_info = await probe_media(output_path)
        except Exception as e:  # noqa: BLE001
            media_info = None

        with app.state.db.session() as s:
            rec = s.get(Recording, rec_id)
            if rec is None:
                return
            rec.status = "complete"
            rec.ended_at = _dt.datetime.now(_dt.UTC)
            if output_path.exists():
                rec.size_bytes = output_path.stat().st_size
            if media_info is not None:
                rec.width = media_info.width
                rec.height = media_info.height
                rec.fps = media_info.fps
                rec.duration_s = media_info.duration_s

    app.state.vod_queue = VodQueue(
        db=app.state.db, handler=_vod_handler, max_concurrent=_vod_cap,
    )
    await app.state.vod_queue.start_workers()
    await app.state.vod_queue.rehydrate_from_db()
```

(`probe_media` is the existing ffprobe wrapper — verify it exists in `ffmpeg.py`. If named differently, use the actual function.)

- [ ] **Step 3: Append API tests**

In `tests/test_streams_api.py`:

```python
def test_post_streams_vod_creates_stream_and_queued_recording(client, monkeypatch):
    """Pasting a non-live URL creates Stream(kind=video) + Recording(vod_queued)."""
    from unittest.mock import AsyncMock, MagicMock

    from concertpvr.ytdlp import StreamInfo

    info = StreamInfo(
        youtube_id="vod123",
        url="https://www.youtube.com/watch?v=vod123",
        title="Khruangbin: Tiny Desk Concert",
        channel_name="NPR Music",
        is_live=False,
        thumbnail_url=None,
        description="0:00 - Intro\n1:24 - Pelota\n5:12 - So We Won't Forget",
        tags=["khruangbin", "indie"],
        chapters=None,
        duration_s=1122,
    )

    async def _async_probe(_url, **_kwargs):
        return info

    fake_queue = MagicMock()
    fake_queue.enqueue = AsyncMock()
    monkeypatch.setattr(client.app.state, "vod_queue", fake_queue)

    with patch("concertpvr.api.streams.probe", side_effect=_async_probe):
        r = client.post("/api/streams", json={"url": info.url})
    assert r.status_code == 201
    body = r.json()
    assert body["kind"] == "video"
    assert body["youtube_id"] == "vod123"
    assert body["description"].startswith("0:00")
    assert body["detected_setlist_source"] == "description"

    # Recording was created with vod_queued status
    db = client.app.state.db
    from sqlalchemy import select
    from concertpvr.models import Recording, Stream
    with db.session() as s:
        st = s.scalar(select(Stream).where(Stream.youtube_id == "vod123"))
        rec = s.scalar(select(Recording).where(Recording.stream_id == st.id))
        assert rec is not None
        assert rec.status == "vod_queued"
        assert rec.is_buffer is False

    # Queue.enqueue was called with the new recording id
    fake_queue.enqueue.assert_awaited_once()


def test_post_streams_vod_dedupe_409(client, monkeypatch):
    from unittest.mock import AsyncMock, MagicMock
    from concertpvr.ytdlp import StreamInfo

    info = StreamInfo(
        youtube_id="dup1", url="https://x", title="t", channel_name="c",
        is_live=False, thumbnail_url=None,
    )

    async def _p(_u, **_kw):
        return info

    fake_queue = MagicMock()
    fake_queue.enqueue = AsyncMock()
    monkeypatch.setattr(client.app.state, "vod_queue", fake_queue)

    with patch("concertpvr.api.streams.probe", side_effect=_p):
        r1 = client.post("/api/streams", json={"url": info.url})
        assert r1.status_code == 201
        r2 = client.post("/api/streams", json={"url": info.url})
        assert r2.status_code == 409
```

- [ ] **Step 4: Run + commit**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_streams_api.py -v
./.venv/Scripts/python.exe -m pytest -q
./.venv/Scripts/python.exe -m mypy src/
git add src/concertpvr/api/streams.py src/concertpvr/main.py tests/test_streams_api.py
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(api): workflow A — VOD URL paste creates queued recording, queue handler downloads + ffprobes"
```

---

## Wave 3 — Watchers extended + auto-publish

### Task 8: channel_poller VOD branch + auto_publish_after_download flag

**Files:**
- Modify: `src/concertpvr/channel_poller.py`
- Modify: `src/concertpvr/ytdlp_channels.py`
- Modify: `src/concertpvr/api/watchers.py` (accept new fields)
- Modify: `tests/test_channel_poller.py`

- [ ] **Step 1: Extend ytdlp_channels.py with VOD-uploads listing**

In `src/concertpvr/ytdlp_channels.py`, add a function to list recent VOD uploads (non-live) on a channel:

```python
async def list_recent_uploads(
    channel_url: str,
    *,
    cookies_path: Path | None = None,
    limit: int = 20,
) -> list[Broadcast]:
    """Flat-extract recent uploads on a channel; filter to non-live only.

    Returns Broadcast objects (existing dataclass) with is_live=False set on
    each. Used by channel_poller's VOD branch.
    """
    cookies_str = str(cookies_path) if cookies_path and Path(cookies_path).exists() else None
    try:
        info = await asyncio.to_thread(_extract_channel_flat, channel_url, cookies_str, limit)
    except yt_dlp.utils.DownloadError as e:
        raise ProbeError(str(e)) from e

    entries = info.get("entries") or []
    out: list[Broadcast] = []
    for e in entries:
        if e is None:
            continue
        if e.get("is_live"):
            continue  # covered by live path
        upload_date = _parse_yt_date(e.get("upload_date") or e.get("release_date"))
        out.append(Broadcast(
            youtube_id=e.get("id", ""),
            url=e.get("url") or e.get("webpage_url", ""),
            title=e.get("title", ""),
            channel_name=info.get("channel") or info.get("uploader") or "Unknown",
            is_live=False,
            thumbnail_url=e.get("thumbnail"),
            upload_date=upload_date,
        ))
    return out


def _extract_channel_flat(channel_url: str, cookies_path: str | None, limit: int) -> dict:
    opts: dict[str, object] = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "playlistend": limit,
    }
    if cookies_path:
        opts["cookiefile"] = cookies_path
    with yt_dlp.YoutubeDL(opts) as ydl:
        result = ydl.extract_info(channel_url, download=False)
        if result is None:
            raise ProbeError("no info returned")
        return result
```

If `Broadcast` doesn't have `upload_date`, extend the dataclass to add `upload_date: _dt.date | None = None`. Import `_parse_yt_date` from `ytdlp.py` (or move it to a shared util — for now duplicate or import).

- [ ] **Step 2: Extend channel_poller.py**

Find the existing per-watcher loop. Add the VOD branch:

```python
async def _poll_watcher(watcher: Watcher, ...) -> None:
    if watcher.watch_live:
        await _check_for_new_lives(watcher, ...)  # existing logic
    if watcher.watch_vod_uploads:
        await _check_for_new_vod_uploads(watcher, ...)
```

The new function:

```python
async def _check_for_new_vod_uploads(
    watcher: Watcher,
    *,
    db: Database,
    pool: RecorderPool,
    vod_queue: VodQueue,
    buf: BufferManager,
    bc: Broadcaster,
    cookies_path: Path | None,
) -> None:
    """Pull recent uploads from the channel; queue any matching, new ones."""
    import re
    from concertpvr.artist_extractor import extract_artist
    from concertpvr.setlist_detector import detect_in_chapters, detect_in_description, detect_in_comments
    from concertpvr.ytdlp import probe
    from concertpvr.ytdlp_channels import list_recent_uploads

    try:
        uploads = await list_recent_uploads(watcher.channel_url, cookies_path=cookies_path, limit=20)
    except ProbeError as e:
        logger.warning("watcher %d: failed to list uploads: %s", watcher.id, e)
        return

    title_filter_re = re.compile(watcher.vod_title_filter) if watcher.vod_title_filter else None
    cutoff = watcher.created_at.date() if watcher.created_at else None

    with db.session() as s:
        for entry in uploads:
            existing = s.scalar(select(Stream).where(Stream.youtube_id == entry.youtube_id))
            if existing is not None:
                continue
            if cutoff and entry.upload_date and entry.upload_date < cutoff:
                continue  # forward-only
            if title_filter_re and not title_filter_re.search(entry.title):
                continue
            # Full probe
            try:
                info = await probe(
                    entry.url,
                    cookies_path=cookies_path,
                    fetch_comments=watcher.extract_setlist_from_comments,
                )
            except ProbeError as e:
                logger.warning("watcher %d: probe failed for %s: %s", watcher.id, entry.youtube_id, e)
                continue

            # Setlist detection: chapters → description → comments (if opted in)
            detected_text: str | None = None
            detected_source: str | None = None
            chap = detect_in_chapters(info.chapters)
            if chap is not None:
                detected_source = "chapters"
            else:
                desc = detect_in_description(info.description)
                if desc is not None:
                    detected_text = desc.raw_text
                    detected_source = "description"
                elif watcher.extract_setlist_from_comments:
                    com = detect_in_comments(info.comments)
                    if com is not None:
                        detected_text = com.raw_text
                        detected_source = "comments"

            stream = Stream(
                kind="video",
                youtube_id=info.youtube_id,
                url=info.url,
                title=info.title,
                channel_name=info.channel_name,
                thumbnail_url=info.thumbnail_url,
                original_upload_date=info.original_upload_date,
                description=info.description,
                youtube_tags=info.tags,
                detected_setlist_text=detected_text,
                detected_setlist_source=detected_source,
                watcher_id=watcher.id,
            )
            s.add(stream)
            s.flush()

            artist = extract_artist(info.title, watcher.vod_artist_regex)
            auto_pub = bool(watcher.auto_publish and artist is not None)

            from pathlib import Path
            import datetime as _dt
            from concertpvr.models import Recording
            staging_dir = Path(buf.staging_root) if hasattr(buf, "staging_root") else Path("/tmp")
            output_path = staging_dir / f"vod-{info.youtube_id}.mkv"

            rec = Recording(
                stream_id=stream.id,
                started_at=_dt.datetime.now(_dt.UTC),
                path=str(output_path),
                status="vod_queued",
                is_buffer=False,
                auto_publish_after_download=auto_pub,
            )
            s.add(rec)
            s.flush()
            rec_id = rec.id

        s.commit()  # flush all new rows
    # Enqueue all created recordings (outside the session)
    # We need to recollect IDs since `rec_id` was last seed only.
    # Better: collect IDs in the loop above. Refactor:
```

Refactor to collect rec_ids in a list and enqueue after commit. The cleaner version:

```python
async def _check_for_new_vod_uploads(
    watcher: Watcher,
    *,
    db: Database,
    vod_queue: VodQueue,
    buf: BufferManager,
    bc: Broadcaster,
    cookies_path: Path | None,
) -> None:
    # ... (probe + filter as above) ...
    new_rec_ids: list[int] = []
    with db.session() as s:
        for entry in uploads:
            # ... (same logic, append rec.id to new_rec_ids) ...
            new_rec_ids.append(rec.id)
    for rid in new_rec_ids:
        await vod_queue.enqueue(rid)
```

The signature of `_poll_watcher` needs `vod_queue` passed in. Update the calling convention accordingly.

- [ ] **Step 3: Wire `vod_queue` into channel_poller's setup**

Find where `ChannelPoller` is constructed in `register_app(...)` (in main.py). Add `vod_queue=app.state.vod_queue` to the constructor args. Update `ChannelPoller.__init__` to accept and store it.

- [ ] **Step 4: Extend `api/watchers.py` PATCH to accept new fields**

The PATCH handler reads `WatcherPatch` and applies fields to the row. With Pydantic schemas extended in Task 1, the new fields automatically flow through. Add explicit acceptance + 422 validation tests.

- [ ] **Step 5: Test channel poller VOD branch**

In `tests/test_channel_poller.py`:

```python
@pytest.mark.asyncio
async def test_poller_skips_vod_when_watch_vod_uploads_off(monkeypatch, ...):
    """Watcher with watch_vod_uploads=False skips the VOD branch entirely."""
    # ... assert list_recent_uploads NOT called ...


@pytest.mark.asyncio
async def test_poller_creates_vod_recording_with_auto_publish_when_artist_extracted(...):
    """Watcher with auto_publish=True + matching regex sets auto_publish_after_download."""
    # ... mock list_recent_uploads + probe, assert Recording.auto_publish_after_download==True ...


@pytest.mark.asyncio
async def test_poller_skips_already_known_youtube_id(...):
    """If a Stream with the youtube_id already exists, skip."""


@pytest.mark.asyncio
async def test_poller_forward_only_skips_uploads_older_than_watcher_created_at(...):
    """Uploads with upload_date < watcher.created_at are skipped."""


@pytest.mark.asyncio
async def test_poller_applies_vod_title_filter(...):
    """vod_title_filter regex narrows the candidates."""
```

(Each test mocks `list_recent_uploads` and `probe` from the appropriate module path.)

- [ ] **Step 6: Run + commit**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_channel_poller.py -v
./.venv/Scripts/python.exe -m pytest -q
./.venv/Scripts/python.exe -m mypy src/
git add src/concertpvr/channel_poller.py src/concertpvr/ytdlp_channels.py src/concertpvr/api/watchers.py tests/test_channel_poller.py
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(channel_poller): VOD-uploads branch with auto-publish flag"
```

---

### Task 9: Backlog browser endpoints

**Files:**
- Modify: `src/concertpvr/api/watchers.py`
- Modify: `tests/test_watchers_api.py`

- [ ] **Step 1: Add backlog endpoints**

In `api/watchers.py`:

```python
@router.get("/watchers/{watcher_id}/backlog", response_model=list[BacklogItem])
async def get_backlog(
    watcher_id: int,
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    sort: Literal["newest", "most_viewed", "longest", "oldest"] = Query("newest"),
    db: Database = Depends(get_db),
) -> list[BacklogItem]:
    with db.session() as s:
        watcher = s.get(Watcher, watcher_id)
        if watcher is None:
            raise HTTPException(404, "watcher not found")
        channel_url = watcher.channel_url

    cookies_path = _resolve_cookies_path(db)
    try:
        items = await list_recent_uploads(channel_url, cookies_path=cookies_path, limit=offset + limit)
    except ProbeError as e:
        raise HTTPException(400, str(e)) from e

    items_slice = items[offset:offset + limit]
    if sort == "oldest":
        items_slice = sorted(items_slice, key=lambda b: b.upload_date or _dt.date.min)
    elif sort == "longest":
        items_slice = sorted(items_slice, key=lambda b: -(b.duration_s or 0))
    # most_viewed sort requires full probe — flag in helper text; skip for now
    # newest = default order from yt-dlp

    # Mark which are already in DB
    youtube_ids = [b.youtube_id for b in items_slice]
    with db.session() as s:
        existing_ids = {
            row.youtube_id for row in s.scalars(
                select(Stream).where(Stream.youtube_id.in_(youtube_ids))
            )
        }
        queued_ids = {
            stream.youtube_id for stream in s.scalars(
                select(Stream).join(Recording).where(
                    Stream.youtube_id.in_(youtube_ids),
                    Recording.status.in_(["vod_queued", "vod_downloading"]),
                )
            )
        }

    out: list[BacklogItem] = []
    for b in items_slice:
        if b.youtube_id in queued_ids:
            state = "queued"
        elif b.youtube_id in existing_ids:
            state = "downloaded"
        else:
            state = "not_downloaded"
        out.append(BacklogItem(
            youtube_id=b.youtube_id,
            title=b.title,
            url=b.url,
            thumbnail_url=b.thumbnail_url,
            upload_date=b.upload_date,
            duration_s=b.duration_s,
            view_count=None,  # not in flat-extract
            state=state,
        ))
    return out


@router.post("/watchers/{watcher_id}/backlog/download", status_code=201)
async def download_backlog(
    watcher_id: int,
    request: Request,
    body: BacklogDownloadRequest,
    db: Database = Depends(get_db),
) -> dict:
    with db.session() as s:
        watcher = s.get(Watcher, watcher_id)
        if watcher is None:
            raise HTTPException(404, "watcher not found")
        cookies_path = _resolve_cookies_path(db)
        new_rec_ids: list[int] = []
        for yid in body.video_ids:
            existing = s.scalar(select(Stream).where(Stream.youtube_id == yid))
            if existing is not None:
                continue
            url = f"https://www.youtube.com/watch?v={yid}"
            try:
                info = await probe(url, cookies_path=cookies_path)
            except ProbeError as e:
                logger.warning("backlog download: probe failed for %s: %s", yid, e)
                continue
            # Same Stream + Recording creation as channel poller, but
            # auto_publish_after_download stays False (user-curated).
            # ... (copy from channel_poller's flow, sans auto-publish flag) ...
            new_rec_ids.append(rec.id)
    for rid in new_rec_ids:
        await request.app.state.vod_queue.enqueue(rid)
    return {"queued_recording_ids": new_rec_ids}
```

Add the schemas to `schemas.py`:

```python
class BacklogItem(BaseModel):
    youtube_id: str
    title: str
    url: str
    thumbnail_url: str | None
    upload_date: _dt.date | None
    duration_s: int | None
    view_count: int | None
    state: Literal["downloaded", "queued", "not_downloaded"]


class BacklogDownloadRequest(BaseModel):
    video_ids: list[str]
```

- [ ] **Step 2: Test the endpoints**

```python
# tests/test_watchers_api.py — append:

def test_get_backlog_marks_existing_streams_as_downloaded(client, monkeypatch):
    # ... mock list_recent_uploads, seed a Stream with one of the youtube_ids, GET /backlog,
    # assert that one item has state="downloaded" ...


def test_post_backlog_download_creates_recordings_and_enqueues(client, monkeypatch):
    # ... mock probe, mock vod_queue, POST /backlog/download with 2 ids,
    # assert 2 Recording rows with auto_publish_after_download=False, queue.enqueue called twice ...
```

- [ ] **Step 3: Run + commit**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_watchers_api.py -v
./.venv/Scripts/python.exe -m mypy src/
git add src/concertpvr/api/watchers.py src/concertpvr/schemas.py tests/test_watchers_api.py
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(api): watcher backlog browser GET/POST endpoints"
```

---

## Wave 4 — Playlists

### Task 10: playlist_ingest module + endpoints

**Files:**
- Create: `src/concertpvr/playlist_ingest.py`
- Create: `src/concertpvr/api/playlists.py`
- Modify: `src/concertpvr/main.py` (mount router)
- Create: `tests/test_playlists_api.py`

- [ ] **Step 1: Create playlist_ingest.py**

```python
# src/concertpvr/playlist_ingest.py
"""Expand a YouTube playlist URL into a list of video metadata."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import yt_dlp

from concertpvr.ytdlp import ProbeError, _parse_yt_date


@dataclass(frozen=True)
class PlaylistEntry:
    youtube_id: str
    title: str
    url: str
    channel_name: str
    thumbnail_url: str | None
    duration_s: int | None
    upload_date: object | None  # _dt.date


@dataclass(frozen=True)
class PlaylistInfo:
    playlist_id: str
    playlist_title: str
    count: int
    entries: list[PlaylistEntry]


def _extract_playlist_sync(url: str, cookies_path: str | None, limit: int) -> dict:
    opts: dict[str, object] = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "playlistend": limit,
    }
    if cookies_path:
        opts["cookiefile"] = cookies_path
    with yt_dlp.YoutubeDL(opts) as ydl:
        result = ydl.extract_info(url, download=False)
        if result is None:
            raise ProbeError("no playlist info returned")
        return result


async def expand_playlist(
    url: str,
    *,
    cookies_path: Path | None = None,
    limit: int = 500,
) -> PlaylistInfo:
    cookies_str = str(cookies_path) if cookies_path and Path(cookies_path).exists() else None
    try:
        info = await asyncio.to_thread(_extract_playlist_sync, url, cookies_str, limit)
    except yt_dlp.utils.DownloadError as e:
        raise ProbeError(str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise ProbeError(f"unexpected error: {e}") from e

    entries_raw = info.get("entries") or []
    entries: list[PlaylistEntry] = []
    for e in entries_raw:
        if e is None:
            continue
        yid = e.get("id") or ""
        if not yid:
            continue
        entries.append(PlaylistEntry(
            youtube_id=yid,
            title=e.get("title") or "Untitled",
            url=e.get("url") or e.get("webpage_url") or f"https://www.youtube.com/watch?v={yid}",
            channel_name=e.get("channel") or e.get("uploader") or info.get("channel") or "Unknown",
            thumbnail_url=e.get("thumbnail"),
            duration_s=int(e["duration"]) if e.get("duration") is not None else None,
            upload_date=_parse_yt_date(e.get("upload_date") or e.get("release_date")),
        ))

    return PlaylistInfo(
        playlist_id=info.get("id", ""),
        playlist_title=info.get("title", "Untitled Playlist"),
        count=info.get("playlist_count") or len(entries),
        entries=entries,
    )
```

- [ ] **Step 2: Create api/playlists.py**

```python
# src/concertpvr/api/playlists.py
"""Playlist ingest endpoints."""

from __future__ import annotations

import datetime as _dt
import logging
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

from concertpvr.db import Database, get_db
from concertpvr.models import Recording, Stream
from concertpvr.playlist_ingest import expand_playlist
from concertpvr.recording_starter import _resolve_cookies_path
from concertpvr.ytdlp import ProbeError, probe

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


class PlaylistIngestRequest(BaseModel):
    url: str


class PlaylistIngestItem(BaseModel):
    youtube_id: str
    title: str
    channel_name: str
    thumbnail_url: str | None
    duration_s: int | None
    upload_date: _dt.date | None
    is_already_known: bool


class PlaylistIngestResponse(BaseModel):
    type: Literal["playlist"] = "playlist"
    playlist_id: str
    playlist_title: str
    count: int
    items: list[PlaylistIngestItem]


class PlaylistConfirmRequest(BaseModel):
    video_ids: list[str]
    default_genres: str | None = None
    segmentation_mode: Literal["chapters", "whole-video", "manual"] | None = None


@router.post("/playlists/ingest", response_model=PlaylistIngestResponse)
async def ingest_playlist(
    body: PlaylistIngestRequest,
    db: Database = Depends(get_db),
) -> PlaylistIngestResponse:
    cookies_path = _resolve_cookies_path(db)
    try:
        info = await expand_playlist(body.url, cookies_path=cookies_path)
    except ProbeError as e:
        raise HTTPException(400, str(e)) from e

    youtube_ids = [e.youtube_id for e in info.entries]
    with db.session() as s:
        existing = {
            row.youtube_id for row in s.scalars(
                select(Stream).where(Stream.youtube_id.in_(youtube_ids))
            )
        }

    items = [
        PlaylistIngestItem(
            youtube_id=e.youtube_id,
            title=e.title,
            channel_name=e.channel_name,
            thumbnail_url=e.thumbnail_url,
            duration_s=e.duration_s,
            upload_date=e.upload_date,
            is_already_known=e.youtube_id in existing,
        )
        for e in info.entries
    ]
    return PlaylistIngestResponse(
        playlist_id=info.playlist_id,
        playlist_title=info.playlist_title,
        count=info.count,
        items=items,
    )


@router.post("/playlists/ingest/confirm", status_code=201)
async def confirm_playlist(
    body: PlaylistConfirmRequest,
    request: Request,
    db: Database = Depends(get_db),
) -> dict:
    cookies_path = _resolve_cookies_path(db)
    new_rec_ids: list[int] = []
    staging_dir = Path(request.app.state.config.staging_dir)

    for yid in body.video_ids:
        url = f"https://www.youtube.com/watch?v={yid}"
        with db.session() as s:
            existing = s.scalar(select(Stream).where(Stream.youtube_id == yid))
            if existing is not None:
                continue
        try:
            info = await probe(url, cookies_path=cookies_path)
        except ProbeError as e:
            logger.warning("playlist confirm: probe failed for %s: %s", yid, e)
            continue
        with db.session() as s:
            stream = Stream(
                kind="video",
                youtube_id=info.youtube_id,
                url=info.url,
                title=info.title,
                channel_name=info.channel_name,
                thumbnail_url=info.thumbnail_url,
                original_upload_date=info.original_upload_date,
                description=info.description,
                youtube_tags=info.tags,
            )
            s.add(stream)
            s.flush()

            output_path = staging_dir / f"vod-{info.youtube_id}.mkv"
            rec = Recording(
                stream_id=stream.id,
                started_at=_dt.datetime.now(_dt.UTC),
                path=str(output_path),
                status="vod_queued",
                is_buffer=False,
                auto_publish_after_download=False,  # playlists never auto-publish
            )
            s.add(rec)
            s.flush()
            new_rec_ids.append(rec.id)

    for rid in new_rec_ids:
        await request.app.state.vod_queue.enqueue(rid)
    return {"queued_recording_ids": new_rec_ids}
```

- [ ] **Step 3: Mount router in main.py**

Add to the FastAPI app's router includes:

```python
from concertpvr.api import playlists as _playlists_api
app.include_router(_playlists_api.router)
```

- [ ] **Step 4: Tests**

```python
# tests/test_playlists_api.py
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

from concertpvr.main import create_app
from concertpvr.playlist_ingest import PlaylistEntry, PlaylistInfo
from concertpvr.ytdlp import StreamInfo


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))
    with TestClient(create_app()) as c:
        yield c


def test_ingest_returns_playlist_with_items(client):
    fake_info = PlaylistInfo(
        playlist_id="PL123",
        playlist_title="Best of KEXP 2025",
        count=2,
        entries=[
            PlaylistEntry(youtube_id="a", title="Song A", url="https://a", channel_name="KEXP",
                          thumbnail_url=None, duration_s=300, upload_date=None),
            PlaylistEntry(youtube_id="b", title="Song B", url="https://b", channel_name="KEXP",
                          thumbnail_url=None, duration_s=240, upload_date=None),
        ],
    )

    async def _fake_expand(_url, **_kw):
        return fake_info

    with patch("concertpvr.api.playlists.expand_playlist", side_effect=_fake_expand):
        r = client.post("/api/playlists/ingest", json={"url": "https://www.youtube.com/playlist?list=PL123"})
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "playlist"
    assert body["count"] == 2
    assert len(body["items"]) == 2
    assert body["items"][0]["youtube_id"] == "a"
    assert body["items"][0]["is_already_known"] is False


def test_confirm_creates_streams_and_queues(client, monkeypatch):
    info_a = StreamInfo(youtube_id="a", url="https://a", title="A", channel_name="K",
                       is_live=False, thumbnail_url=None)
    info_b = StreamInfo(youtube_id="b", url="https://b", title="B", channel_name="K",
                       is_live=False, thumbnail_url=None)

    async def _probe(url, **_kw):
        return {"https://www.youtube.com/watch?v=a": info_a,
                "https://www.youtube.com/watch?v=b": info_b}[url]

    fake_queue = MagicMock()
    fake_queue.enqueue = AsyncMock()
    monkeypatch.setattr(client.app.state, "vod_queue", fake_queue)

    with patch("concertpvr.api.playlists.probe", side_effect=_probe):
        r = client.post("/api/playlists/ingest/confirm", json={"video_ids": ["a", "b"]})
    assert r.status_code == 201
    body = r.json()
    assert len(body["queued_recording_ids"]) == 2
    assert fake_queue.enqueue.await_count == 2
```

- [ ] **Step 5: Run + commit**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_playlists_api.py -v
./.venv/Scripts/python.exe -m mypy src/
git add src/concertpvr/playlist_ingest.py src/concertpvr/api/playlists.py src/concertpvr/main.py tests/test_playlists_api.py
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(playlists): ingest + confirm endpoints with playlist_ingest module"
```

---

## Wave 5 — Publisher metadata + lifecycle

### Task 11: SegmentMeta genres + plot + NFO emission

**Files:**
- Modify: `src/concertpvr/metadata.py`
- Modify: `tests/test_metadata.py`

- [ ] **Step 1: Extend SegmentMeta + build_nfo**

In `metadata.py`, add fields to the dataclass:

```python
@dataclass(frozen=True)
class SegmentMeta:
    artist: str
    title: str | None
    festival: str | None
    venue: str | None
    year: int
    date: _dt.date | None
    duration_s: int
    width: int | None
    height: int | None
    # New v0.3:
    plot: str | None = None
    genres: list[str] = field(default_factory=list)  # empty = legacy "Concert"
```

Add `from dataclasses import field` import if missing.

In `build_nfo`, replace the hardcoded genre line:

```python
        if meta.plot:
            # Truncate to 2000 chars to keep NFO reasonable
            plot_text = meta.plot[:2000]
            lines.append(f"  <plot>{escape(plot_text)}</plot>")
        if meta.genres:
            for g in meta.genres:
                if g.strip():
                    lines.append(f"  <genre>{escape(g.strip())}</genre>")
        else:
            lines.append("  <genre>Concert</genre>")
        lines.append("  <tag>concertpvr</tag>")
```

- [ ] **Step 2: Tests**

```python
def test_nfo_emits_multiple_genres():
    from concertpvr.metadata import MetadataBuilder, SegmentMeta
    meta = SegmentMeta(
        artist="Khruangbin", title="Tiny Desk", festival=None, venue=None,
        year=2020, date=None, duration_s=1122, width=1920, height=1080,
        genres=["Indie", "Psych", "Funk"],
    )
    out = tmp_path / "movie.nfo"  # use tmp_path fixture
    builder = MetadataBuilder()
    builder.build_nfo(meta, tmp_path)
    content = (tmp_path / "movie.nfo").read_text()
    assert "<genre>Indie</genre>" in content
    assert "<genre>Psych</genre>" in content
    assert "<genre>Funk</genre>" in content


def test_nfo_falls_back_to_concert_when_no_genres(tmp_path):
    # ... assert <genre>Concert</genre> + <tag>concertpvr</tag> present ...


def test_nfo_emits_plot_when_set(tmp_path):
    meta = SegmentMeta(..., plot="A beautiful set from the rural Texas garage.")
    # ... assert <plot>A beautiful set...</plot> ...


def test_nfo_omits_plot_when_none(tmp_path):
    meta = SegmentMeta(..., plot=None)
    # ... assert <plot> absent ...


def test_nfo_truncates_long_plot(tmp_path):
    long_plot = "x" * 5000
    meta = SegmentMeta(..., plot=long_plot)
    # ... assert plot in NFO is at most 2000 chars ...
```

- [ ] **Step 3: Run + commit**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_metadata.py -v
git add src/concertpvr/metadata.py tests/test_metadata.py
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(metadata): NFO emits genres list + plot element; backward-compat fallback"
```

---

### Task 12: Publisher token semantics + folder_pattern validator extension

**Files:**
- Modify: `src/concertpvr/publisher.py`
- Modify: `src/concertpvr/schemas.py` (extend folder_pattern validator)
- Modify: `tests/test_publisher.py`
- Modify: `tests/test_settings_api.py`

- [ ] **Step 1: Update publisher.py for new token semantics**

Find the existing token resolution in publisher.py. Update:

```python
        # year: prefer original_upload_date for VODs, fallback to recording.started_at
        if year is None:
            if stream and stream.original_upload_date:
                year = stream.original_upload_date.year
            elif rec_started:
                year = rec_started.year
            else:
                year = _dt.datetime.now(_dt.UTC).year
        # date: same priority
        date_val: _dt.date | None = (
            stream.original_upload_date if stream and stream.original_upload_date
            else rec_started.date() if rec_started else None
        )
        # festival default: per-kind dispatch
        if festival is None and stream:
            if stream.kind == "video":
                festival = stream.channel_name  # default for VODs
            elif "—" in (stream.title or ""):
                festival = stream.title.split("—")[0].strip()
        if venue is None and stream and stream.kind != "video" and "—" in (stream.title or ""):
            venue = stream.title.split("—", 1)[1].strip()

        # New {channel} token:
        channel_val = stream.channel_name if stream else ""

        try:
            folder_name = self._folder_pattern.format(
                artist=artist,
                festival=festival or "",
                venue=venue or "",
                year=year,
                date=date_val.isoformat() if date_val else "",
                title=title or artist,
                channel=channel_val,
            ).strip()
        except (KeyError, IndexError) as e:
            raise ValueError(f"invalid folder_pattern token: {e}") from e
```

(Adapt to existing variable names; the `stream` variable may not exist in scope — fetch it from the DB session like `rec_started` is fetched.)

- [ ] **Step 2: Resolve genres + plot for SegmentMeta**

In publisher.py, where SegmentMeta is constructed, resolve genres from per-segment override + watcher default, and pull plot from stream.description:

```python
        # Resolve genres: segment.genres > watcher.default_genres > []
        resolved_genres: list[str] = []
        if seg.genres:
            resolved_genres = [g.strip() for g in seg.genres.split(",") if g.strip()]
        elif stream and stream.watcher_id:
            with self._db.session() as s2:
                from concertpvr.models import Watcher
                watcher = s2.get(Watcher, stream.watcher_id)
                if watcher and watcher.default_genres:
                    resolved_genres = [g.strip() for g in watcher.default_genres.split(",") if g.strip()]

        # Plot: stream.description for VODs (single-segment case)
        plot: str | None = None
        if stream and stream.kind == "video" and stream.description:
            plot = stream.description

        meta = SegmentMeta(
            artist=artist, title=title, festival=festival, venue=venue, year=year,
            date=date_val, duration_s=int(end_s - start_s),
            width=rec_width, height=rec_height,
            plot=plot, genres=resolved_genres,
        )
```

- [ ] **Step 3: Extend folder_pattern validator in schemas.py**

In the existing `_validate_folder_pattern` (added in v0.2 T4), extend the test format() call:

```python
            v.format(
                artist="Test", festival="Festival", venue="Venue",
                year=2026, date="2026-01-01", title="Title",
                channel="Channel",  # new v0.3 token
            )
```

- [ ] **Step 4: Tests**

```python
# tests/test_publisher.py — append:

@pytest.mark.asyncio
async def test_publish_uses_upload_date_year_for_vod(db, tmp_path, fixture_video):
    """A VOD with original_upload_date in 2020 should produce {year}=2020 even
    if the recording was downloaded in 2026."""
    # ... seed stream(kind=video, original_upload_date=2020-09-02), seed recording(started_at=2026-04-26),
    # publish with folder_pattern="{artist} ({year})", assert emby_path contains "(2020)" ...


@pytest.mark.asyncio
async def test_publish_channel_token(db, tmp_path, fixture_video):
    """folder_pattern with {channel} resolves to stream.channel_name."""
    # ... seed stream(channel_name="NPR Music"), folder_pattern="{channel}/{artist}",
    # assert emby_path contains "NPR Music/Khruangbin" ...


@pytest.mark.asyncio
async def test_publish_festival_defaults_to_channel_name_for_vod(db, tmp_path, fixture_video):
    # ... assert {festival} resolves to channel_name when stream.kind=video ...


@pytest.mark.asyncio
async def test_publish_genres_resolution_per_segment_overrides_watcher(...):
    """Segment.genres set → use that; otherwise inherit watcher.default_genres."""


@pytest.mark.asyncio
async def test_publish_plot_includes_description_for_vods(...):
    """stream.kind=video with description → NFO has <plot> element."""
```

```python
# tests/test_settings_api.py — append:

def test_patch_settings_accepts_channel_in_folder_pattern(client):
    r = client.patch("/api/settings", json={"folder_pattern": "{channel}/{artist} ({year})"})
    assert r.status_code == 200
    assert r.json()["folder_pattern"] == "{channel}/{artist} ({year})"
```

- [ ] **Step 5: Run + commit**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_publisher.py tests/test_settings_api.py -v
git add src/concertpvr/publisher.py src/concertpvr/schemas.py tests/test_publisher.py tests/test_settings_api.py
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(publisher): {channel} token, VOD-aware {year}/{date}/{festival} fallbacks, genres + plot resolution"
```

---

### Task 13: Source deletion (DELETE endpoint + auto-delete trigger)

**Files:**
- Modify: `src/concertpvr/api/recordings.py`
- Modify: `src/concertpvr/publisher.py`
- Modify: `tests/test_recordings_api.py`
- Modify: `tests/test_publisher.py`

- [ ] **Step 1: Add DELETE /api/recordings/{id}/source + POST /retry endpoints**

```python
# api/recordings.py:

@router.post("/recordings/{recording_id}/retry", status_code=200)
async def retry_recording(
    recording_id: int,
    request: Request,
    db: Database = Depends(get_db),
) -> dict:
    """Re-enqueue a vod_failed recording to the VOD queue."""
    with db.session() as s:
        rec = s.get(Recording, recording_id)
        if rec is None:
            raise HTTPException(404, "recording not found")
        if rec.status != "vod_failed":
            raise HTTPException(409, f"can't retry recording with status={rec.status}")
        rec.status = "vod_queued"
        rec.error = None
    await request.app.state.vod_queue.enqueue(recording_id)
    return {"status": "vod_queued"}


@router.delete("/recordings/{recording_id}/source", status_code=204)
def delete_recording_source(
    recording_id: int,
    db: Database = Depends(get_db),
) -> None:
    import shutil
    from pathlib import Path
    from sqlalchemy import select
    from concertpvr.models import Segment

    with db.session() as s:
        rec = s.get(Recording, recording_id)
        if rec is None:
            raise HTTPException(404, "recording not found")
        if rec.source_deleted:
            raise HTTPException(409, "source already deleted")

        # Verify all segments are published.
        segs = list(s.scalars(select(Segment).where(Segment.recording_id == recording_id)))
        if not segs:
            raise HTTPException(409, "no segments — refusing to delete source of an unsegmented recording")
        unpublished = [seg for seg in segs if seg.status != "published"]
        if unpublished:
            raise HTTPException(
                409,
                f"{len(unpublished)} segment(s) not published — refusing to delete source",
            )

        path = Path(rec.path)
        # Remove file or fragment dir
        try:
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
        except OSError as e:
            raise HTTPException(500, f"failed to delete source: {e}") from e

        rec.source_deleted = True
```

- [ ] **Step 2: Wire auto-delete into publisher**

In publisher.py, at the end of the publish() success path (after segment is marked published):

```python
        # Check auto-delete-source: if all segments now published and watcher/global says delete, do it.
        if seg.status == "published":
            with self._db.session() as s:
                from sqlalchemy import select
                from concertpvr.models import Recording, Segment, Settings, Watcher
                rec = s.get(Recording, seg.recording_id)
                if rec is None or rec.source_deleted:
                    return
                all_segs = list(s.scalars(select(Segment).where(Segment.recording_id == rec.id)))
                if any(sg.status != "published" for sg in all_segs):
                    return  # not all published yet
                # Resolve auto-delete preference
                stream = s.get(Stream, rec.stream_id)
                watcher_pref: bool | None = None
                if stream and stream.watcher_id:
                    watcher = s.get(Watcher, stream.watcher_id)
                    if watcher:
                        watcher_pref = watcher.auto_delete_source_after_publish
                if watcher_pref is None:
                    settings_row = s.get(Settings, 1)
                    delete = bool(settings_row and settings_row.auto_delete_source_after_publish)
                else:
                    delete = watcher_pref
                if delete:
                    import shutil
                    from pathlib import Path
                    path = Path(rec.path)
                    try:
                        if path.is_dir():
                            shutil.rmtree(path)
                        elif path.exists():
                            path.unlink()
                        rec.source_deleted = True
                    except OSError:
                        logger.exception("auto-delete-source failed for rec %d", rec.id)
```

- [ ] **Step 3: Tests**

```python
# tests/test_recordings_api.py:

def test_delete_source_404_for_unknown(client):
    r = client.delete("/api/recordings/99999/source")
    assert r.status_code == 404


def test_delete_source_409_when_no_segments(client):
    rid = _seed_recording_with_no_segments(client)
    r = client.delete(f"/api/recordings/{rid}/source")
    assert r.status_code == 409


def test_delete_source_409_when_any_segment_unpublished(client):
    rid = _seed_with_segment(client, seg_status="draft")
    r = client.delete(f"/api/recordings/{rid}/source")
    assert r.status_code == 409


def test_delete_source_204_when_all_segments_published(client, tmp_path):
    # ... create a real file at recording.path, seed segment with status=published, DELETE,
    # assert 204, file gone, recording.source_deleted=True ...


def test_delete_source_409_already_deleted(client):
    # ... seed recording with source_deleted=True, DELETE → 409 ...


def test_retry_404_for_unknown(client):
    r = client.post("/api/recordings/99999/retry")
    assert r.status_code == 404


def test_retry_409_when_not_vod_failed(client):
    rid = _seed_recording_with_status(client, "complete")
    r = client.post(f"/api/recordings/{rid}/retry")
    assert r.status_code == 409


def test_retry_requeues_vod_failed(client, monkeypatch):
    from unittest.mock import AsyncMock, MagicMock
    fake_queue = MagicMock()
    fake_queue.enqueue = AsyncMock()
    monkeypatch.setattr(client.app.state, "vod_queue", fake_queue)
    rid = _seed_recording_with_status(client, "vod_failed")
    r = client.post(f"/api/recordings/{rid}/retry")
    assert r.status_code == 200
    assert r.json()["status"] == "vod_queued"
    fake_queue.enqueue.assert_awaited_once_with(rid)
```

```python
# tests/test_publisher.py:

@pytest.mark.asyncio
async def test_publish_auto_deletes_source_when_settings_say_so(db, tmp_path, fixture_video, monkeypatch):
    """When settings.auto_delete_source_after_publish=True and all segs published, source deleted."""
    # ... seed settings auto_delete=True, publish the only segment, assert source file removed + source_deleted=True ...


@pytest.mark.asyncio
async def test_publish_does_not_delete_source_when_some_segments_unpublished(...):
    """Multiple segments, only one published → source preserved."""


@pytest.mark.asyncio
async def test_publish_watcher_pref_overrides_settings(...):
    """watcher.auto_delete_source_after_publish=False overrides settings=True."""
```

- [ ] **Step 4: Run + commit**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_recordings_api.py tests/test_publisher.py -v
git add src/concertpvr/api/recordings.py src/concertpvr/publisher.py tests/test_recordings_api.py tests/test_publisher.py
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(source-lifecycle): DELETE /recordings/{id}/source + auto-delete trigger after all-published"
```

---

## Wave 6 — Frontend

### Task 14: Streams → Sources rename + Add URL button + smart-paste modal scaffolding

**Files:**
- Rename: `frontend/src/pages/Streams.tsx` → `frontend/src/pages/Sources.tsx`
- Modify: `frontend/src/App.tsx` (routing + nav label)
- Modify: `frontend/src/components/Nav.tsx` (or wherever the sidebar lives)
- Create: `frontend/src/components/SmartPasteModal.tsx`

- [ ] **Step 1: Rename file and component**

```bash
git mv frontend/src/pages/Streams.tsx frontend/src/pages/Sources.tsx
```

In `Sources.tsx`, rename `StreamsPage` → `SourcesPage` and the page title text.

- [ ] **Step 2: Update routing**

In `frontend/src/App.tsx`, change the route element + import:

```tsx
import SourcesPage from "@/pages/Sources";
// ...
<Route path="/sources" element={<SourcesPage />} />
<Route path="/streams" element={<Navigate to="/sources" replace />} />  // backward-compat
```

In the nav sidebar, change the label "Streams" to "Sources".

- [ ] **Step 3: Add SmartPasteModal scaffold**

```tsx
// frontend/src/components/SmartPasteModal.tsx
import { useState } from "react";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";

type Mode = "input" | "video" | "channel" | "playlist" | "loading" | "error";

export function SmartPasteModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [url, setUrl] = useState("");
  const [mode, setMode] = useState<Mode>("input");
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<any>(null);

  async function probe() {
    setMode("loading");
    setError(null);
    try {
      // Single video URL → POST /api/streams; channel/playlist → routed via probe response.
      // For now, attempt POST /api/streams; if it returns 200 with {type: "channel"|"playlist"}, switch modes.
      const resp = await api.post<any>("/api/streams", { url });
      if (resp.kind === "live" || resp.kind === "video") {
        setData(resp);
        setMode("video");
      } else if (resp.type === "channel") {
        setData(resp);
        setMode("channel");
      } else if (resp.type === "playlist") {
        setData(resp);
        setMode("playlist");
      }
    } catch (e: any) {
      setError(e.message);
      setMode("error");
    }
  }

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent>
        {mode === "input" && (
          <>
            <h3>Add to library</h3>
            <p className="text-xs text-ink-dim">Paste any YouTube URL — single video, channel, or playlist.</p>
            <div className="flex gap-2 mt-3">
              <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://www.youtube.com/…" />
              <Button onClick={probe} disabled={!url}>Probe</Button>
            </div>
          </>
        )}
        {mode === "loading" && <p className="text-xs text-amber">Probing…</p>}
        {mode === "video" && <VideoResultPanel data={data} onClose={onClose} />}
        {mode === "channel" && <ChannelResultPanel data={data} onClose={onClose} />}
        {mode === "playlist" && <PlaylistResultPanel data={data} onClose={onClose} />}
        {mode === "error" && <p className="text-xs text-red-500">{error}</p>}
      </DialogContent>
    </Dialog>
  );
}

// Stub panels — implemented in Task 15
function VideoResultPanel({ data, onClose }: any) { return <div>Video: {data?.title}</div>; }
function ChannelResultPanel({ data, onClose }: any) { return <div>Channel</div>; }
function PlaylistResultPanel({ data, onClose }: any) { return <div>Playlist</div>; }
```

In `Sources.tsx`, add a state-driven button + modal:

```tsx
const [pasteOpen, setPasteOpen] = useState(false);
// ...
<Button onClick={() => setPasteOpen(true)}>+ Add URL</Button>
<SmartPasteModal open={pasteOpen} onClose={() => setPasteOpen(false)} />
```

- [ ] **Step 4: Backend — make POST /api/streams handle channel/playlist URLs**

In `api/streams.py`, before the existing single-video probe, detect URL type from the URL itself or from yt-dlp's response. Simplest: detect via URL pattern, then route:

```python
import re

_CHANNEL_RE = re.compile(r"youtube\.com/(@[^/?]+|channel/[A-Za-z0-9_-]+|c/[^/?]+|user/[^/?]+)")
_PLAYLIST_RE = re.compile(r"[?&]list=([A-Za-z0-9_-]+)")


@router.post("/streams")
async def create_stream(body: StreamCreate, request: Request, db: Database = Depends(get_db)):
    # Channel URL → 200 with {type:"channel", probed_meta}
    if _CHANNEL_RE.search(body.url) and "watch?v=" not in body.url:
        from concertpvr.ytdlp_channels import probe_channel
        try:
            ch = await probe_channel(body.url, cookies_path=_resolve_cookies_path(db))
        except ProbeError as e:
            raise HTTPException(400, str(e))
        return {"type": "channel", "channel_name": ch.channel_name, "channel_id": ch.channel_id, "url": body.url}

    # Playlist URL → 200 with {type:"playlist", count, items}
    if _PLAYLIST_RE.search(body.url) and "watch?v=" not in body.url:
        from concertpvr.playlist_ingest import expand_playlist
        try:
            info = await expand_playlist(body.url, cookies_path=_resolve_cookies_path(db))
        except ProbeError as e:
            raise HTTPException(400, str(e))
        return {"type": "playlist", "playlist_id": info.playlist_id,
                "playlist_title": info.playlist_title, "count": info.count,
                "items": [...]}  # similar to PlaylistIngestResponse

    # Else: single-video flow (existing + Task 7 VOD additions)
    # ...
```

- [ ] **Step 5: Run typecheck + build + commit**

```bash
cd frontend && npm run typecheck && npm run build && cd ..
./.venv/Scripts/python.exe -m pytest tests/test_streams_api.py -v
./.venv/Scripts/python.exe -m mypy src/
git add frontend/src/pages/Sources.tsx frontend/src/App.tsx frontend/src/components/Nav.tsx frontend/src/components/SmartPasteModal.tsx src/concertpvr/api/streams.py
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(frontend): rename Streams → Sources + Add URL smart-paste modal scaffolding"
```

---

### Task 15: Smart-paste modal — three result modes + Sources page extensions

**Files:**
- Modify: `frontend/src/components/SmartPasteModal.tsx`
- Modify: `frontend/src/pages/Sources.tsx`
- Modify: `frontend/src/lib/query.ts`
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Implement the three result panels**

Each panel renders the layouts shown in mockup #2:
- `VideoResultPanel`: card with thumbnail/title/channel + setlist-detected indicator + "Queue download" button (closes modal, shows toast).
- `ChannelResultPanel`: card with channel info + 3 toggle checkboxes (live/VOD/auto-publish) + "Subscribe" button (calls POST /api/watchers, navigates to watcher page).
- `PlaylistResultPanel`: header + per-item checkboxes (filterable, with "already in library" greyed out) + "Add N" button (calls POST /api/playlists/ingest/confirm).

Code per panel goes here — be explicit; no "similar to other panels" handwave.

```tsx
function VideoResultPanel({ data, onClose }: { data: Stream; onClose: () => void }) {
  const queryClient = useQueryClient();
  return (
    <div>
      <div className="flex gap-3 my-3">
        {data.thumbnail_url && <img src={data.thumbnail_url} className="w-32 rounded" />}
        <div>
          <h4 className="font-medium">{data.title}</h4>
          <p className="text-xs text-ink-dim">{data.channel_name}</p>
          {data.detected_setlist_source && (
            <p className="text-xs text-sage mt-1">🎵 Setlist detected ({data.detected_setlist_source})</p>
          )}
        </div>
      </div>
      <div className="flex gap-2 justify-end">
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button onClick={() => {
          queryClient.invalidateQueries({ queryKey: ["streams"] });
          queryClient.invalidateQueries({ queryKey: ["recordings"] });
          onClose();
        }}>Queue download</Button>
      </div>
    </div>
  );
}

function ChannelResultPanel({ data, onClose }: { data: any; onClose: () => void }) {
  const [watchLive, setWatchLive] = useState(false);
  const [watchVod, setWatchVod] = useState(true);
  const [autoPublish, setAutoPublish] = useState(false);
  const navigate = useNavigate();
  const subscribe = useMutation({
    mutationFn: () => api.post<Watcher>("/api/watchers", {
      channel_url: data.url, watch_live: watchLive,
      watch_vod_uploads: watchVod, auto_publish: autoPublish,
    }),
    onSuccess: (w) => { onClose(); navigate(`/watchers/${w.id}`); },
  });
  return (
    <div>
      <h4 className="font-medium">{data.channel_name}</h4>
      <p className="text-xs text-ink-dim">@{data.channel_id}</p>
      <div className="my-3 space-y-2">
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={watchLive} onChange={(e) => setWatchLive(e.target.checked)} />
          Live broadcasts
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={watchVod} onChange={(e) => setWatchVod(e.target.checked)} />
          New VOD uploads
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={autoPublish} onChange={(e) => setAutoPublish(e.target.checked)} />
          Auto-publish to Emby
        </label>
      </div>
      <div className="flex gap-2 justify-end">
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button onClick={() => subscribe.mutate()} disabled={subscribe.isPending}>Subscribe</Button>
      </div>
    </div>
  );
}

function PlaylistResultPanel({ data, onClose }: { data: any; onClose: () => void }) {
  const [filter, setFilter] = useState("");
  const [selected, setSelected] = useState<Set<string>>(
    new Set(data.items.filter((i: any) => !i.is_already_known).map((i: any) => i.youtube_id))
  );
  const queryClient = useQueryClient();
  const visible = data.items.filter((i: any) =>
    !filter || i.title.toLowerCase().includes(filter.toLowerCase())
  );
  const confirm = useMutation({
    mutationFn: () => api.post("/api/playlists/ingest/confirm", { video_ids: Array.from(selected) }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["recordings"] });
      onClose();
    },
  });
  return (
    <div>
      <h4 className="font-medium">{data.playlist_title}</h4>
      <p className="text-xs text-ink-dim">{data.count} videos</p>
      <Input
        placeholder="Filter by title…"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        className="my-2"
      />
      <div className="max-h-72 overflow-y-auto space-y-1">
        {visible.map((item: any) => {
          const checked = selected.has(item.youtube_id);
          return (
            <label key={item.youtube_id}
                   className={`flex items-center gap-2 text-xs p-1 ${item.is_already_known ? "opacity-40" : ""}`}>
              <input
                type="checkbox"
                disabled={item.is_already_known}
                checked={checked && !item.is_already_known}
                onChange={(e) => {
                  const next = new Set(selected);
                  if (e.target.checked) next.add(item.youtube_id);
                  else next.delete(item.youtube_id);
                  setSelected(next);
                }}
              />
              <span className="flex-1">{item.title}</span>
              {item.is_already_known && <span className="text-ink-dim">already in library</span>}
            </label>
          );
        })}
      </div>
      <div className="flex gap-2 justify-end mt-3">
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button onClick={() => confirm.mutate()} disabled={confirm.isPending || selected.size === 0}>
          Queue {selected.size} downloads
        </Button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Sources page — kind + watcher filter chips, kind badge, status column**

In `Sources.tsx`, add state + filter chip rows + the new column rendering. Specifics per mockup #1.

- [ ] **Step 3: Typecheck + build + commit**

```bash
cd frontend && npm run typecheck && npm run build && cd ..
git add frontend/src/components/SmartPasteModal.tsx frontend/src/pages/Sources.tsx frontend/src/lib/query.ts frontend/src/lib/api.ts
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(frontend): smart-paste modal three modes + Sources kind/watcher filter chips"
```

---

### Task 16: Watcher detail Settings tab — VOD fields

**Files:**
- Modify: `frontend/src/pages/WatcherDetail.tsx`

- [ ] **Step 1: Add the form sections**

Per mockup #3: two-column layout, left side has live/VOD checkboxes + VOD filters + segmentation dropdown; right side has library defaults + automation toggles + activity stats.

```tsx
// In WatcherDetail.tsx (existing component), within the form:
<section>
  <h3 className="text-xs uppercase text-ink-dim mb-2">Watching for</h3>
  <Checkbox label="Live broadcasts" {...form.register("watch_live")} />
  <Checkbox label="New VOD uploads" {...form.register("watch_vod_uploads")} />
</section>

<section className="mt-6">
  <h3 className="text-xs uppercase text-ink-dim mb-2">VOD filters</h3>
  <Field label="Title filter (regex)" helper="Empty = all uploads.">
    <Input {...form.register("vod_title_filter")} />
  </Field>
  <Field
    label="Artist extraction (regex with named group)"
    helper={<>Must include <code>(?P&lt;artist&gt;…)</code>. No match → manual review.</>}
  >
    <Input {...form.register("vod_artist_regex")} />
  </Field>
  <Field label="Segmentation mode">
    <Select {...form.register("vod_segmentation_mode")}>
      <option value="chapters">chapters</option>
      <option value="whole-video">whole-video</option>
      <option value="manual">manual</option>
    </Select>
  </Field>
</section>

<section className="mt-6">
  <h3 className="text-xs uppercase text-ink-dim mb-2">Library defaults</h3>
  <Field label="Default genres" helper="Comma-separated.">
    <Input {...form.register("default_genres")} />
  </Field>
</section>

<section className="mt-6">
  <h3 className="text-xs uppercase text-ink-dim mb-2">Automation</h3>
  <Checkbox
    label="Auto-publish to Emby"
    helper="Only fires when the artist regex matches cleanly."
    {...form.register("auto_publish")}
  />
  <Checkbox
    label="Extract setlists from comments"
    helper="Slower polling (~3-5s extra per upload)."
    {...form.register("extract_setlist_from_comments")}
  />
  <Checkbox
    label="Auto-delete source after publish"
    helper="When all segments are published, source file is removed."
    {...form.register("auto_delete_source_after_publish")}
  />
</section>
```

- [ ] **Step 2: Typecheck + build + commit**

```bash
cd frontend && npm run typecheck && npm run build && cd ..
git add frontend/src/pages/WatcherDetail.tsx
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(frontend): watcher detail Settings tab with VOD filters/automation/genres"
```

---

### Task 17: Watcher Backlog tab

**Files:**
- Modify: `frontend/src/pages/WatcherDetail.tsx`
- Create: `frontend/src/components/BacklogBrowser.tsx`
- Modify: `frontend/src/lib/query.ts`

- [ ] **Step 1: Add hook**

```tsx
// query.ts
export function useWatcherBacklog(watcherId: number, sort: string = "newest", offset = 0) {
  return useQuery<BacklogItem[]>({
    queryKey: ["backlog", watcherId, sort, offset],
    queryFn: () => api.get<BacklogItem[]>(`/api/watchers/${watcherId}/backlog?sort=${sort}&offset=${offset}`),
  });
}
```

- [ ] **Step 2: Create BacklogBrowser component**

Per mockup #3 backlog tab — cards grid with thumbnails, state badges, multi-select, sort chips.

- [ ] **Step 3: Wire into WatcherDetail with tabs**

Two-tab layout (Settings / Backlog) with the existing form on Settings tab and BacklogBrowser on Backlog tab.

- [ ] **Step 4: Typecheck + build + commit**

```bash
cd frontend && npm run typecheck && npm run build && cd ..
git add frontend/src/pages/WatcherDetail.tsx frontend/src/components/BacklogBrowser.tsx frontend/src/lib/query.ts
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(frontend): watcher Backlog tab with multi-select grid + bulk download"
```

---

### Task 18: Recordings page — VOD statuses + determinate progress

**Files:**
- Modify: `frontend/src/pages/Recordings.tsx`
- Modify: `frontend/src/components/LiveProgressBar.tsx`

- [ ] **Step 1: Add VOD statuses to filter chips**

Recordings page already has a status filter (added in v0.2). Extend chip values to include `vod_queued`, `vod_downloading`, `vod_failed`.

- [ ] **Step 2: Add determinate mode to LiveProgressBar**

```tsx
type Props = {
  // existing fields...
  mode?: "indeterminate" | "determinate";
  pct?: number;
  etaS?: number;
};

// in render:
{mode === "determinate" && pct !== undefined ? (
  <div className="h-1 bg-base-2 rounded">
    <div className="h-full bg-sage" style={{ width: `${pct}%` }} />
  </div>
) : (/* existing indeterminate live UI */)}
{etaS !== undefined && <span className="text-xs">ETA {formatEta(etaS)}</span>}
```

For VOD recordings, pass `mode="determinate"` and the progress event fields.

- [ ] **Step 3: Typecheck + build + commit**

```bash
cd frontend && npm run typecheck && npm run build && cd ..
git add frontend/src/pages/Recordings.tsx frontend/src/components/LiveProgressBar.tsx
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(frontend): Recordings page VOD statuses + determinate progress for vod_downloading"
```

---

### Task 19: Post-download review screen

**Files:**
- Create: `frontend/src/pages/PostDownloadReview.tsx`
- Modify: `frontend/src/App.tsx` (route)
- Modify: `frontend/src/lib/query.ts`

- [ ] **Step 1: Add the route**

```tsx
<Route path="/recordings/:id/review" element={<PostDownloadReview />} />
```

- [ ] **Step 2: Build the review page**

Per mockup #5: header card (thumbnail/title/channel/duration/upload date/description), detected setlist card (apply/edit/dismiss), segments list (per-row artist/title/range/genres/yt-tag suggestion chips), Save Draft / Open in Timeline editor / Publish to Emby buttons.

- [ ] **Step 3: Typecheck + build + commit**

```bash
cd frontend && npm run typecheck && npm run build && cd ..
git add frontend/src/pages/PostDownloadReview.tsx frontend/src/App.tsx frontend/src/lib/query.ts
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(frontend): post-download review screen with setlist + segments + genres"
```

---

### Task 20: Library + Sources genre filter, year filter on Library

**Files:**
- Modify: `frontend/src/pages/Library.tsx`
- Modify: `frontend/src/pages/Sources.tsx`

- [ ] **Step 1: Add genre filter chip row to both pages**

Multi-select chips with AND-logic across selected. Per mockup #4. Year filter is Library-only.

```tsx
const [selectedGenres, setSelectedGenres] = useState<Set<string>>(new Set());

const visible = (data ?? []).filter((seg) => {
  if (selectedGenres.size === 0) return true;
  const segGenres = (seg.genres || "").split(",").map(g => g.trim().toLowerCase());
  return Array.from(selectedGenres).every(g => segGenres.includes(g.toLowerCase()));
});
```

The available-genres list comes from a built-in array of ~30 common music genres + any genres seen in the visible data:

```tsx
const COMMON_GENRES = ["Rock", "Indie", "Alternative", "Pop", "Folk", "Jazz", "Electronic", "House",
  "Hip-Hop", "R&B", "Soul", "Funk", "Country", "Metal", "Punk", "Classical", "Blues", "Reggae",
  "Latin", "World", "Ambient", "Experimental", "Psych", "Garage", "Singer-Songwriter"];
```

- [ ] **Step 2: Typecheck + build + commit**

```bash
cd frontend && npm run typecheck && npm run build && cd ..
git add frontend/src/pages/Library.tsx frontend/src/pages/Sources.tsx
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(frontend): genre chip filter on Sources + Library; year filter on Library"
```

---

### Task 21: Dashboard split-stat strip

**Files:**
- Modify: `frontend/src/pages/Dashboard.tsx`

- [ ] **Step 1: Split "Recording now" into two cards**

```tsx
const liveActive = recordings.filter(r => r.status === "recording").length;
const vodActive = recordings.filter(r => r.status === "vod_downloading").length;
const liveMax = settings?.max_concurrent_recordings ?? 4;
const vodMax = settings?.max_concurrent_vod_downloads ?? 2;

const stats = [
  { label: "Live now", value: `${liveActive}/${liveMax}`, color: "terra" },
  { label: "VODs downloading", value: `${vodActive}/${vodMax}`, color: "sage" },
  { label: "Up next (24h)", value: scheduledNext24h, color: "amber" },
  { label: "Published this week", value: publishedThisWeek, color: "mauve" },
  { label: "Needs review", value: needsReview, color: "red" },
];
```

- [ ] **Step 2: Typecheck + build + commit**

```bash
cd frontend && npm run typecheck && npm run build && cd ..
git add frontend/src/pages/Dashboard.tsx
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(frontend): Dashboard splits Live now / VODs downloading into separate stat cards"
```

---

### Task 22: Settings page — VOD fields

**Files:**
- Modify: `frontend/src/pages/Settings.tsx`

- [ ] **Step 1: Add the new fields to the form**

```tsx
<Field label="Max concurrent VOD downloads" helper="VOD queue capacity (separate from live).">
  <Input type="number" min={1} max={8} {...form.register("max_concurrent_vod_downloads", { valueAsNumber: true })} />
</Field>
<Checkbox
  label="Auto-delete source after publish"
  helper="When all segments are published, the source file is removed. You won't be able to re-cut."
  {...form.register("auto_delete_source_after_publish")}
/>
```

- [ ] **Step 2: Typecheck + build + commit**

```bash
cd frontend && npm run typecheck && npm run build && cd ..
git add frontend/src/pages/Settings.tsx
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(frontend): Settings page — max_concurrent_vod_downloads + auto_delete_source toggle"
```

---

### Task 23: Timeline editor extensions — genres + setlist pre-fill + tag suggestions

**Files:**
- Modify: `frontend/src/pages/TimelineEditor.tsx`
- Modify: `frontend/src/components/SegmentSidebar.tsx`
- Modify: `frontend/src/components/SetlistPasteModal.tsx`

The Timeline editor is opened either when a user opts to manually segment a VOD (from the post-download review) or when reviewing live recordings. Both kinds need the new metadata fields.

- [ ] **Step 1: SegmentSidebar — add genres input + tag chip suggestions**

In `SegmentSidebar.tsx`, below the existing artist input for each segment, add:

```tsx
<Field label="Genres" helper="Comma-separated.">
  <Input
    value={seg.genres ?? ""}
    onChange={(e) => onPatch(seg.id, { genres: e.target.value })}
    placeholder="Indie, Alternative, Rock"
  />
</Field>

{stream?.youtube_tags && stream.youtube_tags.length > 0 && (
  <div className="mt-1">
    <span className="text-[10px] text-ink-dim mr-2">Suggestions:</span>
    {stream.youtube_tags.slice(0, 8).map((tag: string) => (
      <button
        key={tag}
        type="button"
        className="text-[10px] mr-1 mb-1 px-1.5 py-0.5 rounded bg-base-2 hover:bg-base-3"
        onClick={() => {
          const current = (seg.genres ?? "").split(",").map(g => g.trim()).filter(Boolean);
          if (!current.includes(tag)) {
            const next = [...current, tag].join(", ");
            onPatch(seg.id, { genres: next });
          }
        }}
      >
        + {tag}
      </button>
    ))}
  </div>
)}
```

The Stream's `youtube_tags` field needs to be plumbed down — pass it as a prop from TimelineEditor.

- [ ] **Step 2: SetlistPasteModal — pre-fill from detected_setlist_text**

In `SetlistPasteModal.tsx`, accept a new optional prop `defaultText: string | null` and use it as the initial value of the textarea:

```tsx
type Props = {
  open: boolean;
  onClose: () => void;
  onApply: (text: string) => void;
  defaultText?: string | null;
};

export function SetlistPasteModal({ open, onClose, onApply, defaultText }: Props) {
  const [text, setText] = useState(defaultText ?? "");
  useEffect(() => {
    if (open && defaultText) setText(defaultText);
  }, [open, defaultText]);
  // ... existing render ...
}
```

In `TimelineEditor.tsx` where `SetlistPasteModal` is rendered, pass:

```tsx
<SetlistPasteModal
  open={pasteOpen}
  onClose={() => setPasteOpen(false)}
  onApply={applySetlist}
  defaultText={stream?.detected_setlist_text}
/>
```

- [ ] **Step 3: Typecheck + build + commit**

```bash
cd frontend && npm run typecheck && npm run build && cd ..
git add frontend/src/pages/TimelineEditor.tsx frontend/src/components/SegmentSidebar.tsx frontend/src/components/SetlistPasteModal.tsx
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(frontend): timeline editor — genres input + tag suggestions + setlist pre-fill"
```

---

## Wave 7 — Wrap-up

### Task 24: Final sweep + CHANGELOG + release-checklist + tag v0.3.0

- [ ] **Step 1: Backend sweep**

```bash
./.venv/Scripts/python.exe -m ruff check src/ tests/
./.venv/Scripts/python.exe -m ruff format --check src/ tests/
./.venv/Scripts/python.exe -m mypy src/
./.venv/Scripts/python.exe -m pytest -q
```

If anything fails, fix per the standard guardrails (no spec-weakening, no test rewriting that hides spec violations, no mypy laxity).

Apply ruff format if needed:

```bash
./.venv/Scripts/python.exe -m ruff format src/ tests/
```

- [ ] **Step 2: Frontend sweep**

```bash
cd frontend && npm run typecheck && npm run build && cd ..
```

- [ ] **Step 3: Update CHANGELOG.md**

Prepend:

```markdown
## v0.3.0 — 2026-04-26

### Features

- **Download non-live YouTube performances.** Tiny Desk Concerts, KEXP sets, NPR Music Field Recordings — three workflows: paste any URL, subscribe to a channel for auto-pull, or ingest an entire playlist.
- **Channel watchers learn VOD mode.** Existing watchers gain "Watch for new VOD uploads" + "Auto-publish to Emby" toggles. Forward-only by default; backlog browser to manually pick old videos.
- **Setlist auto-detection.** Description text, YouTube chapters, and (opt-in, slower) pinned/top comments parsed for timestamped setlists. Detected setlists surface on the post-download review screen with apply/edit/dismiss.
- **Per-watcher artist regex.** Named-group regex pattern extracts artist from titles ("Khruangbin: Tiny Desk Concert" → "Khruangbin"). No match → safe fallback to manual review even if auto-publish is on.
- **Genres.** Per-watcher default genres + per-segment overrides + click-to-add suggestions from YouTube tags. Genre filter on Sources and Library pages. NFO emits one `<genre>` per genre.
- **Source-file lifecycle.** Per-recording manual delete button (gated on all segments published), plus per-watcher and global auto-delete-after-publish settings.

### API

- `POST /api/streams` — handles single video / channel / playlist URLs (smart-paste routing).
- `GET /api/watchers/{id}/backlog` — paginated channel-videos listing with sort options.
- `POST /api/watchers/{id}/backlog/download` — bulk-download selected backlog items.
- `POST /api/playlists/ingest` + `/confirm` — playlist preview and bulk-add.
- `POST /api/recordings/{id}/retry` — retry a failed VOD download.
- `DELETE /api/recordings/{id}/source` — manual source-file removal (409 if any segment is unpublished).
- `PATCH /api/watchers/{id}` — accepts 9 new fields (live/VOD toggles, filters, regex, genres, auto-publish, auto-delete).

### Schema

- Migration `0008_vod_support` adds 20 columns across 5 tables (watchers, streams, segments, recordings, settings). All additive.

### UI

- Streams tab renamed to **Sources**; mixed live + video kinds with kind badges.
- "Add URL" smart-paste modal with three result modes.
- Watcher detail page extended: Settings tab with VOD filters/automation, Backlog tab with a multi-select cards grid.
- Post-download review screen for VODs.
- Dashboard split-stat strip: Live + VODs as separate cards.
- Genre filter chips on Sources + Library.

### Performance

- Separate VOD queue (default cap 2) — VOD downloads never starve the live recorder pool.
- Index on `streams.watcher_id` for the "From watcher" filter.

### Known limitations

- Backlog tab title filter and duration sort only — yt-dlp's flat-extract doesn't return tag/genre data cheaply.
- "Most viewed" sort on backlog is documented but not yet wired (would require full probe per item).
- External setlist sources (setlist.fm) not yet integrated; documented as future enhancement.
```

- [ ] **Step 4: Update docs/release-checklist.md**

Append:

```markdown
## VOD downloads (added v0.3)

- [ ] Paste a Tiny Desk URL on Sources page → modal probes → "Queue download" → recording appears in Recordings with `vod_downloading` status, progress updates live.
- [ ] After download completes, post-download review screen opens at `/recordings/{id}/review`. Setlist detected from description shown with Apply/Edit/Dismiss.
- [ ] Subscribe to a YouTube channel via smart-paste → watcher created → toggle "Watch for new VOD uploads" + set `vod_artist_regex` → next channel poll picks up new uploads, creates Recordings.
- [ ] With `auto_publish=true` on a watcher and matching artist regex → new VOD downloads, segments are auto-published to Emby without manual review.
- [ ] Backlog tab on watcher → see channel's recent videos → multi-select 3 → "Queue 3 downloads" → recordings appear in Recordings.
- [ ] Paste a playlist URL → preview modal shows items → confirm → N downloads queued.
- [ ] Genre filter on Library narrows to selected genre(s).
- [ ] Genre filter on Sources narrows to selected genre(s).
- [ ] Settings → flip `auto_delete_source_after_publish` ON, publish all segments on a recording → source file removed; recording shows "Source: deleted".
- [ ] DELETE `/api/recordings/{id}/source` returns 409 when any segment is unpublished.
- [ ] At max concurrent VOD downloads, queueing more keeps them in `vod_queued` state; live recordings unaffected.
```

- [ ] **Step 5: Commit + tag**

```bash
git add -A
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "chore: v0.3 wrap-up — sweep + CHANGELOG + release-checklist" || echo "(nothing to commit)"

git tag -a phase-9-v0.3 -m "Phase 9 complete: VOD downloads"
git tag -a v0.3.0 -m "v0.3.0 — VOD downloads (Tiny Desk, KEXP, NPR Music, playlists)"

git log --oneline v0.2.0..HEAD | head -40
```

---

## v0.3.0 done

At tag `v0.3.0`:
- Three workflows live: URL paste, channel subscription with auto-pull, playlist ingest
- Backlog browser as curated alternative to D auto-backfill
- Per-watcher auto-publish gated on regex artist extraction
- Setlist + genre + plot metadata flowing into NFO
- Source-file lifecycle with auto-delete after publish
- Migration 0008 (20 additive columns)
- ~30 new backend tests, full suite ~220
- Frontend builds clean, no breaking API changes
- All existing live recording behavior bit-identical for users who don't opt in
