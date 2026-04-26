from unittest.mock import AsyncMock, MagicMock

import pytest

from concertpvr.buffer import BufferManager
from concertpvr.db import Database
from concertpvr.models import Base, Recording, Stream
from concertpvr.recording_starter import start_buffer_recording
from concertpvr.ws import Broadcaster


@pytest.mark.asyncio
async def test_creates_recording_row_and_calls_pool_start(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'rs.db'}")
    Base.metadata.create_all(db.engine)

    with db.session() as s:
        stream = Stream(
            kind="live",
            youtube_id="x",
            url="https://example.com",
            title="t",
            channel_name="c",
        )
        s.add(stream)
        s.flush()
        sid = stream.id

    fake_pool = MagicMock()
    fake_pool.start = AsyncMock()
    buf = BufferManager(tmp_path / "buf")
    bc = Broadcaster()

    rec_id = await start_buffer_recording(
        stream_id=sid,
        url="https://example.com",
        quality_format="best",
        db=db,
        pool=fake_pool,
        buf=buf,
        bc=bc,
    )

    assert isinstance(rec_id, int)
    fake_pool.start.assert_awaited_once()

    with db.session() as s:
        rec = s.get(Recording, rec_id)
        assert rec is not None
        assert rec.stream_id == sid
        assert rec.is_buffer is True
        assert rec.status == "recording"
