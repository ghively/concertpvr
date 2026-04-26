"""Parse pasted festival lineups into structured setlist entries."""

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
    ^\s*(?P<artist>.+?)\s*[·\-]\s*
    (?P<start>\d{1,2}:\d{2}(?::\d{2})?)\s*
    \s*(?:[–\-]|to)\s*
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
        entries.append(
            ParsedEntry(
                artist=m.group("artist").strip(),
                start_s=_to_seconds(m.group("start")),
                end_s=_to_seconds(m.group("end")),
            )
        )
    return entries
