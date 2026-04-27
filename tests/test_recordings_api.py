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


def _seed(client, n: int) -> int:
    db = client.app.state.db
    with db.session() as s:
        stream = Stream(kind="live", youtube_id=f"a{n}", url="u", title="t", channel_name="c")
        s.add(stream)
        s.flush()
        for i in range(n):
            s.add(
                Recording(
                    stream_id=stream.id,
                    started_at=dt.datetime(2026, 4, 25, 12, i, tzinfo=dt.UTC),
                    path=f"/buf/{i}",
                    is_buffer=True,
                )
            )
        return stream.id


def test_list_recordings_empty(client):
    r = client.get("/api/recordings")
    assert r.status_code == 200
    assert r.json() == []


def test_list_recordings_returns_all_ordered(client):
    _seed(client, 3)
    r = client.get("/api/recordings")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 3
    starts = [row["started_at"] for row in body]
    assert starts == sorted(starts, reverse=True)


def test_list_recordings_filter_by_stream(client):
    sid = _seed(client, 2)
    _seed(client, 1)
    r = client.get(f"/api/recordings?stream_id={sid}")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    assert all(row["stream_id"] == sid for row in body)


def test_get_recording_by_id(client):
    sid = _seed(client, 1)
    listing = client.get(f"/api/recordings?stream_id={sid}").json()
    rid = listing[0]["id"]
    r = client.get(f"/api/recordings/{rid}")
    assert r.status_code == 200
    assert r.json()["id"] == rid


def test_get_recording_404(client):
    r = client.get("/api/recordings/9999")
    assert r.status_code == 404


def test_finalize_recording_captures_chapters_and_creates_segments(client, tmp_path):
    import json

    db = client.app.state.db

    rec_dir = tmp_path / "rec1"
    rec_dir.mkdir()
    (rec_dir / "x.info.json").write_text(
        json.dumps(
            {
                "chapters": [
                    {"title": "Phoebe", "start_time": 0, "end_time": 60},
                    {"title": "Goose", "start_time": 60, "end_time": 120},
                ],
            }
        )
    )

    with db.session() as s:
        from concertpvr.models import Stream

        stream = Stream(kind="live", youtube_id="x", url="u", title="t", channel_name="c")
        s.add(stream)
        s.flush()
        from concertpvr.models import Recording

        rec = Recording(
            stream_id=stream.id,
            started_at=dt.datetime(2026, 4, 25, 12, 0, tzinfo=dt.UTC),
            path=str(rec_dir),
            is_buffer=True,
            status="recording",
        )
        s.add(rec)
        s.flush()
        rid = rec.id

    r = client.post(f"/api/recordings/{rid}/finalize")
    assert r.status_code == 200
    assert r.json()["status"] == "complete"

    segs = client.get(f"/api/segments?recording_id={rid}").json()
    assert len(segs) == 2
    assert {seg["artist"] for seg in segs} == {"Phoebe", "Goose"}


def test_list_recordings_filter_by_status(client):
    from sqlalchemy import select

    sid = _seed(client, 2)
    db = client.app.state.db
    with db.session() as s:
        recs = list(s.scalars(select(Recording).where(Recording.stream_id == sid)))
        recs[0].status = "complete"
    r = client.get("/api/recordings?status=complete")
    assert r.status_code == 200
    assert all(row["status"] == "complete" for row in r.json())


# ---------------------------------------------------------------------------
# Helpers for DELETE /source + retry tests
# ---------------------------------------------------------------------------


def _seed_recording_with_segments(client, *, seg_statuses: list[str], source_deleted: bool = False) -> tuple[int, int]:
    """Seed a recording with segments; returns (recording_id, stream_id)."""
    db = client.app.state.db
    with db.session() as s:
        stream = Stream(kind="live", youtube_id="src-test", url="u", title="t", channel_name="c")
        s.add(stream)
        s.flush()
        rec = Recording(
            stream_id=stream.id,
            started_at=dt.datetime(2026, 4, 26, 12, 0, tzinfo=dt.UTC),
            path="/fake/path",
            is_buffer=False,
            status="complete",
            source_deleted=source_deleted,
        )
        s.add(rec)
        s.flush()
        for i, status in enumerate(seg_statuses):
            s.add(
                Segment(
                    recording_id=rec.id,
                    artist=f"Artist{i}",
                    title=f"Song{i}",
                    start_s=i * 60,
                    end_s=(i + 1) * 60,
                    source="manual",
                    status=status,
                )
            )
        return rec.id, stream.id


# ---------------------------------------------------------------------------
# DELETE /api/recordings/{id}/source
# ---------------------------------------------------------------------------


def test_delete_source_404_for_unknown(client):
    r = client.delete("/api/recordings/9999/source")
    assert r.status_code == 404


