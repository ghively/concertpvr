import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

from concertpvr.main import create_app
from concertpvr.playlist_ingest import PlaylistEntry, PlaylistInfo
from concertpvr.ytdlp import StreamInfo


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))
    with TestClient(create_app()) as c:
        yield c


def test_ingest_returns_playlist_with_items(client):
    fake_info = PlaylistInfo(
        playlist_id="PL123",
        playlist_title="Best of KEXP 2025",
        count=2,
        entries=[
            PlaylistEntry(youtube_id="a", title="Song A", url="https://a", channel_name="KEXP",
                          thumbnail_url=None, duration_s=300, upload_date=None),
            PlaylistEntry(youtube_id="b", title="Song B", url="https://b", channel_name="KEXP",
                          thumbnail_url=None, duration_s=240, upload_date=None),
        ],
    )

    async def _fake_expand(_url, **_kw):
        return fake_info

    with patch("concertpvr.api.playlists.expand_playlist", side_effect=_fake_expand):
        r = client.post("/api/playlists/ingest", json={"url": "https://www.youtube.com/playlist?list=PL123"})
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "playlist"
    assert body["count"] == 2
    assert len(body["items"]) == 2
    assert body["items"][0]["youtube_id"] == "a"
    assert body["items"][0]["is_already_known"] is False


def test_confirm_creates_streams_and_queues(client, monkeypatch):
    info_a = StreamInfo(youtube_id="a", url="https://a", title="A", channel_name="K",
                       is_live=False, thumbnail_url=None)
    info_b = StreamInfo(youtube_id="b", url="https://b", title="B", channel_name="K",
                       is_live=False, thumbnail_url=None)

    async def _probe(url, **_kw):
        return {"https://www.youtube.com/watch?v=a": info_a,
                "https://www.youtube.com/watch?v=b": info_b}[url]

    fake_queue = MagicMock()
    fake_queue.enqueue = AsyncMock()
    fake_queue.stop = AsyncMock()
    monkeypatch.setattr(client.app.state, "vod_queue", fake_queue)

    with patch("concertpvr.api.playlists.probe", side_effect=_probe):
        r = client.post("/api/playlists/ingest/confirm", json={"video_ids": ["a", "b"]})
    assert r.status_code == 201
    body = r.json()
    assert len(body["queued_recording_ids"]) == 2
    assert fake_queue.enqueue.await_count == 2
