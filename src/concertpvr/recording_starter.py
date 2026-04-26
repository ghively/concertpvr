"""Shared helper for kicking off buffer-style recordings.

Used both by the streams API watch toggle and the channel poller.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

from concertpvr.buffer import BufferManager
from concertpvr.db import Database
from concertpvr.models import Recording, Settings
from concertpvr.pool import RecorderPool
from concertpvr.process import AsyncSubprocessRunner
from concertpvr.recorder import RecorderProgress, RecorderWorker
from concertpvr.ws import Broadcaster


def _resolve_cookies_path(db: Database) -> Path | None:
    """Read yt_dlp_cookies_path from settings (singleton). None if unset or empty."""
    with db.session() as s:
        row = s.get(Settings, 1)
        if row is None or not row.yt_dlp_cookies_path:
            return None
        return Path(row.yt_dlp_cookies_path)


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
    cookies_path = _resolve_cookies_path(db)

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
        cookies_path=cookies_path,
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
