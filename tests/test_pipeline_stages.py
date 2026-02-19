from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app import config, db, discovery, layouts, main
from app.config import DEFAULT_EXTENSIONS, Settings


class PipelineStagesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.project_root = Path(self.temp_dir.name)
        self.test_settings = Settings(
            project_root=self.project_root,
            source_dir=self.project_root / "input",
            db_path=self.project_root / "data" / "test.db",
            allowed_extensions=DEFAULT_EXTENSIONS,
            enable_background_jobs=False,
        )
        self.test_settings.source_dir.mkdir(parents=True, exist_ok=True)

        self.stack = ExitStack()
        self.stack.enter_context(patch.object(config, "settings", self.test_settings))
        self.stack.enter_context(patch.object(db, "settings", self.test_settings))
        self.stack.enter_context(patch.object(discovery, "settings", self.test_settings))
        self.stack.enter_context(patch.object(layouts, "settings", self.test_settings))
        self.stack.enter_context(patch.object(main, "settings", self.test_settings))
        db.init_db()

    def tearDown(self) -> None:
        self.stack.close()
        self.temp_dir.cleanup()

    def _write_image(self, rel_path: str, content: bytes) -> None:
        path = self.test_settings.source_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def _first_page_id(self) -> int:
        pages_payload = main.list_pages()
        self.assertGreaterEqual(pages_payload["count"], 1)
        return int(pages_payload["pages"][0]["id"])

    def test_discovery_scan_stage_tracks_duplicates(self) -> None:
        self._write_image("a.png", b"same-content")
        self._write_image("dup/a-copy.png", b"same-content")
        self._write_image("b.jpg", b"other-content")

        scan = main.scan_images()

        self.assertEqual(scan["scanned_files"], 3)
        self.assertEqual(scan["new_pages"], 2)
        self.assertEqual(scan["duplicate_files"], 1)
        self.assertEqual(scan["missing_marked"], 0)
        self.assertEqual(
            scan["auto_layout_detection"],
            {"considered": 0, "queued": 0, "already_queued_or_running": 0},
        )

        pages_payload = main.list_pages()
        self.assertEqual(pages_payload["count"], 2)
        self.assertEqual({page["rel_path"] for page in pages_payload["pages"]}, {"a.png", "b.jpg"})

        duplicates_payload = main.list_duplicates()
        self.assertEqual(duplicates_payload["count"], 1)
        duplicate = duplicates_payload["duplicates"][0]
        self.assertEqual(duplicate["duplicate_rel_path"], "dup/a-copy.png")
        self.assertEqual(duplicate["canonical_rel_path"], "a.png")

    def test_layout_detection_stage_creates_layouts(self) -> None:
        self._write_image("page.png", b"fake-image")
        main.scan_images()
        page_id = self._first_page_id()

        fake_rows = [
            {
                "class_name": "text",
                "confidence": 0.91,
                "x1": 0.1,
                "y1": 0.2,
                "x2": 0.8,
                "y2": 0.9,
            }
        ]
        fake_thresholds = {"confidence_threshold": 0.3, "iou_threshold": 0.5}

        with patch.object(layouts, "_detect_doclaynet_layouts", return_value=(fake_rows, fake_thresholds)):
            result = main.detect_page_layouts(
                page_id,
                main.DetectLayoutsRequest(
                    replace_existing=True,
                    confidence_threshold=0.3,
                    iou_threshold=0.5,
                ),
            )

        self.assertEqual(result["created"], 1)
        self.assertEqual(result["thresholds"], fake_thresholds)
        self.assertEqual(result["class_counts"], {"text": 1})

        layouts_payload = main.page_layouts(page_id)
        self.assertEqual(layouts_payload["count"], 1)
        self.assertEqual(layouts_payload["layouts"][0]["class_name"], "text")

        page_payload = main.page_details(page_id)
        self.assertEqual(page_payload["page"]["status"], "layout_detected")

    def test_layout_review_stage_marks_page_reviewed(self) -> None:
        self._write_image("review.png", b"review-image")
        main.scan_images()
        page_id = self._first_page_id()

        main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="text",
                reading_order=None,
                bbox=main.BBoxPayload(x1=0.1, y1=0.1, x2=0.9, y2=0.25),
            ),
        )

        result = main.complete_layout_review(page_id)

        self.assertEqual(result["status"], "layout_reviewed")
        self.assertEqual(result["layout_count"], 1)

        page_payload = main.page_details(page_id)
        self.assertEqual(page_payload["page"]["status"], "layout_reviewed")

    def test_pipeline_activity_endpoint_shape(self) -> None:
        self._write_image("activity.png", b"activity")
        main.scan_images()
        payload = main.pipeline_activity(limit=5)
        self.assertIn("worker_running", payload)
        self.assertIn("in_progress", payload)
        self.assertIn("queued", payload)
        self.assertIn("recent_events", payload)
        self.assertIn("registered_stages", payload)
        self.assertIn("layout_detect", payload["registered_stages"])
        start_events = [event for event in payload["recent_events"] if event.get("event_type") == "scan_started"]
        self.assertGreaterEqual(len(start_events), 1)
        start_event = start_events[-1]
        self.assertIn("Discovery scan started", start_event["message"])
        self.assertIn(str(self.test_settings.source_dir), start_event["message"])
        self.assertEqual(start_event["data"]["source_dir"], str(self.test_settings.source_dir))
        self.assertEqual(start_event["data"]["allowed_extensions"], list(self.test_settings.allowed_extensions))

        finished_events = [event for event in payload["recent_events"] if event.get("event_type") == "scan_finished"]
        self.assertGreaterEqual(len(finished_events), 1)
        finished_event = finished_events[-1]
        self.assertIn("Discovery scan finished", finished_event["message"])
        self.assertIn("Scanned:", finished_event["message"])
        self.assertIn("new:", finished_event["message"])
        self.assertIn("updated:", finished_event["message"])
        self.assertIn("missing marked:", finished_event["message"])
        self.assertIn("duplicates:", finished_event["message"])
        self.assertIn("Total Indexed Pages:", finished_event["message"])
        self.assertIn("Missing Pages:", finished_event["message"])
        self.assertIn("Active Duplicate Files:", finished_event["message"])
        self.assertIn("total_pages", finished_event["data"])
        self.assertIn("missing_pages", finished_event["data"])
        self.assertIn("active_duplicate_files", finished_event["data"])

    def test_next_layout_review_page(self) -> None:
        self._write_image("p1.png", b"p1")
        self._write_image("p2.png", b"p2")
        main.scan_images()
        pages = main.list_pages()["pages"]
        page_ids = [int(page["id"]) for page in pages]
        self.assertEqual(len(page_ids), 2)

        for page_id in page_ids:
            main.create_page_layout(
                page_id,
                main.CreateLayoutRequest(
                    class_name="text",
                    reading_order=None,
                    bbox=main.BBoxPayload(x1=0.1, y1=0.1, x2=0.9, y2=0.25),
                ),
            )

        first_id, second_id = sorted(page_ids)
        next_from_first = main.next_layout_review_page(first_id)
        self.assertTrue(next_from_first["has_next"])
        self.assertEqual(next_from_first["next_page_id"], second_id)

        next_from_second = main.next_layout_review_page(second_id)
        self.assertTrue(next_from_second["has_next"])
        self.assertEqual(next_from_second["next_page_id"], first_id)

        main.complete_layout_review(first_id)
        main.complete_layout_review(second_id)
        none_left = main.next_layout_review_page(first_id)
        self.assertFalse(none_left["has_next"])
        self.assertIsNone(none_left["next_page_id"])

    def test_global_next_layout_review_page(self) -> None:
        self._write_image("g1.png", b"g1")
        self._write_image("g2.png", b"g2")
        main.scan_images()

        payload = main.next_layout_review_page_global()
        self.assertFalse(payload["has_next"])
        self.assertIsNone(payload["next_page_id"])

        pages = main.list_pages()["pages"]
        page_ids = [int(page["id"]) for page in pages]
        self.assertGreaterEqual(len(page_ids), 2)
        for page_id in page_ids:
            main.create_page_layout(
                page_id,
                main.CreateLayoutRequest(
                    class_name="text",
                    reading_order=None,
                    bbox=main.BBoxPayload(x1=0.1, y1=0.1, x2=0.9, y2=0.25),
                ),
            )

        payload = main.next_layout_review_page_global()
        self.assertTrue(payload["has_next"])
        self.assertEqual(payload["next_page_id"], min(page_ids))


if __name__ == "__main__":
    unittest.main()
