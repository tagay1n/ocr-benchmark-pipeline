from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app import config, db, discovery, final_export, layouts, main, ocr_extract, runtime_options
from app.config import DEFAULT_EXTENSIONS, Settings


class DiscoveryLifecycleTests(unittest.TestCase):
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
        self.stack.enter_context(patch.object(discovery, "settings", self.test_settings))
        self.stack.enter_context(patch.object(final_export, "settings", self.test_settings))
        self.stack.enter_context(patch.object(layouts, "settings", self.test_settings))
        self.stack.enter_context(patch.object(main, "settings", self.test_settings))
        self.stack.enter_context(patch.object(ocr_extract, "settings", self.test_settings))
        self.stack.enter_context(patch.object(runtime_options, "settings", self.test_settings))
        db.init_db()
        runtime_options.reset_runtime_options_from_settings()

    def tearDown(self) -> None:
        self.stack.close()
        self.temp_dir.cleanup()

    def _write_image(self, rel_path: str, content: bytes) -> Path:
        path = self.test_settings.source_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def test_discovery_marks_missing_and_recovers_when_file_returns(self) -> None:
        self._write_image("books/a.png", b"a")
        removed_path = self._write_image("books/b.png", b"b")
        first = main.scan_images()
        self.assertEqual(first["new_pages"], 2)
        self.assertEqual(first["missing_marked"], 0)

        removed_path.unlink()
        second = main.scan_images()
        self.assertEqual(second["missing_marked"], 1)
        pages_after_remove = {row["rel_path"]: bool(row["is_missing"]) for row in main.list_pages()["pages"]}
        self.assertEqual(pages_after_remove["books/a.png"], False)
        self.assertEqual(pages_after_remove["books/b.png"], True)

        self._write_image("books/b.png", b"b")
        third = main.scan_images()
        self.assertEqual(third["missing_marked"], 0)
        pages_after_restore = {row["rel_path"]: bool(row["is_missing"]) for row in main.list_pages()["pages"]}
        self.assertEqual(pages_after_restore["books/a.png"], False)
        self.assertEqual(pages_after_restore["books/b.png"], False)

    def test_discovery_switches_canonical_rel_path_based_on_remaining_duplicate(self) -> None:
        canonical = self._write_image("dup/a.png", b"same")
        duplicate = self._write_image("dup/z.png", b"same")
        first = main.scan_images()
        self.assertEqual(first["new_pages"], 1)
        self.assertEqual(first["duplicate_files"], 1)
        self.assertEqual(main.list_pages()["pages"][0]["rel_path"], "dup/a.png")

        canonical.unlink()
        second = main.scan_images()
        self.assertEqual(second["updated_pages"], 1)
        self.assertEqual(second["duplicate_files"], 0)
        pages = main.list_pages()["pages"]
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0]["rel_path"], "dup/z.png")
        duplicates = main.list_duplicates()
        self.assertEqual(duplicates["count"], 0)
        self.assertTrue(duplicate.exists())

    def test_discovery_reactivates_duplicate_rows_when_duplicate_reappears(self) -> None:
        self._write_image("x/a.png", b"same")
        duplicate_path = self._write_image("x/copy/a2.png", b"same")
        first = main.scan_images()
        self.assertEqual(first["duplicate_files"], 1)
        first_duplicate = main.list_duplicates()
        self.assertEqual(first_duplicate["count"], 1)
        first_seen = first_duplicate["duplicates"][0]["first_seen_at"]

        duplicate_path.unlink()
        second = main.scan_images()
        self.assertEqual(second["duplicate_files"], 0)
        self.assertEqual(main.list_duplicates()["count"], 0)

        self._write_image("x/copy/a2.png", b"same")
        third = main.scan_images()
        self.assertEqual(third["duplicate_files"], 1)
        restored = main.list_duplicates()
        self.assertEqual(restored["count"], 1)
        self.assertEqual(restored["duplicates"][0]["duplicate_rel_path"], "x/copy/a2.png")
        self.assertEqual(restored["duplicates"][0]["first_seen_at"], first_seen)

    def test_discovery_updates_hash_for_existing_rel_path_without_creating_new_page(self) -> None:
        self._write_image("hash/a.png", b"v1")
        first = main.scan_images()
        self.assertEqual(first["new_pages"], 1)
        pages = main.list_pages()["pages"]
        self.assertEqual(len(pages), 1)
        original_id = int(pages[0]["id"])

        self._write_image("hash/a.png", b"v2")
        second = main.scan_images()
        self.assertEqual(second["new_pages"], 0)
        self.assertEqual(second["updated_pages"], 1)
        pages_after = main.list_pages()["pages"]
        self.assertEqual(len(pages_after), 1)
        self.assertEqual(int(pages_after[0]["id"]), original_id)


if __name__ == "__main__":
    unittest.main()
