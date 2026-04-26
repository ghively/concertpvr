"""Recordings read API."""

from __future__ import annotations

import datetime as _dt
import mimetypes
import re
from collections.abc import Generator
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select

from concertpvr.chapters import extract_chapters_json
from concertpvr.db import Database
from concertpvr.deps import get_db
from concertpvr.models import Recording
from concertpvr.schemas import RecordingRead

router = APIRouter()


@router.get("/recordings", response_model=list[RecordingRead])
def list_recordings(
    stream_id: int | None = Query(None),
    status: str | None = Query(None),
    db: Database = Depends(get_db),  # noqa: B008
) -> list[Recording]:
    with db.session() as s:
        stmt = select(Recording).order_by(Recording.started_at.desc())
        if stream_id is not None:
            stmt = stmt.where(Recording.stream_id == stream_id)
        if status is not None:
            stmt = stmt.where(Recording.status == status)
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
