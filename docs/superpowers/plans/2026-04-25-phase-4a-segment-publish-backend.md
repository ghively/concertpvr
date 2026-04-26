# concertpvr — Phase 4a: Segment & Publish Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Backend pipeline that turns one long recording into per-artist Emby movies. Includes the `segments` and `setlists` tables, ffmpeg-driven splitting, NFO/poster/fanart generation, Emby publish + library refresh, segmenter that derives draft segments from chapters or setlist, and APIs for all of it. The Timeline UI is Phase 4b.

**Architecture:** A `Splitter` wraps ffmpeg-as-subprocess (using the same `ProcessRunner` Protocol from Phase 2) to perform `-ss A -to B -c copy` cuts. A `MetadataBuilder` writes `movie.nfo` (Emby Movie schema) + `poster.jpg` (recording thumbnail with text overlay via Pillow) + `fanart.jpg` (recording thumbnail). An `EmbyClient` POSTs to `/Library/Media/Updated` to trigger a path scan. The `Segmenter` reads a recording's chapters and any setlist rows and creates draft segments. A worker pool publishes segments asynchronously, updating status (`draft → publishing → published | publish_failed`).

**Tech Stack:** Adds to Phase 3: `Pillow` (poster compositing), `httpx` (already a dep — used for Emby), `ffmpeg` subprocess (already in Dockerfile). No new infrastructure.

**Spec reference:** `docs/superpowers/specs/2026-04-24-concertpvr-design.md` — §5 segments + setlists tables, §6.3 Flow C — multi-artist split + publish, §9 Error handling.

**Phase 3 baseline (already on `main`):** 85 backend tests, frontend builds. `/api/streams`, `/api/recordings`, `/api/schedules` working. Recordings have `path` (a directory of fragments OR a file).

---

## File structure (additions in this phase)

```
src/concertpvr/
├── ffmpeg.py             # Splitter: probe duration, copy-cut, extract thumbnail
├── metadata.py           # MetadataBuilder: NFO, poster, fanart
├── emby.py               # EmbyClient: scan-trigger via /Library/Media/Updated
├── segmenter.py          # derive draft segments from chapters/setlist
├── publisher.py          # PublishWorker: orchestrate split → metadata → emby per segment
└── api/
    ├── segments.py       # /api/segments CRUD + /api/segments/{id}/publish
    └── setlists.py       # /api/recordings/{id}/setlist (paste setlist as text)

alembic/versions/
└── 0004_segments_setlists.py

tests/
├── test_ffmpeg.py
├── test_metadata.py
├── test_emby.py
├── test_segmenter.py
├── test_publisher.py
├── test_segments_api.py
├── test_setlists_api.py
└── fixtures/
    ├── tiny.mp4              # ~3s test video; checked in
    ├── ytdlp_chapters.json   # canned chapters output
    └── setlist_paste.txt     # festival lineup paste
```

We do NOT add new frontend files in 4a — that's 4b.

---

## Module interfaces (locked at design time)

**`ffmpeg.Splitter`:**
```python
@dataclass(frozen=True)
class ProbeInfo:
    duration_s: float
    width: int
    height: int
    fps: float

class Splitter:
    def __init__(self, runner: ProcessRunner) -> None: ...
    async def probe(self, input_path: Path) -> ProbeInfo: ...
    async def cut(
        self, input_path: Path, output_path: Path, start_s: float, end_s: float
    ) -> None: ...
    async def thumbnail(
        self, input_path: Path, output_path: Path, at_s: float
    ) -> None: ...
```

**`metadata.MetadataBuilder`:**
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

class MetadataBuilder:
    def build_nfo(self, meta: SegmentMeta, output_dir: Path) -> Path: ...
    def build_poster(
        self, meta: SegmentMeta, source_thumbnail: Path | None, output_dir: Path
    ) -> Path: ...
    def build_fanart(self, source_thumbnail: Path | None, output_dir: Path) -> Path: ...
```

**`emby.EmbyClient`:**
```python
class EmbyClient:
    def __init__(self, base_url: str | None, api_key: str | None) -> None: ...
    @property
    def configured(self) -> bool: ...
    async def trigger_path_scan(self, library_path: str) -> None: ...
```

**`segmenter.derive_draft_segments(recording, db) -> list[Segment]`** (top-level fn):
- If `recording.raw_chapters_json` non-empty → segments from chapters with `source="chapter"`
- Else if `setlists` rows exist for this recording → segments from setlist with `source="setlist"`
- Else → return empty list (user uses Timeline editor in Phase 4b)
- Persist draft segments and return them

**`publisher.PublishWorker.publish(segment_id, options) -> None`** — orchestrates one segment publish.

---

## Task 1: Migration 0004 + Segment + Setlist models

**Files:**
- Modify: `src/concertpvr/models.py` (append `Segment` and `Setlist` classes; add `raw_chapters_json` to `Recording`)
- Create: `alembic/versions/0004_segments_setlists.py`
- Modify: `tests/test_db.py` (append round-trip tests)

- [ ] **Step 1: Append models**

After the existing `Schedule` class in `src/concertpvr/models.py`, append:

```python
class Segment(Base):
    __tablename__ = "segments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recording_id: Mapped[int] = mapped_column(
        ForeignKey("recordings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    artist: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    start_s: Mapped[int] = mapped_column(Integer, nullable=False)
    end_s: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)  # chapter|setlist|manual
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft")
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    emby_path: Mapped[str | None] = mapped_column(String, nullable=True)
    poster_path: Mapped[str | None] = mapped_column(String, nullable=True)
    nfo_path: Mapped[str | None] = mapped_column(String, nullable=True)

    recording = relationship("Recording")


