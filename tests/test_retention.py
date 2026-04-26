import asyncio
import os
import time

import pytest
from fastapi.testclient import TestClient

from concertpvr.main import create_app
from concertpvr.models import Stream, WatchSubscription


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))
    with TestClient(create_app()) as c:
        yield c


def test_prune_job_is_registered(client):
    sched = client.app.state.scheduler
    job_ids = {j.id for j in sched.get_jobs()}
    assert "buffer_retention_prune" in job_ids


def test_prune_job_actually_prunes(client):
    db = client.app.state.db
    buf = client.app.state.buffer

    with db.session() as s:
        stream = Stream(kind="live", youtube_id="x", url="u", title="t", channel_name="c")
        stream.subscription = WatchSubscription(retention_days=7)
        s.add(stream)
        s.flush()
        sid = stream.id

    d = buf.stream_dir(sid)
    old = d / "old.ts"
    fresh = d / "fresh.ts"
    old.write_bytes(b"o" * 100)
    fresh.write_bytes(b"f" * 100)
    eight_days_ago = time.time() - 8 * 86400
    os.utime(old, (eight_days_ago, eight_days_ago))

    sched = client.app.state.scheduler
    job = sched.get_job("buffer_retention_prune")
    assert job is not None
    asyncio.run(job.func())

    assert not old.exists()
    assert fresh.exists()
