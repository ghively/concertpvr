import datetime as _dt

import pytest

from concertpvr.db import Database
from concertpvr.models import Base, Recording, Stream
from concertpvr.vod_recovery import mark_vod_downloads_interrupted_on_startup


@pytest.fixture
def db(tmp_path):
    d = Database(f"sqlite:///{tmp_path / 'r.db'}")
    Base.metadata.create_all(d.engine)
    return d


def test_vod_downloading_rows_become_vod_queued(db):
    with db.session() as s:
        st = Stream(kind="video", youtube_id="x", url="u", title="t", channel_name="c")
        s.add(st)
        s.flush()
        s.add_all([
            Recording(stream_id=st.id, started_at=_dt.datetime.now(_dt.UTC),
                      path="/tmp/a", status="vod_downloading", is_buffer=False),
            Recording(stream_id=st.id, started_at=_dt.datetime.now(_dt.UTC),
                      path="/tmp/b", status="vod_queued", is_buffer=False),
            Recording(stream_id=st.id, started_at=_dt.datetime.now(_dt.UTC),
                      path="/tmp/c", status="complete", is_buffer=False),
        ])

    count = mark_vod_downloads_interrupted_on_startup(db)
    assert count == 1

    with db.session() as s:
        from sqlalchemy import select
        statuses = sorted(r.status for r in s.scalars(select(Recording)))
        # one was vod_downloading → vod_queued. The original vod_queued stays.
        assert statuses == ["complete", "vod_queued", "vod_queued"]
