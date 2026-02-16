from __future__ import annotations

import sqlite3
from contextlib import contextmanager

from .config import settings


@contextmanager
def get_connection() -> sqlite3.Connection:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(settings.db_path)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_db() -> None:
    with get_connection() as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rel_path TEXT NOT NULL UNIQUE,
                file_hash TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'new',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                is_missing INTEGER NOT NULL DEFAULT 0 CHECK (is_missing IN (0, 1))
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS duplicate_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rel_path TEXT NOT NULL UNIQUE,
                file_hash TEXT NOT NULL,
                canonical_page_id INTEGER NOT NULL,
                active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                FOREIGN KEY(canonical_page_id) REFERENCES pages(id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS layouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                page_id INTEGER NOT NULL,
                class_name TEXT NOT NULL,
                x1 REAL NOT NULL,
                y1 REAL NOT NULL,
                x2 REAL NOT NULL,
                y2 REAL NOT NULL,
                reading_order INTEGER NOT NULL,
                confidence REAL,
                source TEXT NOT NULL DEFAULT 'manual',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(page_id) REFERENCES pages(id) ON DELETE CASCADE
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_pages_status
            ON pages(status)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_duplicate_files_active
            ON duplicate_files(active)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_layouts_page_order
            ON layouts(page_id, reading_order)
            """
        )
