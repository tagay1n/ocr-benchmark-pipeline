from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import settings
from .models import Base

_ENGINE: Engine | None = None
_ENGINE_DB_PATH: Path | None = None
_SESSION_FACTORY: sessionmaker[Session] | None = None


def _database_url(db_path: Path) -> str:
    return f"sqlite+pysqlite:///{db_path}"


def _new_engine(db_path: Path) -> Engine:
    engine = create_engine(
        _database_url(db_path),
        future=True,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.close()

    return engine


def get_engine() -> Engine:
    global _ENGINE, _ENGINE_DB_PATH, _SESSION_FACTORY

    db_path = settings.db_path.resolve()
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)

    if _ENGINE is not None and _ENGINE_DB_PATH == db_path and _SESSION_FACTORY is not None:
        return _ENGINE

    if _ENGINE is not None:
        _ENGINE.dispose()

    _ENGINE = _new_engine(db_path)
    _ENGINE_DB_PATH = db_path
    _SESSION_FACTORY = sessionmaker(bind=_ENGINE, autoflush=False, expire_on_commit=False, future=True)
    return _ENGINE


def _get_session_factory() -> sessionmaker[Session]:
    get_engine()
    if _SESSION_FACTORY is None:
        raise RuntimeError("Session factory is not initialized.")
    return _SESSION_FACTORY


@contextmanager
def get_session() -> Session:
    session = _get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
