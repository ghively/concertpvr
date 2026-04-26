# concertpvr — Phase 5: Channel Watchers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Subscribe to a YouTube channel → APScheduler polls the channel every 60s → when a new live broadcast appears (and matches an optional title regex), auto-record it. Adds the Watchers screen to manage subscriptions.

**Architecture:** A new `channel_watchers` table stores subscriptions. A periodic APScheduler job runs `poll_all_channel_watchers()` which queries each enabled watcher's channel via yt-dlp's `extract_info` against `<channel>/streams`. New live broadcasts (deduped by yt-dlp video id against `last_live_id`) that match the optional `title_filter` regex trigger a buffer-style recording. The recording-start logic is extracted from `api/streams.py` into a shared `recording_starter` module so both manual buffer toggles and channel auto-triggers use the same code path.

**Tech Stack:** No new dependencies. Uses `yt-dlp` library, `RecorderPool`, `BufferManager`, `Broadcaster`, `APScheduler` (all in place).

**Spec reference:** `docs/superpowers/specs/2026-04-24-concertpvr-design.md` — §5 channel_watchers table, §6.4 Flow D — channel watcher, §7.6 Channel Watchers screen.

**Phase 4b baseline (already on `main`):** 138 backend tests, full timeline UI, Emby publishing pipeline. Existing patterns: APScheduler memory jobstore for closures, `# noqa: B008`, expunge before return, etc.

---

## File structure (additions in this phase)

```
src/concertpvr/
├── recording_starter.py        # NEW: extracted shared recording-start logic
├── ytdlp_channels.py           # NEW: poll a channel for live broadcasts via yt-dlp
├── channel_poller.py           # NEW: poll_all_channel_watchers() — APScheduler job target
└── api/
    ├── streams.py              # MODIFY: use recording_starter.start_buffer_recording
    └── channel_watchers.py     # NEW: /api/channel-watchers CRUD

alembic/versions/
└── 0005_channel_watchers.py

tests/
├── test_ytdlp_channels.py
├── test_channel_poller.py
├── test_channel_watchers_api.py
└── fixtures/
    └── ytdlp_channel_streams.json   # canned yt-dlp channel listing

frontend/src/
├── lib/
│   ├── api.ts                  # APPEND: ChannelWatcher type + clients
│   └── query.ts                # APPEND: hooks
├── components/
│   └── AddWatcherDialog.tsx    # NEW
└── pages/
    └── Watchers.tsx            # FULL implementation (was stub)
```

---

## Module interfaces (locked at design time)

**`recording_starter.start_buffer_recording`:**
```python
async def start_buffer_recording(
    *,
    stream_id: int,
    url: str,
    quality_format: str,
    db: Database,
    pool: RecorderPool,
    buf: BufferManager,
    bc: Broadcaster,
) -> int:  # returns the new Recording.id
    """Spawn a buffer-style RecorderWorker for the given stream and persist a Recording row."""
```

**`ytdlp_channels.fetch_channel_live_broadcasts(channel_url) -> list[BroadcastInfo]`:**
```python
@dataclass(frozen=True)
class BroadcastInfo:
    youtube_id: str
    url: str
    title: str
    channel_name: str
    is_live: bool
```
Wraps yt-dlp's `extract_info` against `<channel>/streams` (note: yt-dlp resolves channel handles like `@nprmusic` to a channel URL). Returns only entries where `is_live=True`. On any yt-dlp error, returns `[]` (logging-only — polling must never crash the scheduler).

**`channel_poller.poll_all_channel_watchers(*, db, pool, buf, bc, default_quality)`:**
- Top-level async function (importable by qualname for APScheduler).
- Iterates enabled `channel_watchers` rows.
- For each watcher: fetch broadcasts; filter by `last_live_id` and `title_filter`; for each match, ensure a `Stream` row exists, then call `start_buffer_recording`.
- Updates `last_polled` and `last_live_id` on each watcher.

---

## Task 1: Migration 0005 + ChannelWatcher model

**Files:**
- Modify: `src/concertpvr/models.py` (append ChannelWatcher class)
- Create: `alembic/versions/0005_channel_watchers.py`
- Modify: `tests/test_db.py` (append round-trip test)

- [ ] **Step 1: Append model**

After existing models in `src/concertpvr/models.py`, append:

```python
class ChannelWatcher(Base):
    __tablename__ = "channel_watchers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_url: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    channel_name: Mapped[str] = mapped_column(String, nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String, nullable=True)
    title_filter: Mapped[str | None] = mapped_column(String, nullable=True)
    quality_cap: Mapped[str | None] = mapped_column(String, nullable=True)
    retention_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_polled: Mapped[_dt.datetime | None] = mapped_column(DateTime, nullable=True)
    last_live_id: Mapped[str | None] = mapped_column(String, nullable=True)
    added_at: Mapped[_dt.datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: _dt.datetime.now(_dt.UTC)
    )
```

- [ ] **Step 2: Append round-trip test to `tests/test_db.py`**

```python
from concertpvr.models import ChannelWatcher


def test_channel_watcher_round_trip(tmp_db):
    Base.metadata.create_all(tmp_db.engine)

    with tmp_db.session() as s:
        w = ChannelWatcher(
            channel_url="https://www.youtube.com/@nprmusic",
            channel_name="NPR Music",
            title_filter="tiny desk",
            retention_days=14,
        )
        s.add(w)
        s.flush()
        wid = w.id

    with tmp_db.session() as s:
        loaded = s.get(ChannelWatcher, wid)
        assert loaded is not None
        assert loaded.channel_name == "NPR Music"
        assert loaded.title_filter == "tiny desk"
        assert loaded.enabled is True
        assert loaded.last_polled is None
        assert loaded.last_live_id is None
```

- [ ] **Step 3: Migration `alembic/versions/0005_channel_watchers.py`**

```python
"""channel_watchers table

Revision ID: 0005_channel_watchers
Revises: 0004_segments_setlists
Create Date: 2026-04-26
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_channel_watchers"
down_revision: str | None = "0004_segments_setlists"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "channel_watchers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("channel_url", sa.String(), nullable=False, unique=True),
        sa.Column("channel_name", sa.String(), nullable=False),
        sa.Column("avatar_url", sa.String(), nullable=True),
        sa.Column("title_filter", sa.String(), nullable=True),
        sa.Column("quality_cap", sa.String(), nullable=True),
        sa.Column("retention_days", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("last_polled", sa.DateTime(), nullable=True),
        sa.Column("last_live_id", sa.String(), nullable=True),
        sa.Column("added_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("channel_watchers")
```

