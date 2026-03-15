from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app import config, db, discovery, final_export, layouts, main, ocr_extract, runtime_options
from app.config import DEFAULT_EXTENSIONS, Settings


class PagesPaginationApiTests(unittest.TestCase):
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

    def _write_image(self, rel_path: str, content: bytes = b"img") -> None:
        path = self.test_settings.source_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def test_list_pages_supports_keyset_cursor_pagination(self) -> None:
        for idx in range(1, 6):
            self._write_image(f"pagination/{idx:02d}.png", f"img-{idx}".encode("utf-8"))
        main.scan_images()

        first = main.list_pages(limit=2, sort="id", direction="asc")
        self.assertEqual(first["count"], 2)
        self.assertEqual(first["total_count"], 5)
        self.assertTrue(first["has_more"])
        self.assertEqual(first["sort"], "id")
        self.assertEqual(first["direction"], "asc")
        first_ids = [int(page["id"]) for page in first["pages"]]
        self.assertEqual(first_ids, [1, 2])
        self.assertEqual(first["pages"][0]["layout_order_mode"], "auto")
        self.assertTrue(first["next_cursor"])

        second = main.list_pages(limit=2, sort="id", direction="asc", cursor=first["next_cursor"])
        self.assertEqual(second["count"], 2)
        self.assertTrue(second["has_more"])
        second_ids = [int(page["id"]) for page in second["pages"]]
        self.assertEqual(second_ids, [3, 4])
        self.assertTrue(second["next_cursor"])

        third = main.list_pages(limit=2, sort="id", direction="asc", cursor=second["next_cursor"])
        self.assertEqual(third["count"], 1)
        self.assertFalse(third["has_more"])
        third_ids = [int(page["id"]) for page in third["pages"]]
        self.assertEqual(third_ids, [5])
        self.assertIsNone(third["next_cursor"])

    def test_list_pages_requires_limit_when_cursor_provided(self) -> None:
        with self.assertRaises(main.HTTPException) as error:
            main.list_pages(cursor="abc")
        self.assertEqual(error.exception.status_code, 400)
        self.assertIn("cursor requires a limit", str(error.exception.detail).lower())

    def test_list_pages_rejects_invalid_cursor(self) -> None:
        with self.assertRaises(main.HTTPException) as error:
            main.list_pages(limit=20, sort="id", direction="asc", cursor="bad-cursor")
        self.assertEqual(error.exception.status_code, 400)
        self.assertIn("invalid cursor", str(error.exception.detail).lower())

    def test_list_pages_rejects_cursor_sort_mismatch(self) -> None:
        for idx in range(1, 4):
            self._write_image(f"pagination/mismatch-{idx}.png", f"img-{idx}".encode("utf-8"))
        main.scan_images()

        first = main.list_pages(limit=2, sort="id", direction="asc")
        with self.assertRaises(main.HTTPException) as error:
            main.list_pages(limit=2, sort="created_at", direction="desc", cursor=first["next_cursor"])
        self.assertEqual(error.exception.status_code, 400)
        self.assertIn("cursor does not match", str(error.exception.detail).lower())

    def test_pages_summary_reports_non_missing_status_counts(self) -> None:
        self._write_image("summary/a.png", b"a")
        self._write_image("summary/b.png", b"b")
        self._write_image("summary/c.png", b"c")
        main.scan_images()

        c_path = self.test_settings.source_dir / "summary/c.png"
        c_path.unlink()
        main.scan_images()
        pages_after = sorted(main.list_pages()["pages"], key=lambda row: int(row["id"]))
        non_missing_ids = [int(page["id"]) for page in pages_after if not bool(page["is_missing"])]
        self.assertEqual(len(non_missing_ids), 2)

        with db.get_session() as session:
            first = session.get(main.Page, non_missing_ids[0])
            second = session.get(main.Page, non_missing_ids[1])
            self.assertIsNotNone(first)
            self.assertIsNotNone(second)
            first.status = "OCR_REVIEWED"
            second.status = "LAYOUT_DETECTED"
            first.updated_at = main._utc_now()
            second.updated_at = main._utc_now()

        summary = main.pages_summary()
        self.assertEqual(summary["total_pages"], 2)
        self.assertEqual(summary["missing_pages"], 1)
        by_status = summary["by_status"]
        ocr_reviewed = by_status.get("ocr_reviewed", by_status.get("OCR_REVIEWED", 0))
        layout_detected = by_status.get("layout_detected", by_status.get("LAYOUT_DETECTED", 0))
        self.assertEqual(ocr_reviewed, 1)
        self.assertEqual(layout_detected, 1)


if __name__ == "__main__":
    unittest.main()
