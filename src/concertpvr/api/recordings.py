"""Recordings read API."""

from __future__ import annotations

import datetime as _dt
import mimetypes
import re
import shutil
from collections.abc import Generator
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select

from concertpvr.chapters import extract_chapters_json
from concertpvr.db import Database
from concertpvr.deps import get_db
from concertpvr.models import Recording, Schedule, Segment
from concertpvr.schemas import RecordingRead, ScheduleRead

router = APIRouter()


@router.get("/recordings", response_model=list[RecordingRead])
def list_recordings(
    stream_id: int | None = Query(None),
    status: str | None = Query(None),
    limit: int | None = Query(None, ge=1, le=10000),  # noqa: B008
    offset: int = Query(0, ge=0),  # noqa: B008
    db: Database = Depends(get_db),  # noqa: B008
) -> list[Recording]:
    with db.session() as s:
        stmt = select(Recording).order_by(Recording.started_at.desc())
        if stream_id is not None:
            stmt = stmt.where(Recording.stream_id == stream_id)
        if status is not None:
            stmt = stmt.where(Recording.status == status)
        if limit is not None:
            stmt = stmt.limit(limit).offset(offset)
        elif offset > 0:
            stmt = stmt.offset(offset)
        rows = list(s.scalars(stmt))
        for r in rows:
            s.expunge(r)
    return rows


@router.get("/recordings/{recording_id}", response_model=RecordingRead)
def get_recording(
    recording_id: int,
    db: Database = Depends(get_db),  # noqa: B008
) -> Recording:
    with db.session() as s:
        row = s.get(Recording, recording_id)
        if row is None:
            raise HTTPException(status_code=404, detail="recording not found")
        s.expunge(row)
    return row


@router.post("/recordings/{recording_id}/finalize", response_model=RecordingRead)
async def finalize_recording(
    recording_id: int,
    db: Database = Depends(get_db),  # noqa: B008
) -> Recording:
    """Mark a recording complete + capture chapter metadata + probe dimensions.

    Triggers the auto_segment listener which creates draft Segments.
    """
    # Snapshot path so we can probe outside the session
    with db.session() as s:
        rec = s.get(Recording, recording_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="recording not found")
        path_str = rec.path

    # Probe dimensions if the recording is a single file (scheduled output).
    # Buffer recordings are directories of .ts fragments; ffprobe doesn't handle those.
    rec_path = Path(path_str)
    probed_w: int | None = None
    probed_h: int | None = None
    probed_fps: int | None = None
    probed_duration_s: int = 0
    probed_size_bytes: int = 0
    if rec_path.is_file():
        import contextlib

        from concertpvr.ffmpeg import FFmpegError, Splitter
        from concertpvr.process import AsyncSubprocessRunner

        with contextlib.suppress(FFmpegError):
            info = await Splitter(AsyncSubprocessRunner()).probe(rec_path)
            probed_w = info.width
            probed_h = info.height
            probed_fps = int(round(info.fps))
            probed_duration_s = int(info.duration_s)
        with contextlib.suppress(OSError):
            probed_size_bytes = rec_path.stat().st_size

    with db.session() as s:
        rec = s.get(Recording, recording_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="recording not found")
        chapters = extract_chapters_json(Path(rec.path))
        if chapters is not None:
            rec.raw_chapters_json = chapters
        if probed_w is not None:
            rec.width = probed_w
            rec.height = probed_h
            rec.fps = probed_fps
            rec.duration_s = probed_duration_s
            rec.size_bytes = probed_size_bytes
        rec.status = "complete"
        rec.ended_at = _dt.datetime.now(_dt.UTC)
        s.flush()
        s.refresh(rec)
        s.expunge(rec)
    return rec


_RANGE_RE = re.compile(r"bytes=(\d+)-(\d*)")
_CHUNK_SIZE = 1024 * 1024