- [ ] **Step 4: Run + commit**

```bash
./.venv/Scripts/python.exe -m pytest -q
```
Expected: 139 (138 + 1).

```bash
git add src/concertpvr/models.py alembic/versions/0005_channel_watchers.py tests/test_db.py
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(models): channel_watchers table"
```

---

## Task 2: Pydantic schemas

**File:** Modify `src/concertpvr/schemas.py` (append).

- [ ] **Step 1: Append**

```python
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
```

- [ ] **Step 2: Verify + commit**

```bash
./.venv/Scripts/python.exe -c "from concertpvr.schemas import ChannelWatcherRead, ChannelWatcherCreate, ChannelWatcherPatch; print('ok')"
git add src/concertpvr/schemas.py
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(schemas): pydantic models for channel_watchers"
```

---

## Task 3: Extract `recording_starter.start_buffer_recording` shared helper

The `_start_recording` helper currently lives inside `src/concertpvr/api/streams.py`. The channel poller needs the same logic. Extract it.

**Files:**
- Create: `src/concertpvr/recording_starter.py`
- Modify: `src/concertpvr/api/streams.py` (delegate to new helper)
- Create: `tests/test_recording_starter.py`

- [ ] **Step 1: Failing test**

```python
# tests/test_recording_starter.py
import datetime as dt
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from concertpvr.buffer import BufferManager
from concertpvr.db import Database
from concertpvr.models import Base, Recording, Stream
from concertpvr.recording_starter import start_buffer_recording
from concertpvr.ws import Broadcaster


@pytest.mark.asyncio
async def test_creates_recording_row_and_calls_pool_start(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'rs.db'}")
    Base.metadata.create_all(db.engine)

    with db.session() as s:
        stream = Stream(
            kind="live", youtube_id="x", url="https://example.com",
            title="t", channel_name="c",
        )
        s.add(stream)
        s.flush()
        sid = stream.id

    fake_pool = MagicMock()
    fake_pool.start = AsyncMock()
    buf = BufferManager(tmp_path / "buf")
    bc = Broadcaster()

    rec_id = await start_buffer_recording(
        stream_id=sid,
        url="https://example.com",
        quality_format="best",
        db=db,
        pool=fake_pool,
        buf=buf,
        bc=bc,
    )

    assert isinstance(rec_id, int)
    fake_pool.start.assert_awaited_once()

    with db.session() as s:
        rec = s.get(Recording, rec_id)
        assert rec is not None
        assert rec.stream_id == sid
        assert rec.is_buffer is True
        assert rec.status == "recording"
```

- [ ] **Step 2: Run — fails**

- [ ] **Step 3: Implement `src/concertpvr/recording_starter.py`**

```python
"""Shared helper for kicking off buffer-style recordings.

Used both by the streams API watch toggle and the channel poller.
"""

from __future__ import annotations

import datetime as _dt

from concertpvr.buffer import BufferManager
from concertpvr.db import Database
from concertpvr.models import Recording
from concertpvr.pool import RecorderPool
from concertpvr.process import AsyncSubprocessRunner
from concertpvr.recorder import RecorderProgress, RecorderWorker
from concertpvr.ws import Broadcaster


async def start_buffer_recording(
    *,
    stream_id: int,
    url: str,
    quality_format: str,
    db: Database,
    pool: RecorderPool,
    buf: BufferManager,
    bc: Broadcaster,
) -> int:
    """Spawn a buffer-style recorder. Returns the new Recording.id."""
    output_dir = buf.stream_dir(stream_id)

    async def on_progress(p: RecorderProgress) -> None:
        await bc.publish(
            f"streams.{stream_id}.progress",
            {
                "bytes_total": p.bytes_total,
                "bitrate_bps": p.bitrate_bps,
                "duration_s": p.duration_s,
                "fragment_count": p.fragment_count,
            },
        )

    worker = RecorderWorker(
        stream_id=stream_id,
        url=url,
        output_dir=output_dir,
        quality_format=quality_format,
        runner=AsyncSubprocessRunner(),
        on_progress=on_progress,
    )

    with db.session() as s:
        rec = Recording(
            stream_id=stream_id,
            started_at=_dt.datetime.now(_dt.UTC),
            path=str(output_dir),
            status="recording",
            is_buffer=True,
        )
        s.add(rec)
        s.flush()
        rec_id = rec.id

    await pool.start(worker)
    return rec_id
```

- [ ] **Step 4: Update `src/concertpvr/api/streams.py`**

In the existing `_start_recording` helper inside `api/streams.py`, replace its body with a call to `start_buffer_recording`:

```python
async def _start_recording(
    stream_id: int,
    url: str,
    quality: str,
    db: Database,
    pool: RecorderPool,
    buf: BufferManager,
    bc: Broadcaster,
) -> None:
    from concertpvr.recording_starter import start_buffer_recording
    await start_buffer_recording(
        stream_id=stream_id,
        url=url,
        quality_format=quality,
        db=db,
        pool=pool,
        buf=buf,
        bc=bc,
    )
```

The `AsyncSubprocessRunner` import previously used inside `_start_recording` can be removed if no longer needed at the top of `api/streams.py` (verify by running ruff). The `RecorderProgress`, `RecorderWorker`, `Recording`, `_dt as _dt` imports may also be unused in `api/streams.py` after this — let ruff catch those.

- [ ] **Step 5: Run + commit**

```bash
./.venv/Scripts/python.exe -m pytest -q
```
Expected: 140 (139 + 1). Existing tests in `test_streams_api.py` (which exercise `_start_recording` via the watch PATCH path) must continue to pass.

```bash
git add src/concertpvr/recording_starter.py src/concertpvr/api/streams.py tests/test_recording_starter.py
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "refactor(recording_starter): extract shared buffer-recording start logic"
```

---

## Task 4: yt-dlp channel poller helper

**Files:**
- Create: `src/concertpvr/ytdlp_channels.py`
- Create: `tests/fixtures/ytdlp_channel_streams.json`
- Create: `tests/test_ytdlp_channels.py`

- [ ] **Step 1: Test fixture**

`tests/fixtures/ytdlp_channel_streams.json`:

