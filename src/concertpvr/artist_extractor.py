"""Extract artist name from a YouTube video title via per-watcher regex.

Pure function. Returns the artist string when the regex's named `artist` group
matches and is non-empty; None otherwise. Caller treats None as "manual review
required" — auto-publish path falls through to the post-download review screen.
"""

from __future__ import annotations

import re


def extract_artist(title: str, regex: str | None) -> str | None:
    if not regex or not title:
        return None
    try:
        m = re.search(regex, title)
    except re.error:
        return None
    if m is None:
        return None
    try:
        artist = m.group("artist")
    except (IndexError, KeyError):
        return None
    if artist is None:
        return None
    artist = artist.strip()
    if not artist:
        return None
    return artist
