from sqlalchemy import text

from concertpvr.db import Database
from concertpvr.models import Base, Settings


def test_database_connects_and_pings(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'test.db'}")
    with db.session() as s:
        result = s.execute(text("SELECT 1")).scalar_one()
        assert result == 1


def test_database_session_is_transactional(tmp_path):
    """Each session() context manager is its own transaction."""
    db = Database(f"sqlite:///{tmp_path / 'test.db'}")
    with db.session() as s:
        s.execute(text("CREATE TABLE t (x INTEGER)"))
        s.execute(text("INSERT INTO t VALUES (1)"))

    with db.session() as s:
        count = s.execute(text("SELECT COUNT(*) FROM t")).scalar_one()
        assert count == 1


def test_settings_model_round_trip(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(db.engine)

    with db.session() as s:
        s.add(Settings(id=1, emby_url="http://emby:8096", folder_pattern="{artist}"))

    with db.session() as s:
        row = s.get(Settings, 1)
        assert row is not None
        assert row.emby_url == "http://emby:8096"
        assert row.folder_pattern == "{artist}"
        assert row.default_quality == "bestvideo*+bestaudio/best"  # default
        assert row.max_concurrent_recordings == 4  # default
