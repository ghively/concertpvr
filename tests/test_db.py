from sqlalchemy import text

from concertpvr.db import Database


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
