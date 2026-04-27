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

from concertpvr.db import Database
from concertpvr.deps import get_db
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
    db: Database = Depends(get_db),  # noqa: B008
) -> PlaylistIngestResponse:
    cookies_path = _resolve_cookies_path(db)
    try:
        info = await expand_playlist(body.url, cookies_path=cookies_path)
    except ProbeError as e:
        raise HTTPException(400, str(e)) from e

    youtube_ids = [e.youtube_id for e in info.entries]
    with db.session() as s:
        existing = {
            row.youtube_id
            for row in s.scalars(select(Stream).where(Stream.youtube_id.in_(youtube_ids)))
        }

    items = [
        PlaylistIngestItem(
            youtube_id=e.youtube_id,
            title=e.title,
            channel_name=e.channel_name,
            thumbnail_url=e.thumbnail_url,
            duration_s=e.duration_s,
            upload_date=e.upload_date,  # type: ignore[arg-type]
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
    db: Database = Depends(get_db),  # noqa: B008
) -> dict[str, list[int]]:
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
