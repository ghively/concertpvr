"""Derive draft segments from chapters or setlist rows."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from concertpvr.models import Recording, Segment, Setlist


def derive_draft_segments_no_flush(recording: Recording, session: Session) -> list[Segment]:
    """Like derive_draft_segments but does not call session.flush().

    Safe to call from within a SQLAlchemy before_flush event listener.
    """
    if recording.raw_chapters_json:
        try:
            chapters = json.loads(recording.raw_chapters_json)
        except (json.JSONDecodeError, TypeError):
            chapters = []
        if chapters:
            return _from_chapters_no_flush(recording, chapters, session)

    setlist_rows = list(session.scalars(
        select(Setlist).where(Setlist.recording_id == recording.id).order_by(Setlist.start_s)
    ))
    if setlist_rows:
        return _from_setlist_no_flush(recording, setlist_rows, session)

    return []


def derive_draft_segments(recording: Recording, session: Session) -> list[Segment]:
    """Generate draft segments from chapters (preferred) or setlist (fallback).

    Returns the persisted Segment rows. Empty list if neither is available.
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


def _from_chapters_no_flush(
    recording: Recording, chapters: list[dict], session: Session
) -> list[Segment]:
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
    return segs


def _from_setlist_no_flush(
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
    return segs