```json
{
  "_type": "playlist",
  "id": "UCNPRMusic",
  "title": "NPR Music — Streams",
  "uploader": "NPR Music",
  "thumbnail": "https://example.com/avatar.jpg",
  "entries": [
    {
      "id": "live123",
      "title": "Tiny Desk Live — Jason Isbell",
      "url": "https://www.youtube.com/watch?v=live123",
      "is_live": true,
      "channel": "NPR Music"
    },
    {
      "id": "old456",
      "title": "Past Tiny Desk concert",
      "url": "https://www.youtube.com/watch?v=old456",
      "is_live": false,
      "channel": "NPR Music"
    }
  ]
}
```

- [ ] **Step 2: Failing tests**

```python
# tests/test_ytdlp_channels.py
import json
from pathlib import Path

import pytest

from concertpvr.ytdlp_channels import (
    BroadcastInfo,
    ChannelInfo,
    fetch_channel_live_broadcasts,
    probe_channel,
)

FIXTURE = Path(__file__).parent / "fixtures" / "ytdlp_channel_streams.json"


@pytest.fixture
def fake_extract(monkeypatch):
    info = json.loads(FIXTURE.read_text())

    def _fake_init(self, params=None):  # noqa: ARG001
        pass

    def _fake_extract(self, url, download=False):  # noqa: ARG001
        return info

    def _fake_close(self):
        pass

    import yt_dlp
    monkeypatch.setattr(yt_dlp.YoutubeDL, "__init__", _fake_init)
    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", _fake_extract)
    monkeypatch.setattr(yt_dlp.YoutubeDL, "close", _fake_close)
    return info


@pytest.mark.asyncio
async def test_fetch_returns_only_live_broadcasts(fake_extract):
    broadcasts = await fetch_channel_live_broadcasts(
        "https://www.youtube.com/@nprmusic"
    )
    assert len(broadcasts) == 1
    assert isinstance(broadcasts[0], BroadcastInfo)
    assert broadcasts[0].youtube_id == "live123"
    assert broadcasts[0].is_live is True
    assert broadcasts[0].channel_name == "NPR Music"


@pytest.mark.asyncio
async def test_fetch_returns_empty_on_extract_error(monkeypatch):
    """yt-dlp errors must not bubble up to crash the poller."""
    import yt_dlp
    monkeypatch.setattr(yt_dlp.YoutubeDL, "__init__", lambda self, params=None: None)

    def _raise(self, url, download=False):  # noqa: ARG001
        raise yt_dlp.utils.DownloadError("channel unavailable")

    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", _raise)
    monkeypatch.setattr(yt_dlp.YoutubeDL, "close", lambda self: None)

    result = await fetch_channel_live_broadcasts("https://www.youtube.com/@bad")
    assert result == []


@pytest.mark.asyncio
async def test_fetch_returns_empty_when_no_entries(monkeypatch):
    import yt_dlp
    monkeypatch.setattr(yt_dlp.YoutubeDL, "__init__", lambda self, params=None: None)
    monkeypatch.setattr(
        yt_dlp.YoutubeDL,
        "extract_info",
        lambda self, url, download=False: {"_type": "playlist", "entries": []},
    )
    monkeypatch.setattr(yt_dlp.YoutubeDL, "close", lambda self: None)

    result = await fetch_channel_live_broadcasts("https://www.youtube.com/@empty")
    assert result == []


@pytest.mark.asyncio
async def test_probe_channel_returns_metadata(fake_extract):
    info = await probe_channel("https://www.youtube.com/@nprmusic")
    assert isinstance(info, ChannelInfo)
    assert info.channel_name == "NPR Music"
    assert info.canonical_url.endswith("/streams") or "youtube" in info.canonical_url
    assert info.avatar_url == "https://example.com/avatar.jpg"


@pytest.mark.asyncio
async def test_probe_channel_raises_on_error(monkeypatch):
    import yt_dlp
    from concertpvr.ytdlp_channels import ChannelProbeError

    monkeypatch.setattr(yt_dlp.YoutubeDL, "__init__", lambda self, params=None: None)

    def _raise(self, url, download=False):  # noqa: ARG001
        raise yt_dlp.utils.DownloadError("not a channel")

    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", _raise)
    monkeypatch.setattr(yt_dlp.YoutubeDL, "close", lambda self: None)

    with pytest.raises(ChannelProbeError):
        await probe_channel("https://www.youtube.com/@nope")
```

- [ ] **Step 3: Implement `src/concertpvr/ytdlp_channels.py`**

```python
"""yt-dlp helpers for channel polling.

probe_channel(url) — for the Add Watcher dialog: get channel name + avatar.
fetch_channel_live_broadcasts(url) — periodic poll for currently-live broadcasts.

Both run yt-dlp's library `extract_info` in a thread to avoid blocking the event loop.
fetch_channel_live_broadcasts swallows errors (returns []) — the poller must never crash.
probe_channel raises ChannelProbeError on failure (used at watcher-creation time).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import yt_dlp

logger = logging.getLogger(__name__)


class ChannelProbeError(Exception):
    """Raised when probe_channel cannot extract channel metadata."""


@dataclass(frozen=True)
class BroadcastInfo:
    youtube_id: str
    url: str
    title: str
    channel_name: str
    is_live: bool


@dataclass(frozen=True)
class ChannelInfo:
    channel_name: str
    canonical_url: str
    avatar_url: str | None


def _streams_url(channel_url: str) -> str:
    """Append '/streams' to a channel URL if it isn't already a tab URL."""
    base = channel_url.rstrip("/")
    if base.endswith("/streams") or base.endswith("/videos") or base.endswith("/live"):
        return base
    return f"{base}/streams"


def _extract_sync(url: str) -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


async def fetch_channel_live_broadcasts(channel_url: str) -> list[BroadcastInfo]:
    """Return broadcasts currently live on the given channel.

    Returns an empty list on any extraction error — never raises.
    """
    streams_url = _streams_url(channel_url)
    try:
        data = await asyncio.to_thread(_extract_sync, streams_url)
    except Exception as e:
        logger.warning("channel poll for %s failed: %s", channel_url, e)
        return []

    if not data:
        return []
    entries = data.get("entries") or []
    out: list[BroadcastInfo] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        if not e.get("is_live"):
            continue
        out.append(BroadcastInfo(
            youtube_id=e.get("id", ""),
            url=e.get("url") or e.get("webpage_url") or f"https://www.youtube.com/watch?v={e.get('id', '')}",
            title=e.get("title", ""),
            channel_name=e.get("channel") or data.get("uploader") or data.get("title", ""),
            is_live=True,
        ))
    return out


async def probe_channel(channel_url: str) -> ChannelInfo:
    """Get channel name + avatar for the Add Watcher dialog.

    Raises ChannelProbeError on extraction failure.
    """
    streams_url = _streams_url(channel_url)
    try:
        data = await asyncio.to_thread(_extract_sync, streams_url)
    except yt_dlp.utils.DownloadError as e:
        raise ChannelProbeError(str(e)) from e
    except Exception as e:
        raise ChannelProbeError(f"unexpected error: {e}") from e

    if not data:
        raise ChannelProbeError("no info returned")

    return ChannelInfo(
        channel_name=data.get("uploader") or data.get("title", "Unknown"),
        canonical_url=data.get("webpage_url", streams_url),
        avatar_url=data.get("thumbnail"),
    )
```

