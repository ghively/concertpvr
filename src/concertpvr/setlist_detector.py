"""Detect setlists in VOD description, chapters, and comments.

Pure functions; no I/O. Caller passes already-fetched data; we parse and return
DetectedSetlist (or None). Used by the VOD probe pipeline to enrich Stream
metadata for the post-download review screen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

SetlistSource = Literal["chapters", "description", "comments"]


@dataclass(frozen=True)
class SetlistEntry:
    start_s: int
    title: str


@dataclass(frozen=True)
class DetectedSetlist:
    entries: list[SetlistEntry]
    source: SetlistSource
    raw_text: str


_TS_LINE = re.compile(
    r"""
    ^[\s]*
    \[?
    (?P<h>\d{1,2}):
    (?P<m>\d{1,2})
    (?::(?P<s>\d{1,2}))?
    \]?
    [\s\-–—•·.]+
    (?P<title>.{1,200}?)
    \s*$
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
        return hh * 60 + mm
    return hh * 3600 + mm * 60 + ss


def _extract_entries(text: str) -> list[SetlistEntry]:
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
    if not entries:
        return []
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
    if len(block) < 2:
        return None
    return DetectedSetlist(
        entries=block,
        source="description",
        raw_text=description[:2000],
    )


def detect_in_chapters(chapters: list[dict[str, Any]] | None) -> DetectedSetlist | None:
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
        raw_text="",
    )


def detect_in_comments(comments: list[dict[str, Any]] | None) -> DetectedSetlist | None:
    if not comments:
        return None
    pinned = [c for c in comments if c.get("is_pinned")]
    candidates = pinned + sorted(
        [c for c in comments if not c.get("is_pinned")],
        key=lambda c: -(c.get("like_count") or 0),
    )
    for c in candidates[:20]:
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