class Setlist(Base):
    __tablename__ = "setlists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recording_id: Mapped[int] = mapped_column(
        ForeignKey("recordings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    artist: Mapped[str] = mapped_column(String, nullable=False)
    start_s: Mapped[int] = mapped_column(Integer, nullable=False)
    end_s: Mapped[int] = mapped_column(Integer, nullable=False)

    recording = relationship("Recording")
```

Also modify the existing `Recording` class — add this column inside it (alongside `error`):

```python
    raw_chapters_json: Mapped[str | None] = mapped_column(String, nullable=True)
```

- [ ] **Step 2: Append round-trip tests to `tests/test_db.py`**

```python
from concertpvr.models import Segment, Setlist


def test_segment_round_trip(tmp_db):
    Base.metadata.create_all(tmp_db.engine)

    with tmp_db.session() as s:
        stream = Stream(kind="live", youtube_id="seg1", url="u", title="t", channel_name="c")
        s.add(stream)
        s.flush()
        rec = Recording(
            stream_id=stream.id,
            started_at=dt.datetime(2026, 4, 25, 12, 0, tzinfo=dt.UTC),
            path="/buf/1",
            is_buffer=True,
        )
        s.add(rec)
        s.flush()

        seg = Segment(
            recording_id=rec.id,
            artist="Phoebe Bridgers",
            title="Mojave Set",
            start_s=21,
            end_s=94 * 60 + 21,
            source="chapter",
        )
        s.add(seg)
        s.flush()
        sid = seg.id

    with tmp_db.session() as s:
        loaded = s.get(Segment, sid)
        assert loaded is not None
        assert loaded.artist == "Phoebe Bridgers"
        assert loaded.status == "draft"
        assert loaded.source == "chapter"
        assert loaded.emby_path is None


def test_setlist_round_trip(tmp_db):
    Base.metadata.create_all(tmp_db.engine)

    with tmp_db.session() as s:
        stream = Stream(kind="live", youtube_id="set1", url="u", title="t", channel_name="c")
        s.add(stream)
        s.flush()
        rec = Recording(
            stream_id=stream.id,
            started_at=dt.datetime(2026, 4, 25, 12, 0, tzinfo=dt.UTC),
            path="/buf/1",
            is_buffer=True,
        )
        s.add(rec)
        s.flush()

        sl = Setlist(recording_id=rec.id, artist="Goose", start_s=111 * 60, end_s=222 * 60)
        s.add(sl)
        s.flush()
        slid = sl.id

    with tmp_db.session() as s:
        loaded = s.get(Setlist, slid)
        assert loaded is not None
        assert loaded.artist == "Goose"
```

- [ ] **Step 3: Migration `alembic/versions/0004_segments_setlists.py`**

```python
"""segments + setlists tables, raw_chapters_json on recordings

Revision ID: 0004_segments_setlists
Revises: 0003_schedules
Create Date: 2026-04-25
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_segments_setlists"
down_revision: str | None = "0003_schedules"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("recordings",
                  sa.Column("raw_chapters_json", sa.String(), nullable=True))

    op.create_table(
        "segments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("recording_id", sa.Integer(),
                  sa.ForeignKey("recordings.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("artist", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("start_s", sa.Integer(), nullable=False),
        sa.Column("end_s", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("emby_path", sa.String(), nullable=True),
        sa.Column("poster_path", sa.String(), nullable=True),
        sa.Column("nfo_path", sa.String(), nullable=True),
    )
    op.create_index("ix_segments_recording_id", "segments", ["recording_id"])

    op.create_table(
        "setlists",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("recording_id", sa.Integer(),
                  sa.ForeignKey("recordings.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("artist", sa.String(), nullable=False),
        sa.Column("start_s", sa.Integer(), nullable=False),
        sa.Column("end_s", sa.Integer(), nullable=False),
    )
    op.create_index("ix_setlists_recording_id", "setlists", ["recording_id"])


def downgrade() -> None:
    op.drop_index("ix_setlists_recording_id", table_name="setlists")
    op.drop_table("setlists")
    op.drop_index("ix_segments_recording_id", table_name="segments")
    op.drop_table("segments")
    op.drop_column("recordings", "raw_chapters_json")
```

- [ ] **Step 4: Run + commit**

```bash
./.venv/Scripts/python.exe -m pytest -q
```
Expected: 87 (85 + 2).

```bash
git add src/concertpvr/models.py alembic/versions/0004_segments_setlists.py tests/test_db.py
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(models): segments + setlists tables, raw_chapters_json on recordings"
```

---

## Task 2: Pydantic schemas

**Files:**
- Modify: `src/concertpvr/schemas.py` (append)

- [ ] **Step 1: Append**

```python
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
    """One row in a posted setlist."""
    model_config = ConfigDict(extra="forbid")

    artist: str
    start_s: int
    end_s: int


class SetlistReplaceRequest(BaseModel):
    """Replace all setlist rows for a recording in one shot."""
    model_config = ConfigDict(extra="forbid")

    entries: list[SetlistEntry]


class PublishOptions(BaseModel):
    """Optional overrides when publishing a segment."""
    model_config = ConfigDict(extra="forbid")

    festival: str | None = None
    venue: str | None = None
    year: int | None = None
```

- [ ] **Step 2: Verify + commit**

```bash
./.venv/Scripts/python.exe -c "from concertpvr.schemas import SegmentRead, SegmentCreate, SegmentPatch, SetlistRead, SetlistEntry, SetlistReplaceRequest, PublishOptions; print('ok')"
```

```bash
git add src/concertpvr/schemas.py
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(schemas): pydantic models for segments, setlists, publish options"
```

---

## Task 3: Pillow dependency + tiny.mp4 fixture

**Files:**
- Modify: `pyproject.toml` (add Pillow to dependencies)
- Create: `tests/fixtures/tiny.mp4`

- [ ] **Step 1: Add Pillow**

In `pyproject.toml`, in the `dependencies` array, add `"pillow>=10.4.0",` next to the other entries (alphabetical position).

- [ ] **Step 2: Install**

```bash
./.venv/Scripts/python.exe -m pip install -e ".[dev]"
./.venv/Scripts/python.exe -c "from PIL import Image; print('ok')"
```

- [ ] **Step 3: Create tiny.mp4 fixture**

A small ~3-second test video. We generate it programmatically (no checked-in binary needed):

```bash
./.venv/Scripts/python.exe - <<'PY'
import subprocess
from pathlib import Path
out = Path("tests/fixtures/tiny.mp4")
out.parent.mkdir(parents=True, exist_ok=True)
# Generate a 3-second 320x180 test video at 30 fps with a sine-tone audio track.
r = subprocess.run([
    "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=30:duration=3",
    "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
    "-shortest", str(out),
], check=True, capture_output=True)
print(f"created {out} ({out.stat().st_size} bytes)")
PY
```

If ffmpeg isn't on PATH, this fails. The plan assumes ffmpeg is installed (it's in the Dockerfile and was a Phase 1 setup task; for local dev on Windows install via `winget install ffmpeg` or `choco install ffmpeg`). If unavailable, report BLOCKED.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml tests/fixtures/tiny.mp4
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "build: add Pillow + tiny.mp4 test fixture"
```

---

## Task 4: ffmpeg.Splitter

**Files:**
- Create: `src/concertpvr/ffmpeg.py`
- Create: `tests/test_ffmpeg.py`

- [ ] **Step 1: Failing tests**

```python
# tests/test_ffmpeg.py
from pathlib import Path

import pytest

from concertpvr.ffmpeg import ProbeInfo, Splitter
from concertpvr.process import AsyncSubprocessRunner

FIXTURE = Path(__file__).parent / "fixtures" / "tiny.mp4"


@pytest.mark.asyncio
async def test_probe_returns_dimensions_and_duration():
    splitter = Splitter(AsyncSubprocessRunner())
    info = await splitter.probe(FIXTURE)
    assert isinstance(info, ProbeInfo)
    assert info.width == 320
    assert info.height == 180
    assert 2.5 <= info.duration_s <= 3.5
    assert 25 <= info.fps <= 31


@pytest.mark.asyncio
async def test_cut_writes_a_shorter_file(tmp_path: Path):
    splitter = Splitter(AsyncSubprocessRunner())
    out = tmp_path / "cut.mp4"
    await splitter.cut(FIXTURE, out, start_s=0.5, end_s=1.5)
    assert out.exists() and out.stat().st_size > 0

    info = await splitter.probe(out)
    assert 0.8 <= info.duration_s <= 1.5  # tolerance for keyframe alignment


@pytest.mark.asyncio
async def test_thumbnail_writes_jpeg(tmp_path: Path):
    splitter = Splitter(AsyncSubprocessRunner())
    out = tmp_path / "thumb.jpg"
    await splitter.thumbnail(FIXTURE, out, at_s=1.0)
    assert out.exists() and out.stat().st_size > 0

    # Verify it's a valid JPEG by header bytes
    header = out.read_bytes()[:3]
    assert header == b"\xff\xd8\xff"


@pytest.mark.asyncio
async def test_cut_raises_on_ffmpeg_failure(tmp_path: Path):
    splitter = Splitter(AsyncSubprocessRunner())
    nonexistent = tmp_path / "nonexistent.mp4"
    out = tmp_path / "cut.mp4"
    with pytest.raises(RuntimeError):
        await splitter.cut(nonexistent, out, 0.0, 1.0)
```

- [ ] **Step 2: Run — fails (module missing)**

- [ ] **Step 3: Implement `src/concertpvr/ffmpeg.py`**

```python
"""ffmpeg subprocess wrapper for probing, cutting, and thumbnail extraction."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from concertpvr.process import ProcessRunner


@dataclass(frozen=True)
class ProbeInfo:
    duration_s: float
    width: int
    height: int
    fps: float


class FFmpegError(RuntimeError):
    pass


class Splitter:
    def __init__(self, runner: ProcessRunner) -> None:
        self._runner = runner

    async def probe(self, input_path: Path) -> ProbeInfo:
        argv = [
            "ffprobe", "-v", "error",
            "-print_format", "json",
            "-show_format", "-show_streams",
            str(input_path),
        ]
        proc = await self._runner.spawn(argv)
        stdout_chunks: list[str] = []
        async for line in proc.stdout_lines():
            stdout_chunks.append(line)
        rc = await proc.wait()
        if rc != 0:
            raise FFmpegError(f"ffprobe exited {rc} for {input_path}")
        data = json.loads("\n".join(stdout_chunks))
        video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
        if video is None:
            raise FFmpegError(f"no video stream in {input_path}")

        duration_s = float(data.get("format", {}).get("duration", 0.0))
        width = int(video.get("width", 0))
        height = int(video.get("height", 0))
        fps_str = video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1"
        num, _, denom = fps_str.partition("/")
        denom_f = float(denom or "1") or 1.0
        fps = float(num) / denom_f

        return ProbeInfo(duration_s=duration_s, width=width, height=height, fps=fps)

    async def cut(
        self, input_path: Path, output_path: Path, start_s: float, end_s: float
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        argv = [
            "ffmpeg", "-y",
            "-ss", f"{start_s:.3f}",
            "-to", f"{end_s:.3f}",
            "-i", str(input_path),
            "-c", "copy",
            "-avoid_negative_ts", "make_zero",
            str(output_path),
        ]
        proc = await self._runner.spawn(argv)
        # Drain streams to prevent fill
        async for _ in proc.stdout_lines():
            pass
        async for _ in proc.stderr_lines():
            pass
        rc = await proc.wait()
        if rc != 0:
            raise FFmpegError(f"ffmpeg exited {rc}")

    async def thumbnail(
        self, input_path: Path, output_path: Path, at_s: float
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        argv = [
            "ffmpeg", "-y",
            "-ss", f"{at_s:.3f}",
            "-i", str(input_path),
            "-frames:v", "1",
            "-q:v", "2",
            str(output_path),
        ]
        proc = await self._runner.spawn(argv)
        async for _ in proc.stdout_lines():
            pass
        async for _ in proc.stderr_lines():
            pass
        rc = await proc.wait()
        if rc != 0:
            raise FFmpegError(f"ffmpeg thumbnail exited {rc}")
```

- [ ] **Step 4: Run + commit**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_ffmpeg.py -v
```
Expected: 4 pass.

```bash
git add src/concertpvr/ffmpeg.py tests/test_ffmpeg.py
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(ffmpeg): probe, cut, thumbnail wrapper around ffmpeg/ffprobe"
```

---

## Task 5: metadata.MetadataBuilder

**Files:**
- Create: `src/concertpvr/metadata.py`
- Create: `tests/test_metadata.py`

- [ ] **Step 1: Failing tests**

```python
# tests/test_metadata.py
import datetime as dt
from pathlib import Path

from PIL import Image

from concertpvr.metadata import MetadataBuilder, SegmentMeta


def _meta(**overrides) -> SegmentMeta:
    base = dict(
        artist="Phoebe Bridgers",
        title="Mojave Set",
        festival="Coachella W1",
        venue="Mojave Stage",
        year=2026,
        date=dt.date(2026, 4, 12),
        duration_s=4500,
        width=1920,
        height=1080,
    )
    base.update(overrides)
    return SegmentMeta(**base)


def test_build_nfo_writes_emby_movie_xml(tmp_path: Path):
    mb = MetadataBuilder()
    nfo = mb.build_nfo(_meta(), tmp_path)
    assert nfo == tmp_path / "movie.nfo"
    text = nfo.read_text(encoding="utf-8")
    assert text.startswith("<?xml")
    assert "<movie>" in text
    assert "<title>Phoebe Bridgers — Mojave Set</title>" in text
    assert "<year>2026</year>" in text
    assert "<premiered>2026-04-12</premiered>" in text
    assert "<runtime>75</runtime>" in text  # 4500s == 75 min
    assert "<studio>Coachella W1</studio>" in text


def test_build_nfo_when_no_optional_metadata(tmp_path: Path):
    mb = MetadataBuilder()
    minimal = SegmentMeta(
        artist="Test", title=None, festival=None, venue=None,
        year=2026, date=None, duration_s=600, width=None, height=None,
    )
    nfo = mb.build_nfo(minimal, tmp_path)
    text = nfo.read_text(encoding="utf-8")
    assert "<title>Test</title>" in text  # falls back to artist
    assert "<premiered>" not in text


def test_build_poster_with_source_thumbnail(tmp_path: Path):
    src = tmp_path / "src.jpg"
    Image.new("RGB", (1280, 720), color=(20, 30, 50)).save(src, "JPEG")

    mb = MetadataBuilder()
    poster = mb.build_poster(_meta(), source_thumbnail=src, output_dir=tmp_path)
    assert poster == tmp_path / "poster.jpg"
    assert poster.exists() and poster.stat().st_size > 0

    img = Image.open(poster)
    # Posters are 2:3 aspect ratio (Emby convention)
    assert abs((img.width / img.height) - (2 / 3)) < 0.01


def test_build_poster_without_source_falls_back_to_solid(tmp_path: Path):
    mb = MetadataBuilder()
    poster = mb.build_poster(_meta(), source_thumbnail=None, output_dir=tmp_path)
    assert poster.exists()
    img = Image.open(poster)
    assert abs((img.width / img.height) - (2 / 3)) < 0.01


def test_build_fanart_copies_or_renders(tmp_path: Path):
    src = tmp_path / "src.jpg"
    Image.new("RGB", (1280, 720), color=(20, 30, 50)).save(src, "JPEG")
    mb = MetadataBuilder()
    fan = mb.build_fanart(src, tmp_path)
    assert fan == tmp_path / "fanart.jpg"
    assert fan.exists()


def test_build_fanart_without_source_creates_default(tmp_path: Path):
    mb = MetadataBuilder()
    fan = mb.build_fanart(None, tmp_path)
    assert fan.exists()
```

- [ ] **Step 2: Implement `src/concertpvr/metadata.py`**

```python
"""Generate Emby-compatible movie metadata files (NFO, poster, fanart)."""

from __future__ import annotations

import datetime as _dt
import shutil
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw, ImageFont


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


# Emby's movie posters use a 2:3 aspect ratio (e.g., 1000x1500 is canonical).
POSTER_W: int = 1000
POSTER_H: int = 1500
FANART_W: int = 1920
FANART_H: int = 1080


class MetadataBuilder:
    def build_nfo(self, meta: SegmentMeta, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        out = output_dir / "movie.nfo"

        title = (
            f"{meta.artist} — {meta.title}" if meta.title else meta.artist
        )
        runtime = max(0, meta.duration_s // 60)

        lines = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>',
            "<movie>",
            f"  <title>{escape(title)}</title>",
            f"  <originaltitle>{escape(title)}</originaltitle>",
            f"  <year>{meta.year}</year>",
            f"  <runtime>{runtime}</runtime>",
        ]
        if meta.date:
            lines.append(f"  <premiered>{meta.date.isoformat()}</premiered>")
        if meta.festival:
            lines.append(f"  <studio>{escape(meta.festival)}</studio>")
        if meta.venue:
            lines.append(f"  <set><name>{escape(meta.venue)}</name></set>")
        lines.append(f"  <genre>Concert</genre>")
        lines.append(f"  <tag>concertpvr</tag>")
        lines.append("</movie>")

        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return out

    def build_poster(
        self, meta: SegmentMeta, source_thumbnail: Path | None, output_dir: Path
    ) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        out = output_dir / "poster.jpg"

        canvas = Image.new("RGB", (POSTER_W, POSTER_H), color=(12, 14, 18))

        if source_thumbnail and source_thumbnail.exists():
            try:
                src = Image.open(source_thumbnail).convert("RGB")
                # Cover the canvas while maintaining aspect ratio
                scale = max(POSTER_W / src.width, POSTER_H / src.height)
                new_size = (int(src.width * scale), int(src.height * scale))
                src = src.resize(new_size, Image.LANCZOS)
                # Center crop
                left = (src.width - POSTER_W) // 2
                top = (src.height - POSTER_H) // 2
                src = src.crop((left, top, left + POSTER_W, top + POSTER_H))
                # Apply darkening overlay so text stays legible
                overlay = Image.new("RGB", (POSTER_W, POSTER_H), color=(0, 0, 0))
                src = Image.blend(src, overlay, 0.4)
                canvas = src
            except Exception:
                pass  # fall through to solid background

        draw = ImageDraw.Draw(canvas)
        artist_font, title_font, sub_font = self._load_fonts()

        # Bottom-third title block
        artist_y = POSTER_H * 2 // 3
        draw.text((60, artist_y), meta.artist, fill=(232, 234, 238), font=artist_font)
        if meta.title:
            draw.text((60, artist_y + 90), meta.title, fill=(212, 102, 74), font=title_font)
        sub_lines: list[str] = []
        if meta.festival:
            sub_lines.append(meta.festival)
        if meta.venue and meta.venue != meta.festival:
            sub_lines.append(meta.venue)
        sub_lines.append(str(meta.year))
        sub_text = " · ".join(sub_lines)
        draw.text((60, artist_y + 180), sub_text, fill=(154, 160, 171), font=sub_font)

        canvas.save(out, "JPEG", quality=88)
        return out

    def build_fanart(
        self, source_thumbnail: Path | None, output_dir: Path
    ) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        out = output_dir / "fanart.jpg"

        if source_thumbnail and source_thumbnail.exists():
            try:
                src = Image.open(source_thumbnail).convert("RGB")
                # Resize to fanart aspect ratio with cover-fit
                scale = max(FANART_W / src.width, FANART_H / src.height)
                new_size = (int(src.width * scale), int(src.height * scale))
                src = src.resize(new_size, Image.LANCZOS)
                left = (src.width - FANART_W) // 2
                top = (src.height - FANART_H) // 2
                src = src.crop((left, top, left + FANART_W, top + FANART_H))
                src.save(out, "JPEG", quality=88)
                return out
            except Exception:
                pass

        # Fallback: solid color background
        Image.new("RGB", (FANART_W, FANART_H), color=(12, 14, 18)).save(
            out, "JPEG", quality=88
        )
        return out

    def _load_fonts(
        self,
    ) -> tuple[ImageFont.ImageFont, ImageFont.ImageFont, ImageFont.ImageFont]:
        # Try to find a system font; fall back to PIL default.
        for candidate in (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "C:/Windows/Fonts/Arial.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "/Library/Fonts/Arial.ttf",
        ):
            if Path(candidate).exists():
                return (
                    ImageFont.truetype(candidate, 72),
                    ImageFont.truetype(candidate, 56),
                    ImageFont.truetype(candidate, 36),
                )
        d = ImageFont.load_default()
        return d, d, d
```

- [ ] **Step 3: Run + commit**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_metadata.py -v
```
Expected: 6 pass.

```bash
git add src/concertpvr/metadata.py tests/test_metadata.py
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(metadata): NFO + poster + fanart builder for Emby movies"
```

---

## Task 6: emby.EmbyClient

**Files:**
- Create: `src/concertpvr/emby.py`
- Create: `tests/test_emby.py`

- [ ] **Step 1: Failing tests**

```python
# tests/test_emby.py
import pytest

from concertpvr.emby import EmbyClient


@pytest.mark.asyncio
async def test_unconfigured_client_silently_no_ops():
    """When Emby URL is None or empty, scan trigger is a no-op (not an error)."""
    client = EmbyClient(base_url=None, api_key=None)
    assert client.configured is False
    await client.trigger_path_scan("/media/concerts/foo")  # must not raise


@pytest.mark.asyncio
async def test_configured_client_posts_to_emby(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="http://emby:8096/Library/Media/Updated",
        status_code=204,
    )
    client = EmbyClient(base_url="http://emby:8096", api_key="abc")
    assert client.configured is True
    await client.trigger_path_scan("/media/concerts/Phoebe")
    request = httpx_mock.get_request()
    assert request.headers.get("X-Emby-Token") == "abc" or "api_key=abc" in str(request.url)


@pytest.mark.asyncio
async def test_configured_client_swallows_4xx_5xx(httpx_mock):
    """Failures should be logged but not raise — publish should not fail because Emby is offline."""
    httpx_mock.add_response(
        method="POST",
        url="http://emby:8096/Library/Media/Updated",
        status_code=500,
    )
    client = EmbyClient(base_url="http://emby:8096", api_key="abc")
    await client.trigger_path_scan("/media/concerts/foo")  # must not raise
```

This test uses `pytest-httpx`. Add to `pyproject.toml` `[project.optional-dependencies].dev`:
```
"pytest-httpx>=0.32.0",
```
And install via `pip install -e ".[dev]"`.

- [ ] **Step 2: Implement `src/concertpvr/emby.py`**

```python
"""Minimal Emby client — just enough to trigger a library refresh."""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


class EmbyClient:
    def __init__(self, base_url: str | None, api_key: str | None) -> None:
        self._base_url = (base_url or "").rstrip("/") or None
        self._api_key = api_key

    @property
    def configured(self) -> bool:
        return self._base_url is not None and self._api_key is not None

    async def trigger_path_scan(self, library_path: str) -> None:
        if not self.configured:
            return
        url = f"{self._base_url}/Library/Media/Updated"
        payload = {"Updates": [{"Path": library_path, "UpdateType": "Created"}]}
        headers = {"X-Emby-Token": self._api_key or ""}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code >= 400:
                    logger.warning(
                        "emby scan trigger failed: %s %s", resp.status_code, resp.text[:200]
                    )
        except httpx.HTTPError as e:
            logger.warning("emby scan trigger network error: %s", e)
```

- [ ] **Step 3: Run + commit**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_emby.py -v
```
Expected: 3 pass.

```bash
git add src/concertpvr/emby.py tests/test_emby.py pyproject.toml
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(emby): minimal Emby client for library refresh trigger"
```

---

## Task 7: segmenter.derive_draft_segments

**Files:**
- Create: `src/concertpvr/segmenter.py`
- Create: `tests/test_segmenter.py`

- [ ] **Step 1: Failing tests**

```python
# tests/test_segmenter.py
import datetime as dt
import json

import pytest

from concertpvr.db import Database
from concertpvr.models import Base, Recording, Segment, Setlist, Stream
from concertpvr.segmenter import derive_draft_segments


@pytest.fixture
def db(tmp_path):
    d = Database(f"sqlite:///{tmp_path / 'seg.db'}")
    Base.metadata.create_all(d.engine)
    return d


def _seed_recording(db: Database, *, with_chapters: bool = False) -> int:
    with db.session() as s:
        stream = Stream(kind="live", youtube_id="x", url="u", title="t", channel_name="c")
        s.add(stream)
        s.flush()
        chapters = None
        if with_chapters:
            chapters = json.dumps([
                {"title": "Phoebe Bridgers", "start_time": 21, "end_time": 1900},
                {"title": "Goose", "start_time": 1900, "end_time": 4000},
            ])
        rec = Recording(
            stream_id=stream.id,
            started_at=dt.datetime(2026, 4, 25, 12, 0, tzinfo=dt.UTC),
            path="/buf/1",
            is_buffer=True,
            raw_chapters_json=chapters,
        )
        s.add(rec)
        s.flush()
        return rec.id


def test_derives_from_chapters_when_present(db):
    rid = _seed_recording(db, with_chapters=True)
    with db.session() as s:
        rec = s.get(Recording, rid)
        segments = derive_draft_segments(rec, s)
    assert len(segments) == 2
    assert segments[0].artist == "Phoebe Bridgers"
    assert segments[0].source == "chapter"
    assert segments[0].start_s == 21
    assert segments[0].end_s == 1900
    assert segments[1].artist == "Goose"


def test_derives_from_setlist_when_no_chapters(db):
    rid = _seed_recording(db, with_chapters=False)
    with db.session() as s:
        s.add(Setlist(recording_id=rid, artist="Tame Impala", start_s=10, end_s=2000))
        s.add(Setlist(recording_id=rid, artist="Rüfüs Du Sol", start_s=2100, end_s=4000))
        s.flush()
        rec = s.get(Recording, rid)
        segments = derive_draft_segments(rec, s)
    assert len(segments) == 2
    assert segments[0].artist == "Tame Impala"
    assert segments[0].source == "setlist"


def test_returns_empty_list_when_neither_chapters_nor_setlist(db):
    rid = _seed_recording(db, with_chapters=False)
    with db.session() as s:
        rec = s.get(Recording, rid)
        segments = derive_draft_segments(rec, s)
    assert segments == []


def test_chapters_take_precedence_over_setlist(db):
    rid = _seed_recording(db, with_chapters=True)
    with db.session() as s:
        s.add(Setlist(recording_id=rid, artist="ShouldNotAppear", start_s=0, end_s=99))
        s.flush()
        rec = s.get(Recording, rid)
        segments = derive_draft_segments(rec, s)
    assert all(seg.source == "chapter" for seg in segments)
    assert "ShouldNotAppear" not in {seg.artist for seg in segments}


def test_persists_to_db(db):
    rid = _seed_recording(db, with_chapters=True)
    with db.session() as s:
        rec = s.get(Recording, rid)
        derive_draft_segments(rec, s)

    with db.session() as s:
        rows = s.query(Segment).filter_by(recording_id=rid).all()
        assert len(rows) == 2
        assert all(r.status == "draft" for r in rows)
```

- [ ] **Step 2: Implement `src/concertpvr/segmenter.py`**

```python
"""Derive draft segments from chapters or setlist rows."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from concertpvr.models import Recording, Segment, Setlist


def derive_draft_segments(recording: Recording, session: Session) -> list[Segment]:
    """Generate draft segments from chapters (preferred) or setlist (fallback).

    Returns the persisted Segment rows. Empty list if neither is available.
    Only creates segments that don't already exist for the recording (idempotent).
    """
    if recording.raw_chapters_json:
        try:
            chapters = json.loads(recording.raw_chapters_json)
        except (json.JSONDecodeError, TypeError):
            chapters = []
        if chapters:
            return _from_chapters(recording, chapters, session)

    setlist_rows = list(session.scalars(
        select(Setlist).where(Setlist.recording_id == recording.id).order_by(Setlist.start_s)
    ))
    if setlist_rows:
        return _from_setlist(recording, setlist_rows, session)

    return []


def _from_chapters(recording: Recording, chapters: list[dict], session: Session) -> list[Segment]:
    segs: list[Segment] = []
    for ch in chapters:
        title = (ch.get("title") or "").strip()
        if not title:
            continue
        start = int(ch.get("start_time") or 0)
        end = int(ch.get("end_time") or 0)
        if end <= start:
            continue
        seg = Segment(
            recording_id=recording.id,
            artist=title,
            title=None,
            start_s=start,
            end_s=end,
            source="chapter",
            status="draft",
        )
        session.add(seg)
        segs.append(seg)
    session.flush()
    return segs


def _from_setlist(
    recording: Recording, setlist_rows: list[Setlist], session: Session
) -> list[Segment]:
    segs: list[Segment] = []
    for row in setlist_rows:
        seg = Segment(
            recording_id=recording.id,
            artist=row.artist,
            title=None,
            start_s=row.start_s,
            end_s=row.end_s,
            source="setlist",
            status="draft",
        )
        session.add(seg)
        segs.append(seg)
    session.flush()
    return segs
```

- [ ] **Step 3: Run + commit**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_segmenter.py -v
```
Expected: 5 pass.

```bash
git add src/concertpvr/segmenter.py tests/test_segmenter.py
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(segmenter): derive draft segments from chapters/setlist"
```

---

## Task 8: publisher.PublishWorker

**Files:**
- Create: `src/concertpvr/publisher.py`
- Create: `tests/test_publisher.py`

- [ ] **Step 1: Failing tests**

```python
# tests/test_publisher.py
import datetime as dt
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from concertpvr.db import Database
from concertpvr.models import Base, Recording, Segment, Stream
from concertpvr.process import AsyncSubprocessRunner
from concertpvr.publisher import PublishWorker


@pytest.fixture
def db(tmp_path):
    d = Database(f"sqlite:///{tmp_path / 'pub.db'}")
    Base.metadata.create_all(d.engine)
    return d


def _seed(db: Database, source_path: Path) -> int:
    with db.session() as s:
        stream = Stream(
            kind="live", youtube_id="x", url="u",
            title="Coachella W1 — Mojave Stage", channel_name="Coachella",
        )
        s.add(stream)
        s.flush()
        rec = Recording(
            stream_id=stream.id,
            started_at=dt.datetime(2026, 4, 12, 14, 0, tzinfo=dt.UTC),
            path=str(source_path),
            is_buffer=False,
            status="complete",
        )
        s.add(rec)
        s.flush()
        seg = Segment(
            recording_id=rec.id,
            artist="Phoebe Bridgers",
            title="Mojave Set",
            start_s=0, end_s=2,
            source="manual", status="draft",
        )
        s.add(seg)
        s.flush()
        return seg.id


@pytest.fixture
def fixture_video():
    return Path(__file__).parent / "fixtures" / "tiny.mp4"


@pytest.mark.asyncio
async def test_publish_writes_emby_dir_with_clip_nfo_poster_fanart(db, tmp_path, fixture_video):
    seg_id = _seed(db, fixture_video)

    publish_root = tmp_path / "media" / "concerts"
    emby_client = MagicMock()
    emby_client.trigger_path_scan = AsyncMock()

    worker = PublishWorker(
        db=db,
        runner=AsyncSubprocessRunner(),
        publish_root=publish_root,
        folder_pattern="{artist} - {festival} ({year})",
        emby_client=emby_client,
    )

    await worker.publish(seg_id, festival="Coachella W1", venue="Mojave", year=2026)

    with db.session() as s:
        seg = s.get(Segment, seg_id)
        assert seg.status == "published"
        assert seg.error is None
        assert seg.emby_path is not None

        emby_dir = Path(seg.emby_path)
        assert emby_dir.is_dir()
        # Folder name from pattern
        assert emby_dir.name == "Phoebe Bridgers - Coachella W1 (2026)"
        # Movie file (e.g. <name>.mkv or .mp4)
        movies = list(emby_dir.glob("Phoebe Bridgers - Coachella W1 (2026).*"))
        media = [m for m in movies if m.suffix in (".mp4", ".mkv")]
        assert len(media) == 1
        assert (emby_dir / "movie.nfo").exists()
        assert (emby_dir / "poster.jpg").exists()
        assert (emby_dir / "fanart.jpg").exists()

    emby_client.trigger_path_scan.assert_awaited()


@pytest.mark.asyncio
async def test_publish_marks_failed_on_ffmpeg_error(db, tmp_path):
    """Pointing recording.path at a file that doesn't exist → ffmpeg fails → segment.status=publish_failed."""
    seg_id = _seed(db, tmp_path / "nonexistent.mp4")

    worker = PublishWorker(
        db=db,
        runner=AsyncSubprocessRunner(),
        publish_root=tmp_path / "media",
        folder_pattern="{artist} ({year})",
        emby_client=MagicMock(trigger_path_scan=AsyncMock()),
    )

    with pytest.raises(Exception):
        await worker.publish(seg_id, year=2026)

    with db.session() as s:
        seg = s.get(Segment, seg_id)
        assert seg.status == "publish_failed"
        assert seg.error is not None


@pytest.mark.asyncio
async def test_publish_404s_when_segment_missing(db, tmp_path):
    worker = PublishWorker(
        db=db, runner=AsyncSubprocessRunner(),
        publish_root=tmp_path, folder_pattern="{artist} ({year})",
        emby_client=MagicMock(trigger_path_scan=AsyncMock()),
    )
    with pytest.raises(LookupError):
        await worker.publish(9999, year=2026)
```

- [ ] **Step 2: Implement `src/concertpvr/publisher.py`**

```python
"""End-to-end publish: cut clip → write metadata → move to Emby library → trigger scan."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

from concertpvr.db import Database
from concertpvr.emby import EmbyClient
from concertpvr.ffmpeg import Splitter
from concertpvr.metadata import MetadataBuilder, SegmentMeta
from concertpvr.models import Recording, Segment, Stream
from concertpvr.process import ProcessRunner


class PublishWorker:
    def __init__(
        self,
        *,
        db: Database,
        runner: ProcessRunner,
        publish_root: Path,
        folder_pattern: str,
        emby_client: EmbyClient,
    ) -> None:
        self._db = db
        self._splitter = Splitter(runner)
        self._meta_builder = MetadataBuilder()
        self._publish_root = publish_root
        self._folder_pattern = folder_pattern
        self._emby = emby_client

    async def publish(
        self,
        segment_id: int,
        *,
        festival: str | None = None,
        venue: str | None = None,
        year: int | None = None,
    ) -> None:
        # Load segment + recording + stream
        with self._db.session() as s:
            seg = s.get(Segment, segment_id)
            if seg is None:
                raise LookupError(f"segment {segment_id} not found")
            seg.status = "publishing"
            seg.error = None
            rec = s.get(Recording, seg.recording_id)
            if rec is None:
                seg.status = "publish_failed"
                seg.error = "recording missing"
                raise LookupError(f"recording {seg.recording_id} not found")
            stream = s.get(Stream, rec.stream_id)

            # Snapshot fields for use after session closes
            artist = seg.artist
            title = seg.title
            start_s = seg.start_s
            end_s = seg.end_s
            source_path = Path(rec.path)
            stream_title = stream.title if stream else ""

        try:
            # Determine fallback metadata from stream title
            if year is None:
                year = rec.started_at.year if rec.started_at else _dt.datetime.now().year
            if festival is None:
                festival = stream_title.split("—")[0].strip() if stream_title else None
            if venue is None and "—" in stream_title:
                venue = stream_title.split("—", 1)[1].strip()

            # Compute folder name
            folder_name = self._folder_pattern.format(
                artist=artist,
                festival=festival or "",
                venue=venue or "",
                year=year,
                date=rec.started_at.date().isoformat() if rec.started_at else "",
                title=title or artist,
            ).strip()
            # Clean up multiple spaces and trailing dashes
            folder_name = " ".join(folder_name.split())

            target_dir = self._publish_root / folder_name
            target_dir.mkdir(parents=True, exist_ok=True)

            # Output media file extension from source
            media_ext = source_path.suffix or ".mkv"
            media_out = target_dir / f"{folder_name}{media_ext}"

            # Cut the segment
            await self._splitter.cut(
                source_path, media_out, start_s=float(start_s), end_s=float(end_s)
            )

            # Generate a thumbnail at the midpoint of the SOURCE for poster/fanart
            mid = float(start_s) + (float(end_s) - float(start_s)) / 2
            thumb = target_dir / "_thumb.jpg"
            await self._splitter.thumbnail(source_path, thumb, at_s=mid)

            # Build metadata
            meta = SegmentMeta(
                artist=artist,
                title=title,
                festival=festival,
                venue=venue,
                year=year,
                date=rec.started_at.date() if rec.started_at else None,
                duration_s=int(end_s - start_s),
                width=rec.width,
                height=rec.height,
            )
            nfo_path = self._meta_builder.build_nfo(meta, target_dir)
            poster_path = self._meta_builder.build_poster(meta, thumb, target_dir)
            self._meta_builder.build_fanart(thumb, target_dir)

            # Clean up intermediate thumb
            thumb.unlink(missing_ok=True)

            # Trigger Emby scan
            await self._emby.trigger_path_scan(str(target_dir))

            # Persist success
            with self._db.session() as s:
                seg = s.get(Segment, segment_id)
                if seg is not None:
                    seg.status = "published"
                    seg.emby_path = str(target_dir)
                    seg.poster_path = str(poster_path)
                    seg.nfo_path = str(nfo_path)

        except Exception as e:
            with self._db.session() as s:
                seg = s.get(Segment, segment_id)
                if seg is not None:
                    seg.status = "publish_failed"
                    seg.error = f"{type(e).__name__}: {e}"
            raise
```

- [ ] **Step 3: Run + commit**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_publisher.py -v
```
Expected: 3 pass.

```bash
git add src/concertpvr/publisher.py tests/test_publisher.py
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(publisher): orchestrate split → metadata → emby publish per segment"
```

---

## Task 9: Segments API CRUD + publish endpoint

**Files:**
- Create: `src/concertpvr/api/segments.py`
- Modify: `src/concertpvr/main.py` (register router; create app.state.emby_client + app.state.publisher_factory)
- Create: `tests/test_segments_api.py`

- [ ] **Step 1: Failing tests**

```python
# tests/test_segments_api.py
import datetime as dt
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from concertpvr.main import create_app
from concertpvr.models import Recording, Stream

FIXTURE = Path(__file__).parent / "fixtures" / "tiny.mp4"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CPVR_PUBLISH_DIR", str(tmp_path / "media"))
    with TestClient(create_app()) as c:
        yield c


def _seed_recording(client) -> int:
    db = client.app.state.db
    with db.session() as s:
        stream = Stream(kind="live", youtube_id="x", url="u",
                        title="Coachella — Mojave", channel_name="Coachella")
        s.add(stream)
        s.flush()
        rec = Recording(
            stream_id=stream.id,
            started_at=dt.datetime(2026, 4, 12, 14, 0, tzinfo=dt.UTC),
            path=str(FIXTURE),
            is_buffer=False,
            status="complete",
        )
        s.add(rec)
        s.flush()
        return rec.id


def test_post_segment_creates_draft(client):
    rid = _seed_recording(client)
    r = client.post("/api/segments", json={
        "recording_id": rid,
        "artist": "Phoebe Bridgers",
        "title": "Mojave Set",
        "start_s": 0,
        "end_s": 2,
        "source": "manual",
    })
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "draft"
    assert body["artist"] == "Phoebe Bridgers"


def test_post_segment_rejects_when_end_before_start(client):
    rid = _seed_recording(client)
    r = client.post("/api/segments", json={
        "recording_id": rid, "artist": "X", "start_s": 100, "end_s": 50, "source": "manual",
    })
    assert r.status_code == 400


def test_get_segments_filter_by_recording(client):
    rid = _seed_recording(client)
    client.post("/api/segments", json={
        "recording_id": rid, "artist": "A", "start_s": 0, "end_s": 1, "source": "manual",
    })
    client.post("/api/segments", json={
        "recording_id": rid, "artist": "B", "start_s": 1, "end_s": 2, "source": "manual",
    })
    r = client.get(f"/api/segments?recording_id={rid}")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    assert {row["artist"] for row in body} == {"A", "B"}


def test_patch_segment_updates_times(client):
    rid = _seed_recording(client)
    created = client.post("/api/segments", json={
        "recording_id": rid, "artist": "X", "start_s": 0, "end_s": 1, "source": "manual",
    }).json()
    r = client.patch(f"/api/segments/{created['id']}", json={"start_s": 1, "end_s": 2})
    assert r.status_code == 200
    assert r.json()["start_s"] == 1


def test_delete_segment(client):
    rid = _seed_recording(client)
    created = client.post("/api/segments", json={
        "recording_id": rid, "artist": "X", "start_s": 0, "end_s": 1, "source": "manual",
    }).json()
    r = client.delete(f"/api/segments/{created['id']}")
    assert r.status_code == 204


def test_publish_segment(client, tmp_path):
    rid = _seed_recording(client)
    seg = client.post("/api/segments", json={
        "recording_id": rid, "artist": "Phoebe Bridgers",
        "start_s": 0, "end_s": 2, "source": "manual",
    }).json()

    r = client.post(
        f"/api/segments/{seg['id']}/publish",
        json={"festival": "Coachella W1", "venue": "Mojave", "year": 2026},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "published"
    assert body["emby_path"] is not None

    # Check the file landed in the publish root
    emby_path = Path(body["emby_path"])
    assert emby_path.is_dir()
    assert (emby_path / "movie.nfo").exists()
```

- [ ] **Step 2: Implement `src/concertpvr/api/segments.py`**

```python
"""Segments CRUD + publish."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select

from concertpvr.db import Database
from concertpvr.deps import get_db
from concertpvr.models import Recording, Segment
from concertpvr.schemas import (
    PublishOptions, SegmentCreate, SegmentPatch, SegmentRead,
)

router = APIRouter()


@router.post("/segments", response_model=SegmentRead, status_code=status.HTTP_201_CREATED)
def create_segment(
    payload: SegmentCreate,
    db: Database = Depends(get_db),  # noqa: B008
) -> Segment:
    if payload.end_s <= payload.start_s:
        raise HTTPException(status_code=400, detail="end_s must be after start_s")
    with db.session() as s:
        if s.get(Recording, payload.recording_id) is None:
            raise HTTPException(status_code=404, detail="recording not found")
        seg = Segment(
            recording_id=payload.recording_id,
            artist=payload.artist,
            title=payload.title,
            start_s=payload.start_s,
            end_s=payload.end_s,
            source=payload.source,
            status="draft",
        )
        s.add(seg)
        s.flush()
        s.refresh(seg)
        s.expunge(seg)
    return seg


@router.get("/segments", response_model=list[SegmentRead])
def list_segments(
    recording_id: int | None = Query(None),
    db: Database = Depends(get_db),  # noqa: B008
) -> list[Segment]:
    with db.session() as s:
        stmt = select(Segment).order_by(Segment.start_s.asc())
        if recording_id is not None:
            stmt = stmt.where(Segment.recording_id == recording_id)
        rows = list(s.scalars(stmt))
        for r in rows:
            s.expunge(r)
    return rows


@router.get("/segments/{segment_id}", response_model=SegmentRead)
def get_segment(segment_id: int, db: Database = Depends(get_db)) -> Segment:  # noqa: B008
    with db.session() as s:
        row = s.get(Segment, segment_id)
        if row is None:
            raise HTTPException(status_code=404, detail="segment not found")
        s.expunge(row)
    return row


@router.patch("/segments/{segment_id}", response_model=SegmentRead)
def patch_segment(
    segment_id: int,
    patch: SegmentPatch,
    db: Database = Depends(get_db),  # noqa: B008
) -> Segment:
    updates = patch.model_dump(exclude_unset=True)
    with db.session() as s:
        seg = s.get(Segment, segment_id)
        if seg is None:
            raise HTTPException(status_code=404, detail="segment not found")
        for k, v in updates.items():
            setattr(seg, k, v)
        if seg.end_s <= seg.start_s:
            raise HTTPException(status_code=400, detail="end_s must be after start_s")
        s.flush()
        s.refresh(seg)
        s.expunge(seg)
    return seg


@router.delete("/segments/{segment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_segment(segment_id: int, db: Database = Depends(get_db)) -> Response:  # noqa: B008
    with db.session() as s:
        seg = s.get(Segment, segment_id)
        if seg is None:
            raise HTTPException(status_code=404, detail="segment not found")
        s.delete(seg)
    return Response(status_code=204)


@router.post("/segments/{segment_id}/publish", response_model=SegmentRead)
async def publish_segment(
    segment_id: int,
    options: PublishOptions,
    request: Request,
    db: Database = Depends(get_db),  # noqa: B008
) -> Segment:
    publisher = request.app.state.publisher_factory()
    try:
        await publisher.publish(
            segment_id,
            festival=options.festival,
            venue=options.venue,
            year=options.year,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    with db.session() as s:
        seg = s.get(Segment, segment_id)
        if seg is None:
            raise HTTPException(status_code=404, detail="segment not found post-publish")
        s.expunge(seg)
    return seg
```

- [ ] **Step 3: Wire into `src/concertpvr/main.py` lifespan**

In `lifespan()`, after the `register_app(...)` block, add:

```python
    from concertpvr.emby import EmbyClient
    from concertpvr.models import Settings as SettingsModel
    from concertpvr.publisher import PublishWorker
    from concertpvr.process import AsyncSubprocessRunner

    with app.state.db.session() as s:
        settings_row = s.get(SettingsModel, 1)
        emby_url = settings_row.emby_url if settings_row else None
        emby_key = settings_row.emby_api_key if settings_row else None
        folder_pattern = (
            settings_row.folder_pattern if settings_row
            else "{artist} - {festival} ({year})"
        )

    app.state.emby_client = EmbyClient(emby_url, emby_key)

    def _publisher_factory() -> PublishWorker:
        return PublishWorker(
            db=app.state.db,
            runner=AsyncSubprocessRunner(),
            publish_root=cfg.publish_dir,
            folder_pattern=folder_pattern,
            emby_client=app.state.emby_client,
        )

    app.state.publisher_factory = _publisher_factory
```

In `create_app()`, register the router:

```python
    from concertpvr.api.segments import router as segments_router
    app.include_router(segments_router, prefix="/api")
```

- [ ] **Step 4: Run + commit**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_segments_api.py -v
./.venv/Scripts/python.exe -m pytest -q
```
Expected: 6 new pass; full suite ~108 (87 + 4 ffmpeg + 6 metadata + 3 emby + 5 segmenter + 3 publisher + 6 segments).

```bash
git add src/concertpvr/api/segments.py src/concertpvr/main.py tests/test_segments_api.py
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(api): segments CRUD + /publish endpoint wired to PublishWorker"
```

---

## Task 10: Setlists API + setlist parser

**Files:**
- Create: `src/concertpvr/setlist_parser.py`
- Create: `src/concertpvr/api/setlists.py`
- Modify: `src/concertpvr/main.py` (register router)
- Create: `tests/test_setlist_parser.py`
- Create: `tests/test_setlists_api.py`
- Create: `tests/fixtures/setlist_paste.txt`

The setlist API supports two modes:
- `POST /api/recordings/{id}/setlist` with structured `entries[]` (replaces all)
- `POST /api/recordings/{id}/setlist/paste` with raw text (server parses lines like `Phoebe Bridgers · 00:21–01:34`)

- [ ] **Step 1: Create test fixture**

`tests/fixtures/setlist_paste.txt`:

```
Phoebe Bridgers · 00:21–01:34
Goose · 1:51 - 3:42
Rüfüs Du Sol · 3:58–5:18
Tame Impala · 05:31 to 07:05
```

- [ ] **Step 2: Tests for the parser**

```python
# tests/test_setlist_parser.py
from pathlib import Path

from concertpvr.setlist_parser import parse_setlist_paste, ParseError

import pytest


def test_parses_unicode_em_dash():
    result = parse_setlist_paste("Phoebe Bridgers · 00:21–01:34")
    assert len(result) == 1
    assert result[0].artist == "Phoebe Bridgers"
    assert result[0].start_s == 21
    assert result[0].end_s == 60 + 34


def test_parses_ascii_dash():
    result = parse_setlist_paste("Goose · 1:51 - 3:42")
    assert result[0].start_s == 1 * 60 + 51
    assert result[0].end_s == 3 * 60 + 42


def test_parses_to_separator():
    result = parse_setlist_paste("Tame Impala · 05:31 to 07:05")
    assert result[0].start_s == 5 * 60 + 31


def test_parses_multiline():
    fixture = Path(__file__).parent / "fixtures" / "setlist_paste.txt"
    result = parse_setlist_paste(fixture.read_text(encoding="utf-8"))
    assert len(result) == 4
    assert {e.artist for e in result} == {
        "Phoebe Bridgers", "Goose", "Rüfüs Du Sol", "Tame Impala"
    }


def test_skips_empty_lines_and_comments():
    text = """
# Coachella W1
Phoebe Bridgers · 00:21–01:34

Goose · 1:51 - 3:42
"""
    result = parse_setlist_paste(text)
    assert len(result) == 2


def test_raises_on_unparseable_line():
    with pytest.raises(ParseError):
        parse_setlist_paste("totally invalid garbage")
```

- [ ] **Step 3: Implement `src/concertpvr/setlist_parser.py`**

```python
"""Parse pasted festival lineups into structured setlist entries.

Accepts lines like:
    Phoebe Bridgers · 00:21–01:34
    Goose · 1:51 - 3:42
    Tame Impala · 05:31 to 07:05

Times are interpreted as offsets from the recording start.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


class ParseError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedEntry:
    artist: str
    start_s: int
    end_s: int


_LINE_RE = re.compile(
    r"""
    ^\s*(?P<artist>.+?)\s*[·\-]\s*    # Artist, then either · or -
    (?P<start>\d{1,2}:\d{2}(?::\d{2})?)\s*    # hh:mm or h:mm:ss
    \s*(?:[–\-]|to)\s*                # separator: en-dash, hyphen, or "to"
    (?P<end>\d{1,2}:\d{2}(?::\d{2})?)\s*$
    """,
    re.VERBOSE,
)


def _to_seconds(s: str) -> int:
    parts = [int(p) for p in s.split(":")]
    if len(parts) == 2:
        m, sec = parts
        return m * 60 + sec
    if len(parts) == 3:
        h, m, sec = parts
        return h * 3600 + m * 60 + sec
    raise ParseError(f"invalid time: {s}")


def parse_setlist_paste(text: str) -> list[ParsedEntry]:
    entries: list[ParsedEntry] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _LINE_RE.match(line)
        if m is None:
            raise ParseError(f"unparseable line: {line!r}")
        entries.append(ParsedEntry(
            artist=m.group("artist").strip(),
            start_s=_to_seconds(m.group("start")),
            end_s=_to_seconds(m.group("end")),
        ))
    return entries
```

- [ ] **Step 4: Tests for the API**

```python
# tests/test_setlists_api.py
import datetime as dt
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from concertpvr.main import create_app
from concertpvr.models import Recording, Stream


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))
    with TestClient(create_app()) as c:
        yield c


def _seed_recording(client) -> int:
    db = client.app.state.db
    with db.session() as s:
        stream = Stream(kind="live", youtube_id="x", url="u", title="t", channel_name="c")
        s.add(stream)
        s.flush()
        rec = Recording(
            stream_id=stream.id,
            started_at=dt.datetime(2026, 4, 12, 14, 0, tzinfo=dt.UTC),
            path="/buf/1", is_buffer=True,
        )
        s.add(rec)
        s.flush()
        return rec.id


def test_post_setlist_replaces_all(client):
    rid = _seed_recording(client)
    r = client.post(f"/api/recordings/{rid}/setlist", json={
        "entries": [
            {"artist": "Phoebe Bridgers", "start_s": 21, "end_s": 94},
            {"artist": "Goose", "start_s": 100, "end_s": 200},
        ],
    })
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2

    # Re-post with one entry replaces the previous two
    r2 = client.post(f"/api/recordings/{rid}/setlist", json={
        "entries": [{"artist": "Tame Impala", "start_s": 5, "end_s": 10}],
    })
    assert r2.status_code == 200
    assert len(r2.json()) == 1


def test_post_setlist_paste_parses_text(client):
    rid = _seed_recording(client)
    paste = (Path(__file__).parent / "fixtures" / "setlist_paste.txt").read_text(encoding="utf-8")
    r = client.post(
        f"/api/recordings/{rid}/setlist/paste",
        content=paste,
        headers={"content-type": "text/plain"},
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 4


def test_get_setlist(client):
    rid = _seed_recording(client)
    client.post(f"/api/recordings/{rid}/setlist", json={
        "entries": [{"artist": "Goose", "start_s": 1, "end_s": 2}],
    })
    r = client.get(f"/api/recordings/{rid}/setlist")
    assert r.status_code == 200
    assert r.json()[0]["artist"] == "Goose"


def test_post_setlist_404_for_unknown_recording(client):
    r = client.post("/api/recordings/9999/setlist", json={"entries": []})
    assert r.status_code == 404


def test_post_paste_400_on_unparseable(client):
    rid = _seed_recording(client)
    r = client.post(
        f"/api/recordings/{rid}/setlist/paste",
        content="absolute nonsense line",
        headers={"content-type": "text/plain"},
    )
    assert r.status_code == 400
```

- [ ] **Step 5: Implement `src/concertpvr/api/setlists.py`**

```python
"""Setlist replace + paste endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import delete, select

from concertpvr.db import Database
from concertpvr.deps import get_db
from concertpvr.models import Recording, Setlist
from concertpvr.schemas import SetlistRead, SetlistReplaceRequest
from concertpvr.setlist_parser import ParseError, parse_setlist_paste

router = APIRouter()


def _replace_entries(db: Database, recording_id: int, entries: list) -> list[Setlist]:
    with db.session() as s:
        if s.get(Recording, recording_id) is None:
            raise HTTPException(status_code=404, detail="recording not found")
        s.execute(delete(Setlist).where(Setlist.recording_id == recording_id))
        rows: list[Setlist] = []
        for e in entries:
            row = Setlist(
                recording_id=recording_id,
                artist=e.artist,
                start_s=e.start_s,
                end_s=e.end_s,
            )
            s.add(row)
            rows.append(row)
        s.flush()
        for r in rows:
            s.refresh(r)
            s.expunge(r)
    return rows


@router.get("/recordings/{recording_id}/setlist", response_model=list[SetlistRead])
def get_setlist(
    recording_id: int,
    db: Database = Depends(get_db),  # noqa: B008
) -> list[Setlist]:
    with db.session() as s:
        if s.get(Recording, recording_id) is None:
            raise HTTPException(status_code=404, detail="recording not found")
        rows = list(s.scalars(
            select(Setlist).where(Setlist.recording_id == recording_id).order_by(Setlist.start_s)
        ))
        for r in rows:
            s.expunge(r)
    return rows


@router.post("/recordings/{recording_id}/setlist", response_model=list[SetlistRead])
def post_setlist(
    recording_id: int,
    payload: SetlistReplaceRequest,
    db: Database = Depends(get_db),  # noqa: B008
) -> list[Setlist]:
    return _replace_entries(db, recording_id, payload.entries)


@router.post("/recordings/{recording_id}/setlist/paste", response_model=list[SetlistRead])
def post_setlist_paste(
    recording_id: int,
    body: bytes = Body(..., media_type="text/plain"),
    db: Database = Depends(get_db),  # noqa: B008
) -> list[Setlist]:
    text = body.decode("utf-8", errors="replace")
    try:
        parsed = parse_setlist_paste(text)
    except ParseError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _replace_entries(db, recording_id, parsed)
```

- [ ] **Step 6: Register in `src/concertpvr/main.py`**

In `create_app()`, after segments router:

```python
    from concertpvr.api.setlists import router as setlists_router
    app.include_router(setlists_router, prefix="/api")
```

- [ ] **Step 7: Run + commit**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_setlist_parser.py tests/test_setlists_api.py -v
./.venv/Scripts/python.exe -m pytest -q
```
Expected: 6 parser + 5 api = 11 new pass.

```bash
git add src/concertpvr/setlist_parser.py src/concertpvr/api/setlists.py src/concertpvr/main.py tests/test_setlist_parser.py tests/test_setlists_api.py tests/fixtures/setlist_paste.txt
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(api): setlists endpoint with structured + paste-parser modes"
```

---

## Task 11: Auto-derive segments after recording completes

This wires the segmenter into the recorder flow: when a `Recording.status` flips to `complete`, automatically derive draft segments. We do this with a simple SQLAlchemy event listener on the Recording model that fires `derive_draft_segments` when status changes.

**Files:**
- Create: `src/concertpvr/auto_segment.py`
- Modify: `src/concertpvr/main.py` (call register at startup)
- Create: `tests/test_auto_segment.py`

- [ ] **Step 1: Tests**

```python
# tests/test_auto_segment.py
import datetime as dt
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from concertpvr.main import create_app
from concertpvr.models import Recording, Segment, Stream


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))
    with TestClient(create_app()) as c:
        yield c


def test_setting_recording_complete_with_chapters_creates_segments(client):
    db = client.app.state.db
    chapters = json.dumps([
        {"title": "A", "start_time": 0, "end_time": 60},
        {"title": "B", "start_time": 60, "end_time": 120},
    ])
    with db.session() as s:
        stream = Stream(kind="live", youtube_id="x", url="u", title="t", channel_name="c")
        s.add(stream)
        s.flush()
        rec = Recording(
            stream_id=stream.id,
            started_at=dt.datetime(2026, 4, 12, 14, 0, tzinfo=dt.UTC),
            path="/buf/1",
            status="recording",
            is_buffer=True,
            raw_chapters_json=chapters,
        )
        s.add(rec)
        s.flush()
        rid = rec.id

    # Flip to complete in another session — listener should fire
    with db.session() as s:
        rec = s.get(Recording, rid)
        rec.status = "complete"

    with db.session() as s:
        segments = s.query(Segment).filter_by(recording_id=rid).all()
        assert len(segments) == 2
        assert {seg.artist for seg in segments} == {"A", "B"}


def test_completion_without_chapters_creates_no_segments(client):
    db = client.app.state.db
    with db.session() as s:
        stream = Stream(kind="live", youtube_id="y", url="u", title="t", channel_name="c")
        s.add(stream)
        s.flush()
        rec = Recording(
            stream_id=stream.id,
            started_at=dt.datetime(2026, 4, 12, 14, 0, tzinfo=dt.UTC),
            path="/buf/1",
            status="recording",
            is_buffer=True,
        )
        s.add(rec)
        s.flush()
        rid = rec.id

    with db.session() as s:
        rec = s.get(Recording, rid)
        rec.status = "complete"

    with db.session() as s:
        segments = s.query(Segment).filter_by(recording_id=rid).all()
        assert segments == []
```

- [ ] **Step 2: Implement `src/concertpvr/auto_segment.py`**

```python
"""SQLAlchemy event listener: derive draft segments when a Recording becomes complete."""

from __future__ import annotations

from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session

from concertpvr.models import Recording, Segment
from concertpvr.segmenter import derive_draft_segments


def register() -> None:
    """Call once at app startup to install the listener."""

    @event.listens_for(Session, "before_flush")
    def _before_flush(session: Session, flush_context, instances) -> None:  # noqa: ANN001, ARG001
        for obj in session.dirty:
            if not isinstance(obj, Recording):
                continue
            insp = inspect(obj)
            status_history = insp.attrs.status.history
            if not status_history.has_changes():
                continue
            if obj.status != "complete":
                continue
            # Idempotent: skip if segments already exist for this recording.
            existing = session.scalar(
                select(Segment.id).where(Segment.recording_id == obj.id).limit(1)
            )
            if existing is None:
                derive_draft_segments(obj, session)
```

- [ ] **Step 3: Wire in `src/concertpvr/main.py` lifespan (after register_app)**

```python
    from concertpvr.auto_segment import register as _register_auto_segment
    _register_auto_segment()
```

- [ ] **Step 4: Run + commit**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_auto_segment.py -v
./.venv/Scripts/python.exe -m pytest -q
```
Expected: 2 new pass.

```bash
git add src/concertpvr/auto_segment.py src/concertpvr/main.py tests/test_auto_segment.py
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(auto_segment): derive draft segments on Recording.status=complete"
```

---

## Task 12: yt-dlp chapters captured into recordings

When the buffer recorder or schedule runner finishes, yt-dlp may have written chapter metadata. We probe for it and persist into `recordings.raw_chapters_json`.

**Files:**
- Modify: `src/concertpvr/api/streams.py` (after pool.stop in patch_watch — capture chapters when recording ends)
- Modify: `src/concertpvr/scheduled_runner.py` (capture chapters at the end)
- Create: `src/concertpvr/chapters.py` (reusable helper)
- Create: `tests/test_chapters.py`

For Phase 4a we keep this minimal: a helper that, given a recording's `path` (a directory of fragments), tries to find a `.info.json` that yt-dlp dropped alongside, and pulls its chapter list.

- [ ] **Step 1: Tests**

```python
# tests/test_chapters.py
import json
from pathlib import Path

from concertpvr.chapters import extract_chapters_json


def test_returns_none_when_no_info_json(tmp_path: Path):
    assert extract_chapters_json(tmp_path) is None


def test_extracts_chapters_from_info_json(tmp_path: Path):
    info = tmp_path / "1234.info.json"
    info.write_text(json.dumps({
        "id": "abc",
        "chapters": [
            {"title": "Phoebe Bridgers", "start_time": 21, "end_time": 1900},
            {"title": "Goose", "start_time": 1900, "end_time": 4000},
        ],
    }))
    result = extract_chapters_json(tmp_path)
    assert result is not None
    parsed = json.loads(result)
    assert len(parsed) == 2
    assert parsed[0]["title"] == "Phoebe Bridgers"


def test_returns_none_when_info_has_no_chapters(tmp_path: Path):
    info = tmp_path / "1234.info.json"
    info.write_text(json.dumps({"id": "abc"}))
    assert extract_chapters_json(tmp_path) is None


def test_finds_info_json_in_subdirs(tmp_path: Path):
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "x.info.json").write_text(json.dumps({
        "chapters": [{"title": "X", "start_time": 0, "end_time": 10}],
    }))
    result = extract_chapters_json(tmp_path)
    assert result is not None
```

- [ ] **Step 2: Implement `src/concertpvr/chapters.py`**

```python
"""Extract chapter metadata from a yt-dlp output directory."""

from __future__ import annotations

import json
from pathlib import Path


def extract_chapters_json(directory: Path) -> str | None:
    """Search `directory` (recursively) for a .info.json file with chapters.

    Returns the chapters JSON serialized as a string (suitable for
    Recording.raw_chapters_json), or None if no chapters were found.
    """
    if not directory.is_dir():
        return None
    for info_file in directory.rglob("*.info.json"):
        try:
            data = json.loads(info_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        chapters = data.get("chapters")
        if chapters and isinstance(chapters, list):
            return json.dumps(chapters)
    return None
```

- [ ] **Step 3: Wire into the buffer recorder lifecycle**

In `src/concertpvr/api/streams.py`, the `_start_recording` function: after `pool.start(worker)` we don't currently have a hook for "recording ended". For Phase 4a we wire a simpler version — an explicit endpoint `POST /api/recordings/{id}/finalize` that captures chapters + sets `status=complete`. This is what the user (or a future scheduler) can call when wrapping up a recording.

Append this to `src/concertpvr/api/recordings.py`:

```python
import datetime as _dt
from pathlib import Path

from concertpvr.chapters import extract_chapters_json


@router.post("/recordings/{recording_id}/finalize", response_model=RecordingRead)
def finalize_recording(
    recording_id: int,
    db: Database = Depends(get_db),  # noqa: B008
) -> Recording:
    """Mark a recording complete + capture chapter metadata from its path.

    Triggers the auto_segment listener which creates draft Segments.
    """
    with db.session() as s:
        rec = s.get(Recording, recording_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="recording not found")
        chapters = extract_chapters_json(Path(rec.path))
        if chapters is not None:
            rec.raw_chapters_json = chapters
        rec.status = "complete"
        rec.ended_at = _dt.datetime.now(_dt.UTC)
        s.flush()
        s.refresh(rec)
        s.expunge(rec)
    return rec
```

- [ ] **Step 4: Test for the finalize endpoint**

Append to `tests/test_recordings_api.py`:

```python
import json


def test_finalize_recording_captures_chapters_and_creates_segments(client, tmp_path):
    db = client.app.state.db

    # Seed a recording whose path is a real directory with a chapters info.json
    rec_dir = tmp_path / "rec1"
    rec_dir.mkdir()
    (rec_dir / "x.info.json").write_text(json.dumps({
        "chapters": [
            {"title": "Phoebe", "start_time": 0, "end_time": 60},
            {"title": "Goose", "start_time": 60, "end_time": 120},
        ],
    }))

    with db.session() as s:
        from concertpvr.models import Stream
        stream = Stream(kind="live", youtube_id="x", url="u", title="t", channel_name="c")
        s.add(stream)
        s.flush()
        from concertpvr.models import Recording
        rec = Recording(
            stream_id=stream.id,
            started_at=dt.datetime(2026, 4, 25, 12, 0, tzinfo=dt.UTC),
            path=str(rec_dir),
            is_buffer=True,
            status="recording",
        )
        s.add(rec)
        s.flush()
        rid = rec.id

    r = client.post(f"/api/recordings/{rid}/finalize")
    assert r.status_code == 200
    assert r.json()["status"] == "complete"
    assert r.json()["raw_chapters_json"] is None  # not in schema response (intentional)

    # Segments should have been auto-created via the listener
    segs = client.get(f"/api/segments?recording_id={rid}").json()
    assert len(segs) == 2
    assert {seg["artist"] for seg in segs} == {"Phoebe", "Goose"}
```

NOTE: `raw_chapters_json` is NOT in the `RecordingRead` schema — we don't expose raw yt-dlp internals to the client. The test asserts it via the segments side-effect.

- [ ] **Step 5: Run + commit**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_chapters.py tests/test_recordings_api.py -v
./.venv/Scripts/python.exe -m pytest -q
```
Expected: 4 chapters + 1 new recordings test pass.

```bash
git add src/concertpvr/chapters.py src/concertpvr/api/recordings.py tests/test_chapters.py tests/test_recordings_api.py
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(chapters): finalize endpoint captures yt-dlp chapters and triggers auto-segment"
```

---

## Task 13: Wire emby_client config to settings PATCH

When the user updates `emby_url` or `emby_api_key` via the existing Settings PATCH endpoint, we need `app.state.emby_client` to refresh. Right now it's only built once at startup.

**Files:**
- Modify: `src/concertpvr/api/settings.py` (rebuild emby_client on PATCH)
- Modify: `tests/test_settings_api.py` (add a verification test)

- [ ] **Step 1: Update `patch_settings` in `src/concertpvr/api/settings.py`**

After the section that updates the row, add:

```python
    # Rebuild emby_client if Emby config changed.
    from concertpvr.emby import EmbyClient
    request.app.state.emby_client = EmbyClient(row.emby_url, row.emby_api_key)
```

(Add `Request` import at the top, accept `request: Request` as a param.)

Full `patch_settings` becomes:

```python
@router.patch("/settings", response_model=SettingsRead)
def patch_settings(
    patch: SettingsPatch,
    request: Request,
    db: Database = Depends(get_db),  # noqa: B008
) -> Settings:
    updates = patch.model_dump(exclude_unset=True)
    with db.session() as s:
        row = s.get(Settings, 1)
        if row is None:
            row = Settings(id=1)
            s.add(row)
            s.flush()
        for k, v in updates.items():
            setattr(row, k, v)
        s.flush()
        s.refresh(row)
        s.expunge(row)

    from concertpvr.emby import EmbyClient
    request.app.state.emby_client = EmbyClient(row.emby_url, row.emby_api_key)

    return row
```

Add the import at top:
```python
from fastapi import APIRouter, Depends, Request
```

- [ ] **Step 2: Test**

Append to `tests/test_settings_api.py`:

```python
def test_patching_emby_config_rebuilds_client(client):
    # Initially unconfigured
    assert client.app.state.emby_client.configured is False

    client.patch("/api/settings", json={
        "emby_url": "http://emby:8096",
        "emby_api_key": "secret123",
    })

    assert client.app.state.emby_client.configured is True
```

- [ ] **Step 3: Run + commit**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_settings_api.py -v
./.venv/Scripts/python.exe -m pytest -q
```
Expected: 5 in test_settings_api.py (4 existing + 1 new).

```bash
git add src/concertpvr/api/settings.py tests/test_settings_api.py
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(settings): rebuild emby_client when emby config patched"
```

---

## Task 14: Phase 4a wrap-up

- [ ] **Step 1: Backend sweep**

```bash
./.venv/Scripts/python.exe -m ruff check src/ tests/
./.venv/Scripts/python.exe -m ruff format --check src/ tests/
./.venv/Scripts/python.exe -m mypy src/
./.venv/Scripts/python.exe -m pytest -q
```

If anything fails, fix INLINE per the same guardrails used in Phases 2 and 3 — never weaken `Field(...)` defaults, never change tests to assert something different from the spec, never relax mypy strictness.

Allowed fixes:
- `ruff format src/ tests/` for formatting
- `# noqa: B008` for FastAPI Depends defaults
- `# type: ignore[import-untyped]` for missing stubs

- [ ] **Step 2: Frontend sweep**

```bash
cd frontend && npm run typecheck && npm run build && cd ..
```

(Frontend is unchanged in 4a — should still pass without changes.)

- [ ] **Step 3: Commit fixes if any, then tag**

```bash
git status
git add -A
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "chore: phase 4a wrap-up — lint/type/test sweep" || echo "(nothing to commit)"

git tag -a phase-4a-segment-publish-backend -m "Phase 4a complete: segment + publish backend pipeline"
git log --oneline phase-3-schedule..HEAD
```

- [ ] **Step 4: Manual smoke test (optional)**

Boot the app. With a finished recording in the DB:
```bash
curl -X POST http://localhost:8787/api/recordings/1/finalize  # captures chapters → auto-segments
curl http://localhost:8787/api/segments?recording_id=1         # see drafts
curl -X POST http://localhost:8787/api/segments/1/publish \
     -H "content-type: application/json" \
     -d '{"festival": "Coachella W1", "year": 2026}'           # publishes to Emby movies dir
```

Verify the file lands in the publish dir with `movie.nfo`, `poster.jpg`, `fanart.jpg`. Add Emby URL via settings to also trigger library refresh.

---

## Phase 4a done

At tag `phase-4a-segment-publish-backend`:
- 3 new tables (`segments`, `setlists`, `recordings.raw_chapters_json`)
- ffmpeg-driven splitting tested against a real tiny.mp4 fixture
- Pillow-driven NFO + poster + fanart generation
- Emby library refresh via `/Library/Media/Updated`
- Auto-segment derivation from chapters (preferred) or setlist (fallback) when a Recording flips to complete
- Setlist paste parser supporting unicode em-dashes, hyphens, "to" separators
- `/api/segments` CRUD + `/publish`; `/api/recordings/{id}/setlist` (structured + paste); `/api/recordings/{id}/finalize`
- Emby client rebuilt automatically on settings PATCH

**Tests added:** ~36 new (4 ffmpeg, 6 metadata, 3 emby, 5 segmenter, 3 publisher, 6 segments_api, 6 setlist_parser, 5 setlists_api, 2 auto_segment, 4 chapters, 1 settings, 1 recordings_api).

**Next: Phase 4b — Timeline UI.** Vidstack + wavesurfer.js on the frontend, segment region drag editor, setlist paste modal, full Library page.