- [ ] **Step 4: Run + commit**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_ytdlp_channels.py -v
```
Expected: 5 pass.

```bash
git add src/concertpvr/ytdlp_channels.py tests/fixtures/ytdlp_channel_streams.json tests/test_ytdlp_channels.py
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(ytdlp_channels): probe + fetch live broadcasts from a channel"
```

---

## Task 5: Channel poller — top-level periodic job

**Files:**
- Create: `src/concertpvr/channel_poller.py`
- Create: `tests/test_channel_poller.py`

- [ ] **Step 1: Failing tests**

```python
# tests/test_channel_poller.py
import datetime as dt
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from concertpvr.buffer import BufferManager
from concertpvr.channel_poller import poll_all_channel_watchers
from concertpvr.db import Database
from concertpvr.models import Base, ChannelWatcher, Recording, Stream
from concertpvr.ws import Broadcaster
from concertpvr.ytdlp_channels import BroadcastInfo


@pytest.fixture
def setup(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'cp.db'}")
    Base.metadata.create_all(db.engine)
    pool = MagicMock()
    pool.start = AsyncMock()
    buf = BufferManager(tmp_path / "buf")
    bc = Broadcaster()
    return {"db": db, "pool": pool, "buf": buf, "bc": bc}


def _seed_watcher(db: Database, *, title_filter: str | None = None,
                  last_live_id: str | None = None) -> int:
    with db.session() as s:
        w = ChannelWatcher(
            channel_url="https://www.youtube.com/@nprmusic",
            channel_name="NPR Music",
            title_filter=title_filter,
            last_live_id=last_live_id,
        )
        s.add(w)
        s.flush()
        return w.id


@pytest.mark.asyncio
async def test_creates_stream_and_recording_when_new_live_found(setup):
    db = setup["db"]
    _seed_watcher(db)

    new_broadcast = BroadcastInfo(
        youtube_id="live123",
        url="https://www.youtube.com/watch?v=live123",
        title="Tiny Desk Live — Jason Isbell",
        channel_name="NPR Music",
        is_live=True,
    )

    with patch(
        "concertpvr.channel_poller.fetch_channel_live_broadcasts",
        new=AsyncMock(return_value=[new_broadcast]),
    ):
        await poll_all_channel_watchers(
            db=setup["db"], pool=setup["pool"], buf=setup["buf"],
            bc=setup["bc"], default_quality="best",
        )

    with db.session() as s:
        streams = s.query(Stream).all()
        assert len(streams) == 1
        assert streams[0].youtube_id == "live123"
        assert streams[0].kind == "live"

        recordings = s.query(Recording).all()
        assert len(recordings) == 1
        assert recordings[0].stream_id == streams[0].id

        watcher = s.query(ChannelWatcher).first()
        assert watcher.last_live_id == "live123"
        assert watcher.last_polled is not None

    setup["pool"].start.assert_awaited_once()


@pytest.mark.asyncio
async def test_skips_when_no_change_since_last_poll(setup):
    """If last_live_id matches the only live broadcast, no new recording."""
    db = setup["db"]
    _seed_watcher(db, last_live_id="live123")

    same_broadcast = BroadcastInfo(
        youtube_id="live123",
        url="https://www.youtube.com/watch?v=live123",
        title="Tiny Desk Live",
        channel_name="NPR Music",
        is_live=True,
    )

    with patch(
        "concertpvr.channel_poller.fetch_channel_live_broadcasts",
        new=AsyncMock(return_value=[same_broadcast]),
    ):
        await poll_all_channel_watchers(
            db=setup["db"], pool=setup["pool"], buf=setup["buf"],
            bc=setup["bc"], default_quality="best",
        )

    setup["pool"].start.assert_not_awaited()
    with db.session() as s:
        assert s.query(Recording).count() == 0


@pytest.mark.asyncio
async def test_title_filter_skips_non_matches(setup):
    db = setup["db"]
    _seed_watcher(db, title_filter="tiny desk")

    other = BroadcastInfo(
        youtube_id="live999",
        url="https://www.youtube.com/watch?v=live999",
        title="Behind the Scenes Q&A",
        channel_name="NPR Music",
        is_live=True,
    )

    with patch(
        "concertpvr.channel_poller.fetch_channel_live_broadcasts",
        new=AsyncMock(return_value=[other]),
    ):
        await poll_all_channel_watchers(
            db=setup["db"], pool=setup["pool"], buf=setup["buf"],
            bc=setup["bc"], default_quality="best",
        )

    setup["pool"].start.assert_not_awaited()
    with db.session() as s:
        assert s.query(Recording).count() == 0


