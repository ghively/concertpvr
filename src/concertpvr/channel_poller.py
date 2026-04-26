"""Periodic channel poller — APScheduler job target."""

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
        return pattern.lower() in title.lower()


def _ensure_stream(db: Database, broadcast: BroadcastInfo) -> int:
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
    with db.session() as s:
        enabled = list(s.scalars(select(ChannelWatcher).where(ChannelWatcher.enabled == True)))  # noqa: E712
        watcher_data = [
            (w.id, w.channel_url, w.title_filter, w.quality_cap, w.last_live_id) for w in enabled
        ]

    for w_id, channel_url, title_filter, quality_cap, last_live_id in watcher_data:
        try:
            broadcasts = await fetch_channel_live_broadcasts(channel_url)
        except Exception as e:  # noqa: BLE001
            logger.warning("watcher %s: fetch failed: %s", w_id, e)
            broadcasts = []

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
                    db=db,
                    pool=pool,
                    buf=buf,
                    bc=bc,
                )
                triggered_id = b.youtube_id
                break
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "watcher %s: failed to start recording for %s: %s", w_id, b.youtube_id, e
                )

        with db.session() as s:
            w = s.get(ChannelWatcher, w_id)
            if w is not None:
                w.last_polled = _dt.datetime.now(_dt.UTC)
                if triggered_id is not None:
                    w.last_live_id = triggered_id
