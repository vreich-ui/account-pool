"""Engine + session management."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .tables import Base


class Database:
    """Owns the SQLAlchemy engine and hands out sessions."""

    def __init__(self, url: str = "sqlite:///./account_pool.db") -> None:
        is_sqlite = url.startswith("sqlite")
        is_memory = is_sqlite and (":memory:" in url or url == "sqlite://")
        kwargs: dict = {"future": True}
        if is_sqlite:
            kwargs["connect_args"] = {"check_same_thread": False}
        if is_memory:
            # Keep a single shared connection so the in-memory DB persists across sessions.
            kwargs["poolclass"] = StaticPool
        self.engine = create_engine(url, **kwargs)
        self._session_factory = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)

    def create_all(self) -> None:
        """Create tables. v1 uses create_all; Alembic migrations come with Postgres."""
        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
