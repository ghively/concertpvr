"""Setlist.fm REST client (v0.4.1)."""

import datetime as dt
from typing import Any

import httpx
import pytest

from concertpvr.setlistfm import (
    API_BASE,
    SetlistFmError,
    SetlistFmResult,
    lookup_setlist,
)


def _mock_transport(handler: Any) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_returns_none_when_no_results():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"setlist": []})

    async with httpx.AsyncClient(transport=_mock_transport(handler), base_url="https://x") as c:
        result = await lookup_setlist("Khruangbin", dt.date(2020, 9, 2), api_key="dummy", client=c)
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_on_404():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"code": 404})

    async with httpx.AsyncClient(transport=_mock_transport(handler), base_url="https://x") as c:
        result = await lookup_setlist("Khruangbin", dt.date(2020, 9, 2), api_key="dummy", client=c)
    assert result is None


@pytest.mark.asyncio
async def test_parses_first_setlist_into_songs():
    def handler(request: httpx.Request) -> httpx.Response:
        # Sanity check the API call shape
        assert request.url.path == "/rest/1.0/search/setlists"
        assert request.url.params.get("artistName") == "Khruangbin"
        assert request.url.params.get("date") == "02-09-2020"
        assert request.headers.get("x-api-key") == "dummy"
        return httpx.Response(
            200,
            json={
                "setlist": [
                    {
                        "artist": {"name": "Khruangbin"},
                        "venue": {
                            "name": "NPR HQ",
                            "city": {"name": "Washington"},
                        },
                        "sets": {
                            "set": [
                                {
                                    "song": [
                                        {"name": "First Class"},
                                        {"name": "Pelota"},
                                        {"name": "  "},  # whitespace-only — drop
                                    ]
                                },
                                {
                                    "song": [
                                        {"name": "So We Won't Forget"},
                                    ]
                                },
                            ]
                        },
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=_mock_transport(handler), base_url=API_BASE) as c:
        result = await lookup_setlist("Khruangbin", dt.date(2020, 9, 2), api_key="dummy", client=c)
    assert result is not None
    assert isinstance(result, SetlistFmResult)
    assert result.artist == "Khruangbin"
    assert result.venue == "NPR HQ"
    assert result.city == "Washington"
    assert [s.title for s in result.songs] == ["First Class", "Pelota", "So We Won't Forget"]


@pytest.mark.asyncio
async def test_raises_on_5xx():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream busy")

    with pytest.raises(SetlistFmError) as exc:
        async with httpx.AsyncClient(transport=_mock_transport(handler), base_url=API_BASE) as c:
            await lookup_setlist("Khruangbin", dt.date(2020, 9, 2), api_key="dummy", client=c)
    assert "503" in str(exc.value)


@pytest.mark.asyncio
async def test_raises_when_api_key_empty():
    with pytest.raises(SetlistFmError) as exc:
        await lookup_setlist("Khruangbin", dt.date(2020, 9, 2), api_key="")
    assert "api key" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_returns_none_for_empty_artist():
    result = await lookup_setlist("", dt.date(2020, 9, 2), api_key="dummy")
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_when_setlist_has_no_songs():
    """Setlist.fm can return a setlist entry with empty `sets` (encore-only data)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"setlist": [{"artist": {"name": "X"}, "venue": {}, "sets": {"set": []}}]},
        )

    async with httpx.AsyncClient(transport=_mock_transport(handler), base_url=API_BASE) as c:
        result = await lookup_setlist("X", dt.date(2020, 1, 1), api_key="dummy", client=c)
    assert result is None
