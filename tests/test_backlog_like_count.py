"""Like count + most_liked sort (v0.4.1)."""

from unittest.mock import patch

import pytest

from concertpvr.backlog_cache import fetch_full_channel_with_views
from concertpvr.db import Database
from concertpvr.models import Base, ChannelBacklogCache, ChannelWatcher
from concertpvr.ytdlp_channels import ProbeResult


@pytest.fixture
def db(tmp_path):
    d = Database(f"sqlite:///{tmp_path / 'c.db'}")
    Base.metadata.create_all(d.engine)
    return d


def _seed_watcher(db: Database) -> int:
    with db.session() as s:
        w = ChannelWatcher(channel_url="https://youtube.com/@likes", channel_name="Likes")
        s.add(w)
        s.flush()
        return w.id


@pytest.mark.asyncio
async def test_slow_refresh_populates_like_count(db):
    watcher_id = _seed_watcher(db)

    async def fake_probe(yid, **kwargs):
        likes = {"a": 100, "b": 5000, "c": None}
        views = {"a": 1000, "b": 50_000, "c": 200}
        return ProbeResult(youtube_id=yid, view_count=views.get(yid), like_count=likes.get(yid))

    async def mock_flat_impl(d, wid):
        with d.session() as s:
            cache = ChannelBacklogCache(
                watcher_id=wid,
                status="complete",
                items_json=[
                    {"youtube_id": "a"},
                    {"youtube_id": "b"},
                    {"youtube_id": "c"},
                ],
            )
            s.add(cache)
        return 3

    with (
        patch("concertpvr.backlog_cache.fetch_full_channel", side_effect=mock_flat_impl),
        patch("concertpvr.ytdlp_channels.probe_video_metadata", side_effect=fake_probe),
    ):
        await fetch_full_channel_with_views(db, watcher_id)

    with db.session() as s:
        cache = s.get(ChannelBacklogCache, watcher_id)
        assert cache is not None
        items = cache.items_json
        assert items[0]["like_count"] == 100
        assert items[1]["like_count"] == 5000
        assert items[2]["like_count"] is None
        # And view counts still work alongside.
        assert items[0]["view_count"] == 1000
        assert items[1]["view_count"] == 50_000


@pytest.mark.asyncio
async def test_most_liked_sort(db, tmp_path, monkeypatch):
    """End-to-end: GET /backlog?sort=most_liked orders by like_count desc."""
    from fastapi.testclient import TestClient

    from concertpvr.main import create_app

    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))
    with TestClient(create_app()) as c:
        # Seed cache with mixed like counts
        cdb = c.app.state.db
        with cdb.session() as s:
            w = ChannelWatcher(channel_url="https://youtube.com/@l2", channel_name="L2")
            s.add(w)
            s.flush()
            wid = w.id
            cache = ChannelBacklogCache(
                watcher_id=wid,
                status="complete",
                items_json=[
                    {
                        "youtube_id": "low",
                        "title": "low likes",
                        "url": "https://yt/low",
                        "view_count": 100,
                        "like_count": 10,
                        "duration_s": 100,
                    },
                    {
                        "youtube_id": "high",
                        "title": "high likes",
                        "url": "https://yt/high",
                        "view_count": 100,
                        "like_count": 1000,
                        "duration_s": 100,
                    },
                    {
                        "youtube_id": "no_likes",
                        "title": "no likes",
                        "url": "https://yt/no_likes",
                        "view_count": 100,
                        "like_count": None,
                        "duration_s": 100,
                    },
                ],
            )
            s.add(cache)

        r = c.get(f"/api/channel-watchers/{wid}/backlog?sort=most_liked")
        assert r.status_code == 200
        body = r.json()
        # high → low → no_likes (None sorts last)
        assert [it["youtube_id"] for it in body] == ["high", "low", "no_likes"]
