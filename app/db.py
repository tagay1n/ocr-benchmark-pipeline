from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Connection
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


def _sqlite_table_exists(connection: Connection, table_name: str) -> bool:
    row = connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = :name",
        {"name": table_name},
    ).first()
    return row is not None


def _sqlite_layouts_table_sql(connection: Connection) -> str:
    row = connection.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'layouts'",
    ).first()
    if row is None or row[0] is None:
        return ""
    return str(row[0])


def _sqlite_has_unique_page_order_constraint(connection: Connection) -> bool:
    index_rows = connection.exec_driver_sql("PRAGMA index_list('layouts')").all()
    for row in index_rows:
        row_values = tuple(row)
        is_unique = bool(row_values[2])
        if not is_unique:
            continue
        index_name = str(row_values[1])
        escaped_name = index_name.replace("'", "''")
        cols = connection.exec_driver_sql(f"PRAGMA index_info('{escaped_name}')").all()
        col_names = [str(col[2]) for col in cols]
        if col_names == ["page_id", "reading_order"]:
            return True
    return False


def _sqlite_has_reading_order_positive_check(connection: Connection) -> bool:
    normalized = _sqlite_layouts_table_sql(connection).lower().replace('"', "").replace("`", "").replace(" ", "")
    return "check(reading_order>=1)" in normalized


def _sqlite_needs_layouts_order_migration(connection: Connection) -> bool:
    if not _sqlite_table_exists(connection, "layouts"):
        return False
    has_unique = _sqlite_has_unique_page_order_constraint(connection)
    has_positive_check = _sqlite_has_reading_order_positive_check(connection)
    return not (has_unique and has_positive_check)


def _sqlite_normalize_layout_reading_orders(connection: Connection) -> None:
    page_rows = connection.exec_driver_sql(
        "SELECT DISTINCT page_id FROM layouts ORDER BY page_id ASC",
    ).all()
    for page_row in page_rows:
        page_id = int(page_row[0])
        layout_rows = connection.exec_driver_sql(
            "SELECT id, reading_order FROM layouts WHERE page_id = :page_id ORDER BY reading_order ASC, id ASC",
            {"page_id": page_id},
        ).all()
        for position, layout_row in enumerate(layout_rows, start=1):
            layout_id = int(layout_row[0])
            reading_order = int(layout_row[1])
            if reading_order == position:
                continue
            connection.exec_driver_sql(
                "UPDATE layouts SET reading_order = :reading_order WHERE id = :layout_id",
                {"reading_order": position, "layout_id": layout_id},
            )


def _migrate_sqlite_layouts_order_constraints(engine: Engine) -> None:
    if engine.dialect.name != "sqlite":
        return

    with engine.connect() as connection:
        if not _sqlite_needs_layouts_order_migration(connection):
            return

        if connection.in_transaction():
            connection.commit()
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF;")
        if connection.in_transaction():
            connection.commit()
        try:
            with connection.begin():
                _sqlite_normalize_layout_reading_orders(connection)
                connection.exec_driver_sql("DROP TABLE IF EXISTS layouts_new;")
                connection.exec_driver_sql(
                    """
                    CREATE TABLE layouts_new (
                      id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                      page_id INTEGER NOT NULL REFERENCES pages (id) ON DELETE CASCADE,
                      class_name VARCHAR NOT NULL,
                      x1 FLOAT NOT NULL,
                      y1 FLOAT NOT NULL,
                      x2 FLOAT NOT NULL,
                      y2 FLOAT NOT NULL,
                      reading_order INTEGER NOT NULL CHECK (reading_order >= 1),
                      confidence FLOAT,
                      source VARCHAR NOT NULL DEFAULT 'manual',
                      created_at VARCHAR NOT NULL,
                      updated_at VARCHAR NOT NULL,
                      CONSTRAINT uq_layouts_page_order UNIQUE (page_id, reading_order)
                    )
                    """
                )
                connection.exec_driver_sql(
                    """
                    INSERT INTO layouts_new (
                      id, page_id, class_name, x1, y1, x2, y2, reading_order, confidence, source, created_at, updated_at
                    )
                    SELECT
                      id, page_id, class_name, x1, y1, x2, y2, reading_order, confidence, source, created_at, updated_at
                    FROM layouts
                    ORDER BY id ASC
                    """
                )
                connection.exec_driver_sql("DROP TABLE layouts;")
                connection.exec_driver_sql("ALTER TABLE layouts_new RENAME TO layouts;")
                connection.exec_driver_sql(
                    "CREATE INDEX IF NOT EXISTS idx_layouts_page_order ON layouts (page_id, reading_order);"
                )
        finally:
            if connection.in_transaction():
                connection.commit()
            connection.exec_driver_sql("PRAGMA foreign_keys=ON;")


def _sqlite_table_has_column(connection: Connection, table_name: str, column_name: str) -> bool:
    rows = connection.exec_driver_sql(f"PRAGMA table_info('{table_name}')").all()
    for row in rows:
        row_values = tuple(row)
        if len(row_values) < 2:
            continue
        if str(row_values[1]) == column_name:
            return True
    return False


def _migrate_sqlite_layout_benchmark_predictions_column(engine: Engine) -> None:
    if engine.dialect.name != "sqlite":
        return

    with engine.connect() as connection:
        if not _sqlite_table_exists(connection, "layout_benchmark_results"):
            return
        if _sqlite_table_has_column(connection, "layout_benchmark_results", "predictions_json"):
            return
        # PRAGMA reads can trigger SQLite autobegin; ensure no active txn before DDL.
        if connection.in_transaction():
            connection.commit()
        connection.exec_driver_sql("ALTER TABLE layout_benchmark_results ADD COLUMN predictions_json TEXT;")
        if connection.in_transaction():
            connection.commit()


def init_db() -> None:
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    _migrate_sqlite_layouts_order_constraints(engine)
    _migrate_sqlite_layout_benchmark_predictions_column(engine)
    # Ensure metadata-defined indexes/constraints are present after migrations.
    Base.metadata.create_all(bind=engine)