@pytest.mark.asyncio
async def test_disabled_watcher_is_ignored(setup):
    db = setup["db"]
    with db.session() as s:
        w = ChannelWatcher(
            channel_url="https://www.youtube.com/@x",
            channel_name="X", enabled=False,
        )
        s.add(w)

    fetch_mock = AsyncMock(return_value=[])
    with patch("concertpvr.channel_poller.fetch_channel_live_broadcasts", new=fetch_mock):
        await poll_all_channel_watchers(
            db=setup["db"], pool=setup["pool"], buf=setup["buf"],
            bc=setup["bc"], default_quality="best",
        )
    fetch_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_existing_stream_is_reused(setup):
    """If a Stream with the broadcast's youtube_id already exists, no duplicate."""
    db = setup["db"]
    _seed_watcher(db)

    with db.session() as s:
        existing = Stream(
            kind="live", youtube_id="live123",
            url="https://www.youtube.com/watch?v=live123",
            title="Existing", channel_name="NPR Music",
        )
        s.add(existing)
        s.flush()
        existing_id = existing.id

    new_broadcast = BroadcastInfo(
        youtube_id="live123",
        url="https://www.youtube.com/watch?v=live123",
        title="Tiny Desk Live", channel_name="NPR Music", is_live=True,
    )

    with patch(
        "concertpvr.channel_poller.fetch_channel_live_broadcasts",
        new=AsyncMock(return_value=[new_broadcast]),
    ):
        await poll_all_channel_watchers(
            db=setup["db"], pool=setup["pool"], buf=setup["buf"],
            bc=setup["bc"], default_quality="best",
        )

    with db.session() as s:
        streams = s.query(Stream).all()
        assert len(streams) == 1
        assert streams[0].id == existing_id  # reused, not duplicated
```

- [ ] **Step 2: Implement `src/concertpvr/channel_poller.py`**

```python
"""Periodic channel poller — APScheduler job target.

Iterates enabled channel_watchers; for each, fetches live broadcasts via yt-dlp;
filters by last_live_id and title_filter; triggers a buffer recording for each match.
"""

from __future__ import annotations

import datetime as _dt
import logging
import re

from sqlalchemy import select

from concertpvr.buffer import BufferManager
from concertpvr.db import Database
from concertpvr.models import ChannelWatcher, Stream
from concertpvr.pool import RecorderPool
from concertpvr.recording_starter import start_buffer_recording
from concertpvr.ws import Broadcaster
from concertpvr.ytdlp_channels import BroadcastInfo, fetch_channel_live_broadcasts

logger = logging.getLogger(__name__)


def _matches_filter(title: str, pattern: str | None) -> bool:
    if pattern is None or pattern.strip() == "":
        return True
    try:
        return re.search(pattern, title, re.IGNORECASE) is not None
    except re.error:
        # Treat invalid regex as a plain substring match — never crash the poller.
        return pattern.lower() in title.lower()


def _ensure_stream(db: Database, broadcast: BroadcastInfo) -> int:
    """Return id of existing or freshly-created Stream for this broadcast."""
    with db.session() as s:
        existing = s.scalar(select(Stream).where(Stream.youtube_id == broadcast.youtube_id))
        if existing is not None:
            return existing.id
        stream = Stream(
            kind="live",
            youtube_id=broadcast.youtube_id,
            url=broadcast.url,
            title=broadcast.title,
            channel_name=broadcast.channel_name,
        )
        s.add(stream)
        s.flush()
        return stream.id


async def poll_all_channel_watchers(
    *,
    db: Database,
    pool: RecorderPool,
    buf: BufferManager,
    bc: Broadcaster,
    default_quality: str,
) -> None:
    """Run one polling cycle. Called every 60s by APScheduler."""
    with db.session() as s:
        enabled = list(s.scalars(select(ChannelWatcher).where(ChannelWatcher.enabled == True)))  # noqa: E712
        watcher_data = [
            (w.id, w.channel_url, w.title_filter, w.quality_cap, w.last_live_id)
            for w in enabled
        ]

    for w_id, channel_url, title_filter, quality_cap, last_live_id in watcher_data:
        try:
            broadcasts = await fetch_channel_live_broadcasts(channel_url)
        except Exception as e:
            logger.warning("watcher %s: fetch failed: %s", w_id, e)
            broadcasts = []

        # Find the first live broadcast that's both new AND title-matched.
        triggered_id: str | None = None
        for b in broadcasts:
            if b.youtube_id == last_live_id:
                continue
            if not _matches_filter(b.title, title_filter):
                continue
            try:
                stream_id = _ensure_stream(db, b)
                quality = quality_cap or default_quality
                await start_buffer_recording(
                    stream_id=stream_id,
                    url=b.url,
                    quality_format=quality,
                    db=db, pool=pool, buf=buf, bc=bc,
                )
                triggered_id = b.youtube_id
                break  # one recording per watcher per poll cycle
            except Exception as e:
                logger.warning("watcher %s: failed to start recording for %s: %s",
                               w_id, b.youtube_id, e)

        # Update last_polled and (if we triggered) last_live_id
        with db.session() as s:
            w = s.get(ChannelWatcher, w_id)
            if w is not None:
                w.last_polled = _dt.datetime.now(_dt.UTC)
                if triggered_id is not None:
                    w.last_live_id = triggered_id
```

- [ ] **Step 3: Run + commit**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_channel_poller.py -v
```
Expected: 5 pass.

```bash
git add src/concertpvr/channel_poller.py tests/test_channel_poller.py
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(channel_poller): periodic poll triggering auto-record on matched live"
```

---

## Task 6: Channel watchers API + scheduler wiring

**Files:**
- Create: `src/concertpvr/api/channel_watchers.py`
- Modify: `src/concertpvr/main.py` (register router; add 60s polling job)
- Create: `tests/test_channel_watchers_api.py`

- [ ] **Step 1: Failing tests**

