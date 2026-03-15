from __future__ import annotations

from contextlib import ExitStack
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app import config, db
from app.config import DEFAULT_EXTENSIONS, Settings


class DbMigrationsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.project_root = Path(self.temp_dir.name)
        self.test_settings = Settings(
            project_root=self.project_root,
            source_dir=self.project_root / "input",
            db_path=self.project_root / "data" / "test.db",
            result_dir=self.project_root / "result",
            allowed_extensions=DEFAULT_EXTENSIONS,
            enable_background_jobs=False,
        )
        self.test_settings.source_dir.mkdir(parents=True, exist_ok=True)

        self.stack = ExitStack()
        self.stack.enter_context(patch.object(config, "settings", self.test_settings))
        self.stack.enter_context(patch.object(db, "settings", self.test_settings))

    def tearDown(self) -> None:
        self.stack.close()
        self.temp_dir.cleanup()

    def test_init_db_migrates_layout_order_constraints_and_normalizes_legacy_orders(self) -> None:
        db_path = self.test_settings.db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)

        connection = sqlite3.connect(db_path)
        try:
            connection.execute("PRAGMA foreign_keys=ON;")
            connection.execute(
                """
                CREATE TABLE pages (
                  id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                  rel_path VARCHAR NOT NULL UNIQUE,
                  file_hash VARCHAR NOT NULL UNIQUE,
                  status VARCHAR NOT NULL,
                  created_at VARCHAR NOT NULL,
                  updated_at VARCHAR NOT NULL,
                  last_seen_at VARCHAR NOT NULL,
                  is_missing BOOLEAN NOT NULL DEFAULT 0
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE layouts (
                  id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                  page_id INTEGER NOT NULL REFERENCES pages (id) ON DELETE CASCADE,
                  class_name VARCHAR NOT NULL,
                  x1 FLOAT NOT NULL,
                  y1 FLOAT NOT NULL,
                  x2 FLOAT NOT NULL,
                  y2 FLOAT NOT NULL,
                  reading_order INTEGER NOT NULL,
                  confidence FLOAT,
                  source VARCHAR NOT NULL DEFAULT 'manual',
                  created_at VARCHAR NOT NULL,
                  updated_at VARCHAR NOT NULL
                )
                """
            )
            connection.execute("CREATE INDEX idx_layouts_page_order ON layouts (page_id, reading_order)")

            now = "2026-03-09T00:00:00+00:00"
            connection.execute(
                """
                INSERT INTO pages (rel_path, file_hash, status, created_at, updated_at, last_seen_at, is_missing)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                ("legacy/a.png", "hash-a", "new", now, now, now, 0),
            )
            page_id = int(connection.execute("SELECT id FROM pages").fetchone()[0])

            # Legacy bad orders: duplicates and non-positive values.
            connection.execute(
                """
                INSERT INTO layouts (page_id, class_name, x1, y1, x2, y2, reading_order, confidence, source, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (page_id, "text", 0.1, 0.1, 0.2, 0.2, 0, 0.9, "legacy", now, now),
            )
            connection.execute(
                """
                INSERT INTO layouts (page_id, class_name, x1, y1, x2, y2, reading_order, confidence, source, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (page_id, "text", 0.2, 0.2, 0.3, 0.3, 0, 0.8, "legacy", now, now),
            )
            connection.commit()
        finally:
            connection.close()

        db.init_db()

        with sqlite3.connect(db_path) as verify:
            table_sql = str(
                verify.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='layouts'").fetchone()[0]
            ).lower().replace(" ", "")
            self.assertIn("check(reading_order>=1)", table_sql)
            self.assertIn("unique(page_id,reading_order)", table_sql)

            page_table_sql = str(
                verify.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='pages'").fetchone()[0]
            ).lower().replace(" ", "")
            self.assertIn("layout_order_mode", page_table_sql)
            page_mode = str(
                verify.execute("SELECT layout_order_mode FROM pages WHERE id = ?", (page_id,)).fetchone()[0]
            )
            self.assertEqual(page_mode, "auto")

            orders = [
                int(row[0])
                for row in verify.execute(
                    "SELECT reading_order FROM layouts WHERE page_id = ? ORDER BY id ASC",
                    (page_id,),
                ).fetchall()
            ]
            self.assertEqual(orders, [1, 2])

            # UNIQUE(page_id, reading_order) must be enforced post-migration.
            with self.assertRaises(sqlite3.IntegrityError):
                verify.execute(
                    """
                    INSERT INTO layouts (
                      page_id, class_name, x1, y1, x2, y2, reading_order, confidence, source, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (page_id, "text", 0.3, 0.3, 0.4, 0.4, 2, 0.7, "legacy", "n", "n"),
                )
                verify.commit()


if __name__ == "__main__":
    unittest.main()
