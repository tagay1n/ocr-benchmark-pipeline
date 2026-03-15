from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from sqlalchemy import select

from app import config, db, discovery, final_export, layouts, main, ocr_extract, runtime_options
from app.api import shared
from app.config import DEFAULT_EXTENSIONS, Settings


class ApiSharedHelpersTests(unittest.TestCase):
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

    def test_run_discovery_scan_with_events_returns_stable_payload_and_records_events(self) -> None:
        self._write_image("helpers/a.png", b"a")
        payload = shared.run_discovery_scan_with_events(
            trigger="unit",
            started_message="Unit scan started",
            finished_prefix="Unit scan finished.",
        )
        self.assertEqual(payload["scanned_files"], 1)
        self.assertEqual(payload["new_pages"], 1)
        self.assertIn("total_pages", payload)
        self.assertIn("missing_pages", payload)
        self.assertIn("active_duplicate_files", payload)

        with db.get_session() as session:
            events = session.execute(
                select(main.PipelineEvent)
                .order_by(main.PipelineEvent.id.asc())
            ).scalars().all()

        self.assertGreaterEqual(len(events), 2)
        self.assertEqual(str(events[-2].event_type), "scan_started")
        self.assertEqual(str(events[-1].event_type), "scan_finished")
        self.assertIn("Unit scan started", str(events[-2].message))
        self.assertIn("Unit scan finished", str(events[-1].message))

    def test_next_page_for_status_handles_empty_and_no_wraparound(self) -> None:
        self._write_image("helpers/one.png", b"x")
        self._write_image("helpers/two.png", b"y")
        main.scan_images()
        pages = sorted(main.list_pages()["pages"], key=lambda row: int(row["id"]))
        first_id = int(pages[0]["id"])
        second_id = int(pages[1]["id"])

        for page_id in (first_id, second_id):
            main.create_page_layout(
                page_id,
                main.CreateLayoutRequest(
                    class_name="text",
                    reading_order=1,
                    bbox=main.BBoxPayload(x1=0.1, y1=0.1, x2=0.9, y2=0.3),
                ),
            )

        direct = shared.next_page_for_status(status="layout_detected")
        self.assertTrue(direct["has_next"])
        self.assertEqual(direct["next_page_id"], first_id)

        after_last = shared.next_page_for_status(status="layout_detected", current_page_id=second_id)
        self.assertFalse(after_last["has_next"])
        self.assertIsNone(after_last["next_page_id"])

        main.complete_layout_review(first_id)
        main.complete_layout_review(second_id)
        none_left = shared.next_page_for_status(status="layout_detected")
        self.assertFalse(none_left["has_next"])
        self.assertIsNone(none_left["next_page_id"])


if __name__ == "__main__":
    unittest.main()
