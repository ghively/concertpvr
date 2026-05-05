"""Setlist.fm REST client — search for a setlist by artist + date.

Setlist.fm requires a free API key registered at https://api.setlist.fm/docs/.
Without a key, callers should skip this tier entirely (the lookup function
will fail loudly if invoked without one — caller's responsibility to gate).

API contract used here:
- GET https://api.setlist.fm/rest/1.0/search/setlists
  ?artistName=<name>&date=<dd-MM-yyyy>
  Headers: x-api-key, Accept: application/json
  Returns: { itemsPerPage, page, total, setlist: [...] }

We don't paginate; the first page is enough for a same-day setlist lookup.
The shape returned to the caller is a normalized list of song titles. Times
aren't on setlist.fm — caller pairs them with chapter timestamps if they
want a timed setlist (typical use: surface as a manual-paste suggestion).
"""

from __future__ import annotations

import datetime as _dt
import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

API_BASE = "https://api.setlist.fm/rest/1.0"


class SetlistFmError(Exception):
    """Lookup failed (network error, 4xx, 5xx, or malformed response)."""


@dataclass(frozen=True)
class SetlistFmEntry:
    title: str


@dataclass(frozen=True)
class SetlistFmResult:
    artist: str
    venue: str | None
    city: str | None
    date: _dt.date
    songs: list[SetlistFmEntry]


def _format_date(d: _dt.date) -> str:
    """Setlist.fm's API uses dd-MM-yyyy, not ISO."""
    return d.strftime("%d-%m-%Y")


async def lookup_setlist(
    artist: str,
    date: _dt.date,
    *,
    api_key: str,
    client: httpx.AsyncClient | None = None,
) -> SetlistFmResult | None:
    """Find a setlist for `artist` on `date`. Returns None if no match.

    Raises `SetlistFmError` on transport / HTTP failures (4xx/5xx). Callers
    should generally treat exceptions as "no setlist found this way" and fall
    through to the next detection tier.
    """
    if not api_key:
        raise SetlistFmError("setlist.fm api key not configured")
    if not artist:
        return None

    url = f"{API_BASE}/search/setlists"
    params = {"artistName": artist, "date": _format_date(date)}
    headers = {"x-api-key": api_key, "Accept": "application/json"}

    try:
        if client is None:
            async with httpx.AsyncClient(timeout=10.0) as c:
                resp = await c.get(url, params=params, headers=headers)
        else:
            resp = await client.get(url, params=params, headers=headers)
    except httpx.HTTPError as e:
        raise SetlistFmError(f"network error: {e}") from e

    if resp.status_code == 404:
        # Setlist.fm returns 404 for "no results" on some queries.
        return None
    if resp.status_code >= 400:
        raise SetlistFmError(f"http {resp.status_code}: {resp.text[:200]}")

    try:
        data = resp.json()
    except ValueError as e:
        raise SetlistFmError(f"malformed json: {e}") from e

    items = data.get("setlist") or []
    if not items:
        return None

    # Pick the first hit; setlist.fm returns most-recent-first when multiple
    # match. For a date-bounded query that's almost always exactly one.
    item = items[0]
    artist_obj = item.get("artist") or {}
    venue_obj = item.get("venue") or {}
    city_obj = venue_obj.get("city") or {}

    songs: list[SetlistFmEntry] = []
    sets = item.get("sets") or {}
    for seg in sets.get("set") or []:
        for song in seg.get("song") or []:
            name = song.get("name")
            if isinstance(name, str) and name.strip():
                songs.append(SetlistFmEntry(title=name.strip()))

    if not songs:
        return None

    return SetlistFmResult(
        artist=str(artist_obj.get("name") or artist),
        venue=str(venue_obj.get("name")) if venue_obj.get("name") else None,
        city=str(city_obj.get("name")) if city_obj.get("name") else None,
        date=date,
        songs=songs,
    )