def test_delete_source_409_when_no_segments(client):
    db = client.app.state.db
    with db.session() as s:
        stream = Stream(kind="live", youtube_id="no-segs", url="u", title="t", channel_name="c")
        s.add(stream)
        s.flush()
        rec = Recording(
            stream_id=stream.id,
            started_at=dt.datetime(2026, 4, 26, 12, 0, tzinfo=dt.UTC),
            path="/fake/no-segs",
            is_buffer=False,
            status="complete",
        )
        s.add(rec)
        s.flush()
        rid = rec.id

    r = client.delete(f"/api/recordings/{rid}/source")
    assert r.status_code == 409


def test_delete_source_409_when_any_segment_unpublished(client):
    rid, _ = _seed_recording_with_segments(client, seg_statuses=["published", "draft"])
    r = client.delete(f"/api/recordings/{rid}/source")
    assert r.status_code == 409


def test_delete_source_204_when_all_segments_published(client, tmp_path):
    source_file = tmp_path / "recording.mkv"
    source_file.touch()

    db = client.app.state.db
    with db.session() as s:
        stream = Stream(kind="live", youtube_id="pub-all", url="u", title="t", channel_name="c")
        s.add(stream)
        s.flush()
        rec = Recording(
            stream_id=stream.id,
            started_at=dt.datetime(2026, 4, 26, 12, 0, tzinfo=dt.UTC),
            path=str(source_file),
            is_buffer=False,
            status="complete",
        )
        s.add(rec)
        s.flush()
        s.add(
            Segment(
                recording_id=rec.id,
                artist="Artist",
                title="Song",
                start_s=0,
                end_s=60,
                source="manual",
                status="published",
            )
        )
        rid = rec.id

    r = client.delete(f"/api/recordings/{rid}/source")
    assert r.status_code == 204
    assert not source_file.exists()

    with db.session() as s:
        rec = s.get(Recording, rid)
        assert rec is not None
        assert rec.source_deleted is True


def test_delete_source_409_already_deleted(client):
    db = client.app.state.db
    with db.session() as s:
        stream = Stream(kind="live", youtube_id="already-del", url="u", title="t", channel_name="c")
        s.add(stream)
        s.flush()
        rec = Recording(
            stream_id=stream.id,
            started_at=dt.datetime(2026, 4, 26, 12, 0, tzinfo=dt.UTC),
            path="/fake/already",
            is_buffer=False,
            status="complete",
            source_deleted=True,
        )
        s.add(rec)
        s.flush()
        rid = rec.id

    r = client.delete(f"/api/recordings/{rid}/source")
    assert r.status_code == 409
    assert "already deleted" in r.json()["detail"]


# ---------------------------------------------------------------------------
# POST /api/recordings/{id}/retry
# ---------------------------------------------------------------------------


def test_retry_404_for_unknown(client, monkeypatch):
    fake_queue = MagicMock()
    fake_queue.enqueue = AsyncMock()
    fake_queue.stop = AsyncMock()
    monkeypatch.setattr(client.app.state, "vod_queue", fake_queue)

    r = client.post("/api/recordings/9999/retry")
    assert r.status_code == 404


def test_retry_409_when_not_vod_failed(client, monkeypatch):
    fake_queue = MagicMock()
    fake_queue.enqueue = AsyncMock()
    fake_queue.stop = AsyncMock()
    monkeypatch.setattr(client.app.state, "vod_queue", fake_queue)

    db = client.app.state.db
    with db.session() as s:
        stream = Stream(kind="video", youtube_id="retry-no", url="u", title="t", channel_name="c")
        s.add(stream)
        s.flush()
        rec = Recording(
            stream_id=stream.id,
            started_at=dt.datetime(2026, 4, 26, 12, 0, tzinfo=dt.UTC),
            path="/fake/retry",
            is_buffer=False,
            status="complete",
        )
        s.add(rec)
        s.flush()
        rid = rec.id

    r = client.post(f"/api/recordings/{rid}/retry")
    assert r.status_code == 409


def test_retry_requeues_vod_failed(client, monkeypatch):
    fake_queue = MagicMock()
    fake_queue.enqueue = AsyncMock()
    fake_queue.stop = AsyncMock()
    monkeypatch.setattr(client.app.state, "vod_queue", fake_queue)

    db = client.app.state.db
    with db.session() as s:
        stream = Stream(kind="video", youtube_id="retry-yes", url="u", title="t", channel_name="c")
        s.add(stream)
        s.flush()
        rec = Recording(
            stream_id=stream.id,
            started_at=dt.datetime(2026, 4, 26, 12, 0, tzinfo=dt.UTC),
            path="/fake/retry-yes",
            is_buffer=False,
            status="vod_failed",
            error="some error",
        )
        s.add(rec)
        s.flush()
        rid = rec.id

    r = client.post(f"/api/recordings/{rid}/retry")
    assert r.status_code == 200
    assert r.json() == {"status": "vod_queued"}

    fake_queue.enqueue.assert_awaited_once_with(rid)

    with db.session() as s:
        rec = s.get(Recording, rid)
        assert rec is not None
        assert rec.status == "vod_queued"
        assert rec.error is None