```python
# tests/test_channel_watchers_api.py
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from concertpvr.main import create_app
from concertpvr.ytdlp_channels import ChannelInfo


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def fake_probe():
    info = ChannelInfo(
        channel_name="NPR Music",
        canonical_url="https://www.youtube.com/@nprmusic/streams",
        avatar_url="https://example.com/avatar.jpg",
    )

    async def _async_probe(_url):
        return info

    with patch("concertpvr.api.channel_watchers.probe_channel",
               side_effect=_async_probe) as m:
        yield m, info


def test_post_creates_watcher_with_probed_metadata(client, fake_probe):
    _, info = fake_probe
    r = client.post("/api/channel-watchers", json={
        "channel_url": "https://www.youtube.com/@nprmusic",
        "title_filter": "tiny desk",
        "retention_days": 14,
    })
    assert r.status_code == 201
    body = r.json()
    assert body["channel_name"] == "NPR Music"
    assert body["avatar_url"] == "https://example.com/avatar.jpg"
    assert body["title_filter"] == "tiny desk"
    assert body["retention_days"] == 14
    assert body["enabled"] is True


def test_post_rejects_when_probe_fails(client):
    from concertpvr.ytdlp_channels import ChannelProbeError

    async def _raise(_url):
        raise ChannelProbeError("not a channel")

    with patch("concertpvr.api.channel_watchers.probe_channel", side_effect=_raise):
        r = client.post("/api/channel-watchers",
                        json={"channel_url": "https://www.youtube.com/@bad"})
    assert r.status_code == 400


def test_post_rejects_duplicate_url(client, fake_probe):
    _, info = fake_probe
    body = {"channel_url": "https://www.youtube.com/@nprmusic"}
    assert client.post("/api/channel-watchers", json=body).status_code == 201
    assert client.post("/api/channel-watchers", json=body).status_code == 409


def test_get_lists_watchers(client, fake_probe):
    client.post("/api/channel-watchers",
                json={"channel_url": "https://www.youtube.com/@nprmusic"})
    r = client.get("/api/channel-watchers")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_patch_updates_filter_and_enabled(client, fake_probe):
    created = client.post("/api/channel-watchers",
                          json={"channel_url": "https://www.youtube.com/@nprmusic"}).json()
    r = client.patch(f"/api/channel-watchers/{created['id']}",
                     json={"title_filter": "session", "enabled": False})
    assert r.status_code == 200
    body = r.json()
    assert body["title_filter"] == "session"
    assert body["enabled"] is False


def test_delete_watcher(client, fake_probe):
    created = client.post("/api/channel-watchers",
                          json={"channel_url": "https://www.youtube.com/@nprmusic"}).json()
    r = client.delete(f"/api/channel-watchers/{created['id']}")
    assert r.status_code == 204
    r = client.get(f"/api/channel-watchers/{created['id']}")
    assert r.status_code == 404


def test_polling_job_is_registered(client):
    sched = client.app.state.scheduler
    job_ids = {j.id for j in sched.get_jobs()}
    assert "channel_poller" in job_ids
```

- [ ] **Step 2: Implement `src/concertpvr/api/channel_watchers.py`**

```python
"""Channel watchers CRUD."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from concertpvr.db import Database
from concertpvr.deps import get_db
from concertpvr.models import ChannelWatcher
from concertpvr.schemas import (
    ChannelWatcherCreate, ChannelWatcherPatch, ChannelWatcherRead,
)
from concertpvr.ytdlp_channels import ChannelProbeError, probe_channel

router = APIRouter()


@router.post(
    "/channel-watchers", response_model=ChannelWatcherRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_watcher(
    payload: ChannelWatcherCreate,
    db: Database = Depends(get_db),  # noqa: B008
) -> ChannelWatcher:
    try:
        info = await probe_channel(payload.channel_url)
    except ChannelProbeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    with db.session() as s:
        existing = s.scalar(
            select(ChannelWatcher).where(ChannelWatcher.channel_url == info.canonical_url)
        )
        if existing is not None:
            raise HTTPException(status_code=409, detail="watcher already exists")
        w = ChannelWatcher(
            channel_url=info.canonical_url,
            channel_name=info.channel_name,
            avatar_url=info.avatar_url,
            title_filter=payload.title_filter,
            quality_cap=payload.quality_cap,
            retention_days=payload.retention_days,
        )
        s.add(w)
        try:
            s.flush()
        except IntegrityError as e:
            raise HTTPException(status_code=409, detail="watcher already exists") from e
        s.refresh(w)
        s.expunge(w)
    return w


@router.get("/channel-watchers", response_model=list[ChannelWatcherRead])
def list_watchers(db: Database = Depends(get_db)) -> list[ChannelWatcher]:  # noqa: B008
    with db.session() as s:
        rows = list(s.scalars(select(ChannelWatcher).order_by(ChannelWatcher.added_at.desc())))
        for r in rows:
            s.expunge(r)
    return rows


@router.get("/channel-watchers/{watcher_id}", response_model=ChannelWatcherRead)
def get_watcher(watcher_id: int, db: Database = Depends(get_db)) -> ChannelWatcher:  # noqa: B008
    with db.session() as s:
        row = s.get(ChannelWatcher, watcher_id)
        if row is None:
            raise HTTPException(status_code=404, detail="watcher not found")
        s.expunge(row)
    return row


@router.patch("/channel-watchers/{watcher_id}", response_model=ChannelWatcherRead)
def patch_watcher(
    watcher_id: int,
    patch: ChannelWatcherPatch,
    db: Database = Depends(get_db),  # noqa: B008
) -> ChannelWatcher:
    updates = patch.model_dump(exclude_unset=True)
    with db.session() as s:
        w = s.get(ChannelWatcher, watcher_id)
        if w is None:
            raise HTTPException(status_code=404, detail="watcher not found")
        for k, v in updates.items():
            setattr(w, k, v)
        s.flush()
        s.refresh(w)
        s.expunge(w)
    return w


@router.delete("/channel-watchers/{watcher_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_watcher(watcher_id: int, db: Database = Depends(get_db)) -> Response:  # noqa: B008
    with db.session() as s:
        w = s.get(ChannelWatcher, watcher_id)
        if w is None:
            raise HTTPException(status_code=404, detail="watcher not found")
        s.delete(w)
    return Response(status_code=204)
```

- [ ] **Step 3: Wire scheduler job + router into `src/concertpvr/main.py`**

In `lifespan()`, AFTER the retention pruner registration block, add:

```python
    from concertpvr.channel_poller import poll_all_channel_watchers
    from concertpvr.models import Settings as _SettingsModel

    async def _channel_poll_job() -> None:
        with app.state.db.session() as s:
            settings_row = s.get(_SettingsModel, 1)
            quality = settings_row.default_quality if settings_row else "bestvideo*+bestaudio/best"
        await poll_all_channel_watchers(
            db=app.state.db,
            pool=app.state.pool,
            buf=app.state.buffer,
            bc=app.state.broadcaster,
            default_quality=quality,
        )

    app.state.scheduler.add_job(
        _channel_poll_job,
        "interval",
        seconds=60,
        id="channel_poller",
        replace_existing=True,
        jobstore="memory",
    )
```

In `create_app()`, after the existing routers:

```python
    from concertpvr.api.channel_watchers import router as channel_watchers_router
    app.include_router(channel_watchers_router, prefix="/api")
```

