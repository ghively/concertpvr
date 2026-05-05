"""POST /api/segments/bulk-publish — retry multiple failed publishes (v0.4)."""

import datetime as dt
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from concertpvr.main import create_app
from concertpvr.models import Recording, Segment, Stream


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))
    with TestClient(create_app()) as c:
        yield c


def _seed_segments(client, n: int) -> list[int]:
    db = client.app.state.db
    ids = []
    with db.session() as s:
        st = Stream(kind="video", youtube_id="bp1", url="u", title="t", channel_name="c")
        s.add(st)
        s.flush()
        rec = Recording(
            stream_id=st.id,
            started_at=dt.datetime.now(dt.UTC),
            path="/tmp/r",
            status="complete",
            is_buffer=False,
        )
        s.add(rec)
        s.flush()
        for i in range(n):
            seg = Segment(
                recording_id=rec.id,
                artist=f"Artist {i}",
                start_s=i * 10,
                end_s=i * 10 + 5,
                source="manual",
                status="publish_failed",
                error="prior failure",
            )
            s.add(seg)
            s.flush()
            ids.append(seg.id)
    return ids


def test_bulk_publish_all_succeed(client, monkeypatch):
    seg_ids = _seed_segments(client, 3)

    fake_pub = MagicMock()
    fake_pub.publish = AsyncMock(return_value=None)
    monkeypatch.setattr(client.app.state, "publisher_factory", lambda: fake_pub)

    r = client.post("/api/segments/bulk-publish", json={"segment_ids": seg_ids})
    assert r.status_code == 200
    body = r.json()
    assert body["succeeded"] == 3
    assert body["failed"] == 0
    assert {row["status"] for row in body["results"]} == {"published"}
    assert fake_pub.publish.await_count == 3


def test_bulk_publish_continues_past_individual_failures(client, monkeypatch):
    seg_ids = _seed_segments(client, 3)

    fake_pub = MagicMock()
    side_effects = [None, RuntimeError("ffmpeg blew up"), None]
    fake_pub.publish = AsyncMock(side_effect=side_effects)
    monkeypatch.setattr(client.app.state, "publisher_factory", lambda: fake_pub)

    r = client.post("/api/segments/bulk-publish", json={"segment_ids": seg_ids})
    assert r.status_code == 200
    body = r.json()
    assert body["succeeded"] == 2
    assert body["failed"] == 1
    failed_row = next(row for row in body["results"] if row["status"] == "failed")
    assert "ffmpeg" in (failed_row["error"] or "")
    assert fake_pub.publish.await_count == 3


def test_bulk_publish_empty_list_no_op(client):
    r = client.post("/api/segments/bulk-publish", json={"segment_ids": []})
    assert r.status_code == 200
    body = r.json()
    assert body["succeeded"] == 0
    assert body["failed"] == 0
    assert body["results"] == []


def test_bulk_publish_passes_options(client, monkeypatch):
    seg_ids = _seed_segments(client, 1)

    fake_pub = MagicMock()
    fake_pub.publish = AsyncMock(return_value=None)
    monkeypatch.setattr(client.app.state, "publisher_factory", lambda: fake_pub)

    r = client.post(
        "/api/segments/bulk-publish",
        json={
            "segment_ids": seg_ids,
            "festival": "Coachella W2",
            "venue": "Mojave",
            "year": 2026,
        },
    )
    assert r.status_code == 200
    fake_pub.publish.assert_awaited_once_with(
        seg_ids[0], festival="Coachella W2", venue="Mojave", year=2026
    )


def test_bulk_publish_lookup_error_marks_failed(client, monkeypatch):
    """LookupError (segment not found) is captured per-row, not raised."""
    seg_ids = _seed_segments(client, 1)

    fake_pub = MagicMock()
    fake_pub.publish = AsyncMock(side_effect=LookupError("segment 99 not found"))
    monkeypatch.setattr(client.app.state, "publisher_factory", lambda: fake_pub)

    r = client.post("/api/segments/bulk-publish", json={"segment_ids": seg_ids})
    assert r.status_code == 200
    body = r.json()
    assert body["succeeded"] == 0
    assert body["failed"] == 1
    assert "not found" in body["results"][0]["error"]
