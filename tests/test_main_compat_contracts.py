from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app import config, db, discovery, final_export, layouts, main, ocr_extract, runtime_options
from app.config import DEFAULT_EXTENSIONS, Settings


class MainCompatibilityContractsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.project_root = Path(self.temp_dir.name)
        self.test_settings = Settings(
            project_root=self.project_root,
            source_dir=self.project_root / "input",
            db_path=self.project_root / "data" / "test.db",
            result_dir=self.project_root / "result",
            allowed_extensions=DEFAULT_EXTENSIONS,
            enable_background_jobs=True,
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

    def _write_image(self, rel_path: str, content: bytes = b"fake-image") -> None:
        path = self.test_settings.source_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def _first_page_id(self) -> int:
        pages = main.list_pages()["pages"]
        self.assertGreaterEqual(len(pages), 1)
        return int(pages[0]["id"])

    def test_scan_images_never_auto_enqueues_layout_detection(self) -> None:
        self._write_image("auto/a.png")

        fake_auto = {"considered": 1, "queued": 1, "already_queued_or_running": 0}
        with patch.object(main, "enqueue_layout_detection_for_new_pages", return_value=fake_auto) as enqueue_mock:
            payload = main.scan_images()

        enqueue_mock.assert_not_called()
        self.assertEqual(
            payload["auto_layout_detection"],
            {"considered": 0, "queued": 0, "already_queued_or_running": 0},
        )

    def test_layout_review_never_auto_enqueues_ocr_job(self) -> None:
        self._write_image("review/a.png")
        main.scan_images()
        page_id = self._first_page_id()
        main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="text",
                reading_order=1,
                bbox=main.BBoxPayload(x1=0.1, y1=0.1, x2=0.9, y2=0.3),
            ),
        )

        with patch.object(main, "enqueue_job", return_value=True) as enqueue_mock:
            result = main.complete_layout_review(page_id)

        self.assertEqual(result["status"], "layout_reviewed")
        enqueue_mock.assert_not_called()

    def test_manual_reextract_uses_main_extract_ocr_for_page_patch(self) -> None:
        self._write_image("ocr/a.png")
        main.scan_images()
        page_id = self._first_page_id()
        main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="text",
                reading_order=1,
                bbox=main.BBoxPayload(x1=0.1, y1=0.1, x2=0.9, y2=0.3),
            ),
        )
        main.complete_layout_review(page_id)

        fake_result = {
            "page_id": page_id,
            "status": "ocr_done",
            "extracted_count": 1,
            "skipped_count": 0,
            "requests_count": 1,
        }
        with patch.object(main, "extract_ocr_for_page", return_value=fake_result) as extract_mock:
            result = main.reextract_ocr(page_id, main.ReextractOcrRequest())

        self.assertEqual(result, fake_result)
        extract_mock.assert_called_once()
        args, kwargs = extract_mock.call_args
        self.assertEqual(args[0], page_id)


if __name__ == "__main__":
    unittest.main()