- [ ] **Step 4: Run + commit**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_channel_watchers_api.py -v
./.venv/Scripts/python.exe -m pytest -q
```
Expected: 7 new pass; full suite ~152.

```bash
git add src/concertpvr/api/channel_watchers.py src/concertpvr/main.py tests/test_channel_watchers_api.py
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(api): channel-watchers CRUD + 60s polling job"
```

---

## Task 7: Frontend api/query for channel watchers

**Files:**
- Modify: `frontend/src/lib/api.ts` (append)
- Modify: `frontend/src/lib/query.ts` (append)

- [ ] **Step 1: Append to `frontend/src/lib/api.ts`**

```typescript
// ── Channel Watchers ────────────────────────────────────────────────────────

export type ChannelWatcher = {
  id: number;
  channel_url: string;
  channel_name: string;
  avatar_url: string | null;
  title_filter: string | null;
  quality_cap: string | null;
  retention_days: number;
  enabled: boolean;
  last_polled: string | null;
  last_live_id: string | null;
  added_at: string;
};

export type ChannelWatcherCreate = {
  channel_url: string;
  title_filter?: string | null;
  quality_cap?: string | null;
  retention_days?: number;
};

export type ChannelWatcherPatch = {
  title_filter?: string | null;
  quality_cap?: string | null;
  retention_days?: number;
  enabled?: boolean;
};

export const watchersApi = {
  list: () => api.get<ChannelWatcher[]>("/api/channel-watchers"),
  create: (p: ChannelWatcherCreate) => api.post<ChannelWatcher>("/api/channel-watchers", p),
  patch: (id: number, p: ChannelWatcherPatch) =>
    api.patch<ChannelWatcher>(`/api/channel-watchers/${id}`, p),
  delete: (id: number) => api.delete<void>(`/api/channel-watchers/${id}`),
};
```

- [ ] **Step 2: Append to `frontend/src/lib/query.ts`**

```typescript
import {
  type ChannelWatcher,
  type ChannelWatcherCreate,
  type ChannelWatcherPatch,
  watchersApi,
} from "./api";

export const watchersKeys = {
  all: ["channel-watchers"] as const,
};

export function useChannelWatchers() {
  return useQuery<ChannelWatcher[]>({
    queryKey: watchersKeys.all,
    queryFn: () => watchersApi.list(),
    refetchInterval: 60_000,  // refresh "last_polled" every minute
  });
}

export function useCreateChannelWatcher() {
  const qc = useQueryClient();
  return useMutation<ChannelWatcher, Error, ChannelWatcherCreate>({
    mutationFn: (p) => watchersApi.create(p),
    onSuccess: () => qc.invalidateQueries({ queryKey: watchersKeys.all }),
  });
}

export function useUpdateChannelWatcher() {
  const qc = useQueryClient();
  return useMutation<ChannelWatcher, Error, { id: number; patch: ChannelWatcherPatch }>({
    mutationFn: ({ id, patch }) => watchersApi.patch(id, patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: watchersKeys.all }),
  });
}

export function useDeleteChannelWatcher() {
  const qc = useQueryClient();
  return useMutation<void, Error, number>({
    mutationFn: (id) => watchersApi.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: watchersKeys.all }),
  });
}
```

- [ ] **Step 3: Typecheck + commit**

```bash
cd frontend && npm run typecheck && cd ..
git add frontend/src/lib/api.ts frontend/src/lib/query.ts
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(frontend): channel-watchers api types + react-query hooks"
```

---

## Task 8: AddWatcherDialog component

**File:** Create `frontend/src/components/AddWatcherDialog.tsx`

- [ ] **Step 1: Implement**

```typescript
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogBody, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useCreateChannelWatcher } from "@/lib/query";
import type { ApiError } from "@/lib/api";

export function AddWatcherDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const [url, setUrl] = useState("");
  const [filter, setFilter] = useState("");
  const [retention, setRetention] = useState(7);
  const create = useCreateChannelWatcher();

  const submit = () => {
    if (!url.trim()) return;
    create.mutate(
      {
        channel_url: url.trim(),
        title_filter: filter.trim() || null,
        retention_days: retention,
      },
      {
        onSuccess: () => {
          setUrl(""); setFilter(""); setRetention(7);
          onOpenChange(false);
        },
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogHeader>Watch a channel</DialogHeader>
      <DialogBody className="space-y-3">
        <div>
          <label className="text-[11px] text-ink-dim block mb-1">Channel URL or handle</label>
          <Input
            autoFocus
            className="font-mono"
            placeholder="https://www.youtube.com/@nprmusic"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
        </div>
        <div>
          <label className="text-[11px] text-ink-dim block mb-1">
            Title filter (regex, optional)
          </label>
          <Input
            className="font-mono"
            placeholder="tiny desk|live"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          <p className="text-[10px] text-ink-faint mt-1">
            Only auto-record live broadcasts whose title matches. Leave empty to record all.
          </p>
        </div>
        <div>
          <label className="text-[11px] text-ink-dim block mb-1">Retention (days)</label>
          <Input
            type="number"
            min={1}
            max={365}
            className="font-mono"
            value={retention}
            onChange={(e) => setRetention(Number(e.target.value) || 7)}
          />
        </div>
        {create.isError && (
          <p className="text-xs text-red-400">
            {(create.error as ApiError).status === 409
              ? "This channel is already being watched."
              : (create.error as ApiError).status === 400
              ? "Couldn't fetch channel info — check the URL."
              : create.error.message}
          </p>
        )}
      </DialogBody>
      <DialogFooter>
        <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
        <Button variant="primary" onClick={submit} disabled={create.isPending}>
          {create.isPending ? "Probing channel…" : "Watch"}
        </Button>
      </DialogFooter>
    </Dialog>
  );
}
```

- [ ] **Step 2: Typecheck + commit**

```bash
cd frontend && npm run typecheck && cd ..
git add frontend/src/components/AddWatcherDialog.tsx
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(frontend): add-watcher dialog with URL + filter + retention"
```

---

## Task 9: Watchers page (full implementation)

**File:** Replace contents of `frontend/src/pages/Watchers.tsx`

- [ ] **Step 1: Implement**

```typescript
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  useChannelWatchers,
  useUpdateChannelWatcher,
  useDeleteChannelWatcher,
} from "@/lib/query";
import { AddWatcherDialog } from "@/components/AddWatcherDialog";
import type { ChannelWatcher } from "@/lib/api";
import { cn } from "@/lib/utils";

