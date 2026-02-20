from __future__ import annotations

from contextlib import ExitStack
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app import config, db, discovery, layouts, main, ocr_extract, pipeline_runtime
from app.config import DEFAULT_EXTENSIONS, Settings


class PipelineStagesTests(unittest.TestCase):
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
        self.stack.enter_context(patch.object(layouts, "settings", self.test_settings))
        self.stack.enter_context(patch.object(main, "settings", self.test_settings))
        self.stack.enter_context(patch.object(ocr_extract, "settings", self.test_settings))
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

    def test_settings_loads_gemini_keys_from_yaml_map(self) -> None:
        config_path = self.project_root / "config.yaml"
        config_path.write_text(
            "\n".join(
                [
                    "source_dir: input",
                    "db_path: data/test.db",
                    "enable_background_jobs: false",
                    "gemini_keys:",
                    "  a:",
                    "    - key-1",
                    "    - key-2",
                    "  b:",
                    "    - key-2",
                    "    - key-3",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        with patch.dict(
            os.environ,
            {
                "PROJECT_ROOT": str(self.project_root),
                "APP_CONFIG_PATH": str(config_path),
            },
            clear=False,
        ):
            loaded = config.load_settings()

        self.assertEqual(loaded.gemini_keys, ("key-1", "key-2", "key-3"))
        self.assertEqual(loaded.gemini_usage_path, self.project_root / "_artifacts" / "gemini_usage.json")

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
        fake_inference_params = {
            "confidence_threshold": 0.3,
            "iou_threshold": 0.5,
            "image_size": 960,
            "max_detections": 123,
            "agnostic_nms": True,
        }

        with patch.object(layouts, "_detect_doclaynet_layouts", return_value=(fake_rows, fake_inference_params)) as detect_mock:
            result = main.detect_page_layouts(
                page_id,
                main.DetectLayoutsRequest(
                    replace_existing=True,
                    confidence_threshold=0.3,
                    iou_threshold=0.5,
                    image_size=960,
                    max_detections=123,
                    agnostic_nms=True,
                ),
            )

        self.assertEqual(result["created"], 1)
        self.assertEqual(result["thresholds"], {"confidence_threshold": 0.3, "iou_threshold": 0.5})
        self.assertEqual(result["inference_params"], fake_inference_params)
        self.assertEqual(result["class_counts"], {"text": 1})
        detect_mock.assert_called_once()
        self.assertEqual(detect_mock.call_args.kwargs["confidence_threshold"], 0.3)
        self.assertEqual(detect_mock.call_args.kwargs["iou_threshold"], 0.5)
        self.assertEqual(detect_mock.call_args.kwargs["image_size"], 960)
        self.assertEqual(detect_mock.call_args.kwargs["max_detections"], 123)
        self.assertEqual(detect_mock.call_args.kwargs["agnostic_nms"], True)

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

    def test_layout_review_enqueues_ocr_when_background_jobs_enabled(self) -> None:
        self.test_settings = Settings(
            project_root=self.project_root,
            source_dir=self.project_root / "input",
            db_path=self.project_root / "data" / "test.db",
            result_dir=self.project_root / "result",
            allowed_extensions=DEFAULT_EXTENSIONS,
            enable_background_jobs=True,
        )
        self.stack.close()
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(config, "settings", self.test_settings))
        self.stack.enter_context(patch.object(db, "settings", self.test_settings))
        self.stack.enter_context(patch.object(discovery, "settings", self.test_settings))
        self.stack.enter_context(patch.object(layouts, "settings", self.test_settings))
        self.stack.enter_context(patch.object(main, "settings", self.test_settings))
        self.stack.enter_context(patch.object(ocr_extract, "settings", self.test_settings))
        db.init_db()

        self._write_image("review-queue.png", b"review-image")
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

        with patch.object(main, "enqueue_job", return_value=True) as enqueue_mock:
            main.complete_layout_review(page_id)

        enqueue_mock.assert_called_once_with(
            "ocr_extract",
            page_id=page_id,
            payload={"trigger": "layout_review_complete"},
        )

    def test_layout_review_requires_caption_bindings(self) -> None:
        self._write_image("caption.png", b"caption-image")
        main.scan_images()
        page_id = self._first_page_id()

        caption_layout = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="caption",
                reading_order=None,
                bbox=main.BBoxPayload(x1=0.1, y1=0.7, x2=0.9, y2=0.8),
            ),
        )["layout"]
        table_layout = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="table",
                reading_order=None,
                bbox=main.BBoxPayload(x1=0.1, y1=0.2, x2=0.9, y2=0.65),
            ),
        )["layout"]

        with self.assertRaises(main.HTTPException) as review_error:
            main.complete_layout_review(page_id)
        self.assertEqual(review_error.exception.status_code, 400)
        self.assertIn("caption layouts must be bound", str(review_error.exception.detail))

        bindings_result = main.put_page_caption_bindings(
            page_id,
            main.ReplaceCaptionBindingsRequest(
                bindings=[
                    main.CaptionBindingPayload(
                        caption_layout_id=int(caption_layout["id"]),
                        target_layout_ids=[int(table_layout["id"])],
                    )
                ]
            ),
        )
        self.assertEqual(bindings_result["binding_count"], 1)

        reviewed = main.complete_layout_review(page_id)
        self.assertEqual(reviewed["status"], "layout_reviewed")

    def test_ocr_extract_handler_uses_gemini_keys(self) -> None:
        self.test_settings = Settings(
            project_root=self.project_root,
            source_dir=self.project_root / "input",
            db_path=self.project_root / "data" / "test.db",
            result_dir=self.project_root / "result",
            allowed_extensions=DEFAULT_EXTENSIONS,
            enable_background_jobs=False,
            gemini_keys=("k1", "k2"),
            gemini_usage_path=self.project_root / "_artifacts" / "gemini_usage.json",
        )
        self.stack.close()
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(config, "settings", self.test_settings))
        self.stack.enter_context(patch.object(db, "settings", self.test_settings))
        self.stack.enter_context(patch.object(discovery, "settings", self.test_settings))
        self.stack.enter_context(patch.object(layouts, "settings", self.test_settings))
        self.stack.enter_context(patch.object(main, "settings", self.test_settings))
        self.stack.enter_context(patch.object(ocr_extract, "settings", self.test_settings))
        db.init_db()

        self._write_image("ocr.png", b"fake-image")
        main.scan_images()
        page_id = self._first_page_id()
        main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="text",
                reading_order=None,
                bbox=main.BBoxPayload(x1=0.0, y1=0.0, x2=1.0, y2=1.0),
            ),
        )
        main.complete_layout_review(page_id)

        with patch.object(ocr_extract, "_crop_layout_png_bytes", return_value=b"png-bytes"), patch.object(
            ocr_extract, "_gemini_generate_content", return_value="Extracted text"
        ) as gemini_mock:
            result = pipeline_runtime._ocr_extract_handler({"page_id": page_id, "payload": {}, "id": 1, "stage": "ocr_extract"})

        self.assertEqual(result["status"], "ocr_done")
        self.assertEqual(result["extracted_count"], 1)
        self.assertEqual(result["requests_count"], 1)
        gemini_mock.assert_called_once()

        self.assertFalse(self.test_settings.gemini_usage_path.exists())

        page_payload = main.page_details(page_id)
        self.assertEqual(page_payload["page"]["status"], "ocr_done")

        outputs_payload = main.page_ocr_outputs(page_id)
        self.assertEqual(outputs_payload["count"], 1)
        self.assertEqual(outputs_payload["outputs"][0]["output_format"], "markdown")
        self.assertEqual(outputs_payload["outputs"][0]["content"], "Extracted text")

    def test_ocr_extract_stores_exhausted_keys_as_json_array(self) -> None:
        self.test_settings = Settings(
            project_root=self.project_root,
            source_dir=self.project_root / "input",
            db_path=self.project_root / "data" / "test.db",
            result_dir=self.project_root / "result",
            allowed_extensions=DEFAULT_EXTENSIONS,
            enable_background_jobs=False,
            gemini_keys=("k1", "k2"),
            gemini_usage_path=self.project_root / "_artifacts" / "gemini_usage.json",
        )
        self.stack.close()
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(config, "settings", self.test_settings))
        self.stack.enter_context(patch.object(db, "settings", self.test_settings))
        self.stack.enter_context(patch.object(discovery, "settings", self.test_settings))
        self.stack.enter_context(patch.object(layouts, "settings", self.test_settings))
        self.stack.enter_context(patch.object(main, "settings", self.test_settings))
        self.stack.enter_context(patch.object(ocr_extract, "settings", self.test_settings))
        db.init_db()

        self._write_image("ocr-exhausted.png", b"fake-image")
        main.scan_images()
        page_id = self._first_page_id()
        main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="text",
                reading_order=None,
                bbox=main.BBoxPayload(x1=0.0, y1=0.0, x2=1.0, y2=1.0),
            ),
        )
        main.complete_layout_review(page_id)

        def fake_gemini_call(api_key: str, prompt: str, image_bytes: bytes) -> str:
            del prompt, image_bytes
            if api_key == "k1":
                raise RuntimeError("HTTP 429 quota exceeded")
            return "Extracted text"

        with patch.object(ocr_extract, "_crop_layout_png_bytes", return_value=b"png-bytes"), patch.object(
            ocr_extract, "_gemini_generate_content", side_effect=fake_gemini_call
        ):
            result = pipeline_runtime._ocr_extract_handler({"page_id": page_id, "payload": {}, "id": 1, "stage": "ocr_extract"})

        self.assertEqual(result["status"], "ocr_done")
        usage_payload = json.loads(self.test_settings.gemini_usage_path.read_text(encoding="utf-8"))
        self.assertEqual(usage_payload, ["k1"])

    def test_ocr_review_flow_updates_output_and_marks_reviewed(self) -> None:
        self.test_settings = Settings(
            project_root=self.project_root,
            source_dir=self.project_root / "input",
            db_path=self.project_root / "data" / "test.db",
            result_dir=self.project_root / "result",
            allowed_extensions=DEFAULT_EXTENSIONS,
            enable_background_jobs=False,
            gemini_keys=("k1",),
            gemini_usage_path=self.project_root / "_artifacts" / "gemini_usage.json",
        )
        self.stack.close()
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(config, "settings", self.test_settings))
        self.stack.enter_context(patch.object(db, "settings", self.test_settings))
        self.stack.enter_context(patch.object(discovery, "settings", self.test_settings))
        self.stack.enter_context(patch.object(layouts, "settings", self.test_settings))
        self.stack.enter_context(patch.object(main, "settings", self.test_settings))
        self.stack.enter_context(patch.object(ocr_extract, "settings", self.test_settings))
        db.init_db()

        self._write_image("ocr-review.png", b"fake-image")
        main.scan_images()
        page_id = self._first_page_id()
        main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="text",
                reading_order=None,
                bbox=main.BBoxPayload(x1=0.0, y1=0.0, x2=1.0, y2=1.0),
            ),
        )
        main.complete_layout_review(page_id)

        with patch.object(ocr_extract, "_crop_layout_png_bytes", return_value=b"png-bytes"), patch.object(
            ocr_extract, "_gemini_generate_content", return_value="Extracted text"
        ):
            pipeline_runtime._ocr_extract_handler({"page_id": page_id, "payload": {}, "id": 1, "stage": "ocr_extract"})

        next_payload = main.next_ocr_review_page_global()
        self.assertTrue(next_payload["has_next"])
        self.assertEqual(next_payload["next_page_id"], page_id)

        outputs_payload = main.page_ocr_outputs(page_id)
        self.assertEqual(outputs_payload["count"], 1)
        layout_id = int(outputs_payload["outputs"][0]["layout_id"])

        updated = main.patch_ocr_output(layout_id, main.UpdateOcrOutputRequest(content="Corrected text"))
        self.assertEqual(updated["output"]["content"], "Corrected text")

        reviewed = main.complete_ocr_review(page_id)
        self.assertEqual(reviewed["status"], "ocr_reviewed")

        page_payload = main.page_details(page_id)
        self.assertEqual(page_payload["page"]["status"], "ocr_reviewed")

        next_after = main.next_ocr_review_page_global()
        self.assertFalse(next_after["has_next"])

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
