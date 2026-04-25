"""SQLAlchemy engine + session factory."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


class Database:
    """Wraps a SQLAlchemy engine + session factory for an app install."""

    def __init__(self, url: str) -> None:
        self.engine: Engine = create_engine(
            url,
            # SQLite + multi-thread (FastAPI threadpool) needs this:
            connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
            future=True,
        )
        self._Session = sessionmaker(self.engine, expire_on_commit=False, future=True)

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Open a session; commit on clean exit, rollback on exception."""
        s = self._Session()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()