function fmtRelative(iso: string | null): string {
  if (!iso) return "never";
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 60_000) return "just now";
  if (ms < 3_600_000) return `${Math.round(ms / 60_000)}m ago`;
  if (ms < 86_400_000) return `${Math.round(ms / 3_600_000)}h ago`;
  return `${Math.round(ms / 86_400_000)}d ago`;
}

export default function WatchersPage() {
  const [dialogOpen, setDialogOpen] = useState(false);
  const { data, isLoading } = useChannelWatchers();
  const update = useUpdateChannelWatcher();
  const del = useDeleteChannelWatcher();

  const next_poll_in = (() => {
    const lp = (data ?? []).reduce<number | null>((acc, w) => {
      if (!w.last_polled) return acc;
      const t = new Date(w.last_polled).getTime();
      return acc === null || t > acc ? t : acc;
    }, null);
    if (lp === null) return null;
    const elapsed_s = Math.floor((Date.now() - lp) / 1000);
    return Math.max(0, 60 - elapsed_s);
  })();

  return (
    <div>
      <div className="flex items-center mb-4">
        <h2 className="text-lg font-semibold">Channel Watchers</h2>
        <span className="flex-1" />
        <span className="text-xs text-ink-dim mr-3">
          Polled every 60s
          {next_poll_in !== null && (
            <span className="text-amber font-mono ml-1">· next in {next_poll_in}s</span>
          )}
        </span>
        <Button variant="primary" onClick={() => setDialogOpen(true)}>
          ＋ Watch a channel
        </Button>
      </div>

      <AddWatcherDialog open={dialogOpen} onOpenChange={setDialogOpen} />

      {isLoading && <p className="text-ink-dim text-xs">Loading…</p>}
      {data && data.length === 0 && (
        <Card className="text-center py-8 text-ink-dim text-xs">
          No watchers yet. Click &ldquo;Watch a channel&rdquo; to add one.
        </Card>
      )}
      <div className="space-y-2">
        {(data ?? []).map((w) => (
          <WatcherRow
            key={w.id}
            watcher={w}
            onToggle={(enabled) => update.mutate({ id: w.id, patch: { enabled } })}
            onDelete={() => {
              if (confirm(`Stop watching "${w.channel_name}"?`)) del.mutate(w.id);
            }}
          />
        ))}
      </div>
    </div>
  );
}

function WatcherRow({
  watcher,
  onToggle,
  onDelete,
}: {
  watcher: ChannelWatcher;
  onToggle: (enabled: boolean) => void;
  onDelete: () => void;
}) {
  return (
    <Card className="flex items-center gap-4">
      <div className="w-12 h-12 rounded-full bg-surface-3 flex-shrink-0 overflow-hidden">
        {watcher.avatar_url && (
          <img src={watcher.avatar_url} alt="" className="w-full h-full object-cover" />
        )}
      </div>
      <div className="flex-1 min-w-0">
        <div className="font-medium truncate">{watcher.channel_name}</div>
        <div className="text-xs text-ink-dim font-mono truncate">
          {watcher.channel_url} · last polled {fmtRelative(watcher.last_polled)}
        </div>
      </div>
      <div className="flex items-center gap-2 flex-shrink-0">
        {watcher.title_filter && (
          <span className="text-[11px] font-mono text-amber bg-amber/10 px-2 py-0.5 rounded">
            ~ {watcher.title_filter}
          </span>
        )}
        <span className="text-[11px] font-mono text-ink-faint">
          {watcher.retention_days}d
        </span>
        {!watcher.enabled && <Badge color="neutral">paused</Badge>}
        <button
          onClick={() => onToggle(!watcher.enabled)}
          className={cn(
            "w-9 h-5 rounded-full relative transition-colors",
            watcher.enabled ? "bg-sage/30" : "bg-surface-3",
          )}
          aria-label={watcher.enabled ? "Disable" : "Enable"}
        >
          <span
            className={cn(
              "absolute top-0.5 w-4 h-4 rounded-full transition-all",
              watcher.enabled ? "left-[18px] bg-sage" : "left-0.5 bg-ink-dim",
            )}
          />
        </button>
        <Button variant="ghost" onClick={onDelete}>✕</Button>
      </div>
    </Card>
  );
}
```

- [ ] **Step 2: Typecheck + build + commit**

```bash
cd frontend
npm run typecheck
npm run build
cd ..
git add frontend/src/pages/Watchers.tsx
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(frontend): channel watchers page with toggle + delete + add dialog"
```

---

## Task 10: Phase 5 wrap-up

- [ ] **Step 1: Backend sweep**

```bash
./.venv/Scripts/python.exe -m ruff check src/ tests/
./.venv/Scripts/python.exe -m ruff format --check src/ tests/
./.venv/Scripts/python.exe -m mypy src/
./.venv/Scripts/python.exe -m pytest -q
```

If anything fails, fix INLINE per the standard guardrails — don't weaken `Field(...)` defaults, don't change tests to assert different behavior, don't relax mypy strictness. Allowed fixes: `ruff format`, `# noqa: B008`, `# type: ignore[import-untyped]`.

- [ ] **Step 2: Frontend sweep**

```bash
cd frontend && npm run typecheck && npm run build && cd ..
```

- [ ] **Step 3: Commit + tag**

```bash
git status
git add -A
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "chore: phase 5 wrap-up — lint/type/test sweep" || echo "(nothing to commit)"

git tag -a phase-5-channel-watchers -m "Phase 5 complete: channel watchers + auto-record on go-live"
git log --oneline phase-4b-timeline-ui..HEAD | head -25
```

---

## Phase 5 done

At tag `phase-5-channel-watchers`:
- New `channel_watchers` table + migration 0005
- yt-dlp helpers for probing channels and fetching live broadcasts
- Periodic 60-second poller that triggers buffer recordings on new + matching live broadcasts
- `recording_starter` shared module used by both manual buffer toggles and channel auto-triggers
- `/api/channel-watchers` CRUD
- Watchers page with avatar + title-filter pill + enable toggle + delete
- "Polled every 60s · next in Xs" header

**Tests added:** ~18 (1 schema, 1 recording starter, 5 ytdlp_channels, 5 channel poller, 7 watchers API).

**Next: Phase 6 — Polish & Ship.** Settings page improvements, password auth, full error UI, manual smoke-test docs, Docker compose verification.
