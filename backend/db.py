"""SQLite engine and session management."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def make_engine(url: str) -> Engine:
    """Create an engine with foreign keys and WAL enabled for SQLite."""
    engine = create_engine(url, future=True)

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record) -> None:  # pragma: no cover - driver hook
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

    return engine


@lru_cache
def get_engine() -> Engine:
    """Return the engine for the configured SQLite file, creating the schema on first use."""
    settings = get_settings()
    path = settings.resolve(settings.sqlite_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = make_engine(f"sqlite:///{path.as_posix()}")
    init_db(engine)
    return engine


def init_db(engine: Engine) -> None:
    """Create all tables that do not exist yet."""
    from backend.knowledge import models  # noqa: F401  (registers tables on Base)

    Base.metadata.create_all(engine)


@contextmanager
def session_scope(engine: Engine | None = None) -> Iterator[Session]:
    """Yield a session that commits on success and rolls back on error."""
    factory = sessionmaker(bind=engine or get_engine(), expire_on_commit=False)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