def _stream_file(path: Path, start: int, end: int) -> Generator[bytes, None, None]:
    remaining = end - start + 1
    with path.open("rb") as f:
        f.seek(start)
        while remaining > 0:
            chunk = f.read(min(_CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


@router.get("/recordings/{recording_id}/media")
def get_recording_media(
    recording_id: int,
    request: Request,
    db: Database = Depends(get_db),  # noqa: B008
) -> Response:
    with db.session() as s:
        rec = s.get(Recording, recording_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="recording not found")
        path = Path(rec.path)

    if not path.exists():
        raise HTTPException(status_code=404, detail="recording file missing")
    if path.is_dir():
        raise HTTPException(
            status_code=415,
            detail="recording is a directory of fragments; only single-file recordings can be served",
        )

    file_size = path.stat().st_size
    media_type, _ = mimetypes.guess_type(str(path))
    if media_type is None:
        media_type = "application/octet-stream"

    range_header = request.headers.get("range")
    if range_header:
        match = _RANGE_RE.match(range_header)
        if match is None:
            raise HTTPException(status_code=400, detail="invalid Range header")
        start = int(match.group(1))
        end_str = match.group(2)
        end = int(end_str) if end_str else file_size - 1
        if start >= file_size or end >= file_size:
            return Response(
                status_code=416,
                headers={"content-range": f"bytes */{file_size}"},
            )
        content_length = end - start + 1
        return StreamingResponse(
            _stream_file(path, start, end),
            status_code=206,
            media_type=media_type,
            headers={
                "content-range": f"bytes {start}-{end}/{file_size}",
                "content-length": str(content_length),
                "accept-ranges": "bytes",
            },
        )

    return StreamingResponse(
        _stream_file(path, 0, file_size - 1),
        status_code=200,
        media_type=media_type,
        headers={
            "content-length": str(file_size),
            "accept-ranges": "bytes",
        },
    )


@router.post("/recordings/{recording_id}/retry", status_code=200)
async def retry_vod(
    recording_id: int,
    request: Request,
    db: Database = Depends(get_db),  # noqa: B008
) -> dict[str, str]:
    """Re-queue a failed VOD download."""
    with db.session() as s:
        rec = s.get(Recording, recording_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="recording not found")
        if rec.status != "vod_failed":
            raise HTTPException(status_code=409, detail="recording is not in vod_failed state")
        rec.status = "vod_queued"
        rec.error = None
        s.flush()
        rec_id = rec.id

    await request.app.state.vod_queue.enqueue(rec_id)
    return {"status": "vod_queued"}


@router.get("/recordings/{recording_id}/schedule", response_model=ScheduleRead | None)
def get_recording_schedule(
    recording_id: int,
    db: Database = Depends(get_db),  # noqa: B008
) -> Schedule | None:
    """Return the Schedule that produced this Recording, or null if it was ad-hoc.

    Reverse lookup for the v0.1 limitation where Recording rows didn't carry a
    schedule_id. Implemented as a query against Schedule.recording_id (which has
    been indexed since v0.1.1) — no migration needed.
    """
    with db.session() as s:
        rec = s.get(Recording, recording_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="recording not found")
        sched = s.scalar(select(Schedule).where(Schedule.recording_id == recording_id))
        if sched is None:
            return None
        s.expunge(sched)
    return sched


@router.post("/recordings/{recording_id}/cancel", status_code=200)
async def cancel_vod_download(
    recording_id: int,
    request: Request,
    db: Database = Depends(get_db),  # noqa: B008
) -> dict[str, str]:
    """Cancel a queued or running VOD download.

    Behavior by current status:
      - vod_queued: marks the row vod_cancelled; the queue worker skips it when its turn comes.
      - vod_downloading: SIGTERMs the yt-dlp subprocess; the worker observes
        VodCancelled and writes vod_cancelled.
      - any other status: 409 Conflict (recording is not cancellable).
    """
    with db.session() as s:
        rec = s.get(Recording, recording_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="recording not found")
        if rec.status not in ("vod_queued", "vod_downloading"):
            raise HTTPException(
                status_code=409,
                detail=f"recording is in {rec.status} state — only queued/downloading can be cancelled",
            )

    result = await request.app.state.vod_queue.cancel(recording_id)
    return {"status": "vod_cancelled", "previous": result}


@router.delete("/recordings/{recording_id}/source", status_code=204)
def delete_source(
    recording_id: int,
    db: Database = Depends(get_db),  # noqa: B008
) -> Response:
    """Delete the source recording file/directory after all segments are published."""
    with db.session() as s:
        rec = s.get(Recording, recording_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="recording not found")
        if rec.source_deleted:
            raise HTTPException(status_code=409, detail="source already deleted")

        segs = list(s.scalars(select(Segment).where(Segment.recording_id == recording_id)))
        if not segs:
            raise HTTPException(status_code=409, detail="no segments exist for this recording")
        if any(seg.status != "published" for seg in segs):
            raise HTTPException(status_code=409, detail="not all segments are published")

        path = Path(rec.path)
        try:
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"file removal failed: {exc}") from exc

        rec.source_deleted = True

    return Response(status_code=204)
