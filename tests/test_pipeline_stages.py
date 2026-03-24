from __future__ import annotations

import asyncio
from contextlib import ExitStack
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app import config, db, discovery, final_export, layouts, main, ocr_extract, pipeline_runtime, runtime_options
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

    def _write_image(self, rel_path: str, content: bytes) -> None:
        path = self.test_settings.source_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def _first_page_id(self) -> int:
        pages_payload = main.list_pages()
        self.assertGreaterEqual(pages_payload["count"], 1)
        return int(pages_payload["pages"][0]["id"])

    def _set_page_ocr_done_with_outputs(
        self,
        page_id: int,
        outputs: list[tuple[int, str, str, str]],
    ) -> None:
        now = main._utc_now()
        with db.get_session() as session:
            for layout_id, class_name, output_format, content in outputs:
                session.add(
                    main.OcrOutput(
                        layout_id=int(layout_id),
                        page_id=int(page_id),
                        class_name=str(class_name),
                        output_format=str(output_format),
                        content=str(content),
                        model_name="gemini-3-flash-preview",
                        key_alias="test-key",
                        created_at=now,
                        updated_at=now,
                    )
                )
            page_row = session.get(main.Page, page_id)
            self.assertIsNotNone(page_row)
            page_row.status = "ocr_done"
            page_row.updated_at = now

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

    def test_remove_page_deletes_file_and_related_records(self) -> None:
        self._write_image("remove/a.png", b"same-content")
        self._write_image("remove/dup/a-copy.png", b"same-content")
        main.scan_images()
        page_id = self._first_page_id()

        layout_payload = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="text",
                reading_order=None,
                bbox=main.BBoxPayload(x1=0.1, y1=0.2, x2=0.9, y2=0.4),
            ),
        )
        self.assertIn("layout", layout_payload)

        image_path = self.test_settings.source_dir / "remove/a.png"
        self.assertTrue(image_path.exists())

        removed = main.remove_page(page_id)
        self.assertTrue(removed["deleted"])
        self.assertEqual(removed["page_id"], page_id)
        self.assertEqual(removed["rel_path"], "remove/a.png")
        self.assertTrue(removed["file_existed"])
        self.assertTrue(removed["file_deleted"])
        self.assertEqual(removed["related_counts"]["layouts"], 1)
        self.assertEqual(removed["related_counts"]["duplicate_files"], 1)

        self.assertFalse(image_path.exists())
        self.assertEqual(main.list_pages()["count"], 0)
        self.assertEqual(main.list_duplicates()["count"], 0)

        with self.assertRaises(main.HTTPException) as page_error:
            main.page_details(page_id)
        self.assertEqual(page_error.exception.status_code, 404)

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

    def test_manual_layout_detect_works(self) -> None:
        self._write_image("manual-detect.png", b"manual-detect-image")
        main.scan_images()
        page_id = self._first_page_id()

        fake_rows = [
            {
                "class_name": "text",
                "confidence": 0.88,
                "x1": 0.1,
                "y1": 0.2,
                "x2": 0.8,
                "y2": 0.9,
            }
        ]
        fake_inference_params = {
            "confidence_threshold": 0.25,
            "iou_threshold": 0.45,
            "image_size": 1024,
            "max_detections": 300,
            "agnostic_nms": False,
        }

        with patch.object(layouts, "_detect_doclaynet_layouts", return_value=(fake_rows, fake_inference_params)):
            result = main.detect_page_layouts(page_id, main.DetectLayoutsRequest(replace_existing=True))

        self.assertEqual(result["created"], 1)
        self.assertEqual(result["inference_params"]["image_size"], 1024)

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

    def test_layout_review_never_auto_enqueues_ocr_when_background_jobs_enabled(self) -> None:
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
        self.stack.enter_context(patch.object(runtime_options, "settings", self.test_settings))
        db.init_db()
        runtime_options.reset_runtime_options_from_settings()

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

        enqueue_mock.assert_not_called()

    def test_scan_never_auto_enqueues_layout_detection(self) -> None:
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
        self.stack.enter_context(patch.object(runtime_options, "settings", self.test_settings))
        db.init_db()
        runtime_options.reset_runtime_options_from_settings()

        self._write_image("scan-auto-layout.png", b"scan-image")

        with patch.object(main, "enqueue_layout_detection_for_new_pages", return_value={"considered": 1, "queued": 1, "already_queued_or_running": 0}) as enqueue_mock:
            first = main.scan_images()
        enqueue_mock.assert_not_called()
        self.assertEqual(
            first["auto_layout_detection"],
            {"considered": 0, "queued": 0, "already_queued_or_running": 0},
        )

    def test_layout_review_never_auto_enqueues_ocr(self) -> None:
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
        self.stack.enter_context(patch.object(runtime_options, "settings", self.test_settings))
        db.init_db()
        runtime_options.reset_runtime_options_from_settings()

        self._write_image("layout-auto-ocr-a.png", b"a")
        self._write_image("layout-auto-ocr-b.png", b"b")
        main.scan_images()
        pages = sorted(main.list_pages()["pages"], key=lambda row: row["rel_path"])
        first_page_id = int(pages[0]["id"])
        second_page_id = int(pages[1]["id"])

        for page_id in (first_page_id, second_page_id):
            main.create_page_layout(
                page_id,
                main.CreateLayoutRequest(
                    class_name="text",
                    reading_order=None,
                    bbox=main.BBoxPayload(x1=0.1, y1=0.1, x2=0.9, y2=0.25),
                ),
            )

        with patch.object(main, "enqueue_job", return_value=True) as enqueue_mock:
            main.complete_layout_review(first_page_id)
        enqueue_mock.assert_not_called()
        with patch.object(main, "enqueue_job", return_value=True) as enqueue_mock:
            main.complete_layout_review(second_page_id)
        enqueue_mock.assert_not_called()

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
        self.stack.enter_context(patch.object(runtime_options, "settings", self.test_settings))
        db.init_db()
        runtime_options.reset_runtime_options_from_settings()

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

    def test_ocr_extract_writes_prompt_debug_artifact(self) -> None:
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
        self.stack.enter_context(patch.object(runtime_options, "settings", self.test_settings))
        db.init_db()
        runtime_options.reset_runtime_options_from_settings()

        self._write_image("ocr-prompt-debug.png", b"fake-image")
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
            result = pipeline_runtime._ocr_extract_handler({"page_id": page_id, "payload": {}, "id": 1, "stage": "ocr_extract"})

        prompt_debug_path = Path(str(result.get("prompt_debug_path", "")))
        self.assertTrue(prompt_debug_path.exists())
        self.assertTrue(prompt_debug_path.name.endswith(f"_page_{page_id}.jsonl"))

        rows = [
            json.loads(line)
            for line in prompt_debug_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertGreaterEqual(len(rows), 1)
        first = rows[0]
        self.assertEqual(first["page_id"], page_id)
        self.assertEqual(first["class_name"], "text")
        self.assertEqual(first["output_format"], "markdown")
        self.assertIn('Return output as JSON only: {"content":"..."}', first["prompt"])
        self.assertIn("Keep text as normal Markdown paragraphs.", first["prompt"])
        self.assertNotIn("clip", first["prompt"].lower())

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
        self.stack.enter_context(patch.object(runtime_options, "settings", self.test_settings))
        db.init_db()
        runtime_options.reset_runtime_options_from_settings()

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

        def fake_gemini_call(
            api_key: str, prompt: str, image_bytes: bytes, *, temperature: float = 0.0
        ) -> str:
            del prompt, image_bytes
            if api_key == "k1":
                raise RuntimeError("HTTP 429 RESOURCE_EXHAUSTED GenerateRequestsPerDayPerProjectPerModel-FreeTier")
            self.assertEqual(temperature, 0.0)
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
        self.stack.enter_context(patch.object(runtime_options, "settings", self.test_settings))
        db.init_db()
        runtime_options.reset_runtime_options_from_settings()

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

    def test_manual_ocr_reextract_refreshes_outputs_and_resets_reviewed_status(self) -> None:
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
        self.stack.enter_context(patch.object(runtime_options, "settings", self.test_settings))
        db.init_db()
        runtime_options.reset_runtime_options_from_settings()

        self._write_image("ocr-reextract.png", b"fake-image")
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
            ocr_extract, "_gemini_generate_content", return_value="Initial text"
        ):
            pipeline_runtime._ocr_extract_handler({"page_id": page_id, "payload": {}, "id": 1, "stage": "ocr_extract"})

        reviewed = main.complete_ocr_review(page_id)
        self.assertEqual(reviewed["status"], "ocr_reviewed")

        with patch.object(ocr_extract, "_crop_layout_png_bytes", return_value=b"png-bytes"), patch.object(
            ocr_extract, "_gemini_generate_content", return_value="Reextracted text"
        ):
            result = main.reextract_ocr(page_id)

        self.assertEqual(result["status"], "ocr_done")
        self.assertEqual(result["extracted_count"], 1)
        self.assertEqual(result["requests_count"], 1)

        page_payload = main.page_details(page_id)
        self.assertEqual(page_payload["page"]["status"], "ocr_done")

        outputs_payload = main.page_ocr_outputs(page_id)
        self.assertEqual(outputs_payload["count"], 1)
        self.assertEqual(outputs_payload["outputs"][0]["content"], "Reextracted text")

    def test_manual_ocr_reextract_accepts_prompt_and_generation_params(self) -> None:
        self._write_image("ocr-reextract-params.png", b"fake-image")
        main.scan_images()
        page_id = self._first_page_id()
        layout_payload = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="text",
                reading_order=None,
                bbox=main.BBoxPayload(x1=0.0, y1=0.0, x2=1.0, y2=1.0),
            ),
        )
        layout_id = int(layout_payload["layout"]["id"])
        main.complete_layout_review(page_id)

        fake_result = {
            "page_id": page_id,
            "status": "ocr_done",
            "model": "gemini-3-flash-preview",
            "layouts_total": 1,
            "extracted_count": 1,
            "skipped_count": 0,
            "requests_count": 1,
            "inference_params": {
                "temperature": 0.2,
                "max_retries_per_layout": 5,
                "prompt_template": "Rules: {class_rule}. {format_rule}",
            },
        }
        request_payload = main.ReextractOcrRequest(
            layout_ids=[layout_id],
            prompt_template="Rules: {class_rule}. {format_rule}",
            temperature=0.2,
            max_retries_per_layout=5,
        )
        with patch.object(main, "extract_ocr_for_page", return_value=fake_result) as extract_mock:
            result = main.reextract_ocr(page_id, request_payload)

        self.assertEqual(result, fake_result)
        extract_mock.assert_called_once_with(
            page_id,
            layout_ids=[layout_id],
            prompt_template="Rules: {class_rule}. {format_rule}",
            temperature=0.2,
            max_retries_per_layout=5,
        )

    def test_manual_ocr_reextract_works(self) -> None:
        self._write_image("ocr-reextract-auto-disabled.png", b"fake-image")
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

        fake_result = {
            "page_id": page_id,
            "status": "ocr_done",
            "model": "gemini-3-flash-preview",
            "layouts_total": 1,
            "extracted_count": 1,
            "skipped_count": 0,
            "requests_count": 1,
            "inference_params": {
                "temperature": 0.0,
                "max_retries_per_layout": 3,
                "prompt_template": "default",
            },
        }
        with patch.object(main, "extract_ocr_for_page", return_value=fake_result) as extract_mock:
            result = main.reextract_ocr(page_id, main.ReextractOcrRequest())

        self.assertEqual(result["status"], "ocr_done")
        extract_mock.assert_called_once_with(
            page_id,
            layout_ids=None,
            prompt_template=None,
            temperature=None,
            max_retries_per_layout=None,
        )

    def test_manual_ocr_reextract_allows_ocr_extracting_status(self) -> None:
        self._write_image("ocr-reextract-from-extracting.png", b"fake-image")
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

        with db.get_session() as session:
            page_row = session.get(main.Page, page_id)
            self.assertIsNotNone(page_row)
            page_row.status = "ocr_extracting"

        fake_result = {
            "page_id": page_id,
            "status": "ocr_done",
            "model": "gemini-3-flash-preview",
            "layouts_total": 1,
            "extracted_count": 1,
            "skipped_count": 0,
            "requests_count": 1,
            "inference_params": {
                "temperature": 0.0,
                "max_retries_per_layout": 3,
                "prompt_template": "default",
            },
        }
        with patch.object(main, "extract_ocr_for_page", return_value=fake_result):
            result = main.reextract_ocr(page_id, main.ReextractOcrRequest())

        self.assertEqual(result["status"], "ocr_done")

    def test_manual_ocr_reextract_selected_layouts_updates_only_selected_outputs(self) -> None:
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
        self.stack.enter_context(patch.object(runtime_options, "settings", self.test_settings))
        db.init_db()
        runtime_options.reset_runtime_options_from_settings()

        self._write_image("ocr-reextract-selected-layouts.png", b"fake-image")
        main.scan_images()
        page_id = self._first_page_id()
        first_layout = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="text",
                reading_order=1,
                bbox=main.BBoxPayload(x1=0.0, y1=0.0, x2=0.5, y2=0.5),
            ),
        )["layout"]
        second_layout = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="text",
                reading_order=2,
                bbox=main.BBoxPayload(x1=0.5, y1=0.5, x2=1.0, y2=1.0),
            ),
        )["layout"]
        first_layout_id = int(first_layout["id"])
        second_layout_id = int(second_layout["id"])

        main.complete_layout_review(page_id)

        with patch.object(ocr_extract, "_crop_layout_png_bytes", return_value=b"png-bytes"), patch.object(
            ocr_extract, "_gemini_generate_content", side_effect=["Initial first", "Initial second"]
        ):
            pipeline_runtime._ocr_extract_handler({"page_id": page_id, "payload": {}, "id": 1, "stage": "ocr_extract"})

        reviewed = main.complete_ocr_review(page_id)
        self.assertEqual(reviewed["status"], "ocr_reviewed")

        with patch.object(ocr_extract, "_crop_layout_png_bytes", return_value=b"png-bytes"), patch.object(
            ocr_extract, "_gemini_generate_content", side_effect=["Updated first"]
        ):
            result = main.reextract_ocr(page_id, main.ReextractOcrRequest(layout_ids=[first_layout_id]))

        self.assertEqual(result["status"], "ocr_done")
        self.assertEqual(result["layouts_total"], 2)
        self.assertEqual(result["layouts_selected"], 1)
        self.assertEqual(result["extracted_count"], 1)
        self.assertEqual(result["requests_count"], 1)

        outputs_payload = main.page_ocr_outputs(page_id)
        outputs_by_layout_id = {int(output["layout_id"]): str(output["content"]) for output in outputs_payload["outputs"]}
        self.assertEqual(outputs_by_layout_id[first_layout_id], "Updated first")
        self.assertEqual(outputs_by_layout_id[second_layout_id], "Initial second")

    def test_manual_ocr_reextract_failure_keeps_previous_outputs(self) -> None:
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

        self._write_image("ocr-reextract-fail.png", b"fake-image")
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
            ocr_extract, "_gemini_generate_content", return_value="Initial text"
        ):
            pipeline_runtime._ocr_extract_handler({"page_id": page_id, "payload": {}, "id": 1, "stage": "ocr_extract"})

        initial_outputs = main.page_ocr_outputs(page_id)
        self.assertEqual(initial_outputs["count"], 1)
        self.assertEqual(initial_outputs["outputs"][0]["content"], "Initial text")

        with patch.object(ocr_extract, "_crop_layout_png_bytes", return_value=b"png-bytes"), patch.object(
            ocr_extract, "_gemini_generate_content", side_effect=RuntimeError("HTTP 500 transient failure")
        ):
            with self.assertRaises(main.HTTPException) as reextract_error:
                main.reextract_ocr(page_id)

        self.assertEqual(reextract_error.exception.status_code, 400)
        outputs_after = main.page_ocr_outputs(page_id)
        self.assertEqual(outputs_after["count"], 1)
        self.assertEqual(outputs_after["outputs"][0]["content"], "Initial text")

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
        self.assertFalse(next_from_second["has_next"])
        self.assertIsNone(next_from_second["next_page_id"])

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
        self.assertTrue(payload["has_next"])

        pages = main.list_pages()["pages"]
        page_ids = [int(page["id"]) for page in pages]
        self.assertGreaterEqual(len(page_ids), 2)
        self.assertEqual(payload["next_page_id"], min(page_ids))
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

    def test_next_ocr_review_page_no_wraparound_and_global_progress(self) -> None:
        self._write_image("ocr-next/a.png", b"a")
        self._write_image("ocr-next/b.png", b"b")
        main.scan_images()

        pages = sorted(main.list_pages()["pages"], key=lambda row: int(row["id"]))
        self.assertEqual(len(pages), 2)
        page_ids = [int(page["id"]) for page in pages]

        for page_id in page_ids:
            layout_payload = main.create_page_layout(
                page_id,
                main.CreateLayoutRequest(
                    class_name="text",
                    reading_order=1,
                    bbox=main.BBoxPayload(x1=0.1, y1=0.1, x2=0.9, y2=0.3),
                ),
            )
            main.complete_layout_review(page_id)
            self._set_page_ocr_done_with_outputs(
                page_id,
                [
                    (
                        int(layout_payload["layout"]["id"]),
                        "text",
                        "markdown",
                        f"text-{page_id}",
                    )
                ],
            )

        first_id, second_id = page_ids
        next_from_first = main.next_ocr_review_page(first_id)
        self.assertTrue(next_from_first["has_next"])
        self.assertEqual(next_from_first["next_page_id"], second_id)

        next_from_second = main.next_ocr_review_page(second_id)
        self.assertFalse(next_from_second["has_next"])
        self.assertIsNone(next_from_second["next_page_id"])

        global_next = main.next_ocr_review_page_global()
        self.assertTrue(global_next["has_next"])
        self.assertEqual(global_next["next_page_id"], first_id)

        main.complete_ocr_review(first_id)
        global_after_first_review = main.next_ocr_review_page_global()
        self.assertTrue(global_after_first_review["has_next"])
        self.assertEqual(global_after_first_review["next_page_id"], second_id)

        main.complete_ocr_review(second_id)
        global_after_all_reviews = main.next_ocr_review_page_global()
        self.assertFalse(global_after_all_reviews["has_next"])
        self.assertIsNone(global_after_all_reviews["next_page_id"])

    def test_complete_ocr_review_requires_ocr_done_and_is_repeatable(self) -> None:
        self._write_image("ocr-review-repeatable.png", b"img")
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

        with self.assertRaises(main.HTTPException) as review_error:
            main.complete_ocr_review(page_id)
        self.assertEqual(review_error.exception.status_code, 400)
        self.assertIn("no ocr outputs", str(review_error.exception.detail).lower())

        layouts_payload = main.page_layouts(page_id)
        self.assertEqual(layouts_payload["count"], 1)
        layout_id = int(layouts_payload["layouts"][0]["id"])
        self._set_page_ocr_done_with_outputs(
            page_id,
            [(layout_id, "text", "markdown", "extracted")],
        )

        first = main.complete_ocr_review(page_id)
        second = main.complete_ocr_review(page_id)
        self.assertEqual(first["status"], "ocr_reviewed")
        self.assertEqual(second["status"], "ocr_reviewed")
        self.assertEqual(first["output_count"], 1)
        self.assertEqual(second["output_count"], 1)

    def test_pipeline_activity_stream_sends_valid_sse_json_payload(self) -> None:
        self._write_image("sse.png", b"sse")
        main.scan_images()

        class _RequestStub:
            def __init__(self) -> None:
                self._checks = 0

            async def is_disconnected(self) -> bool:
                self._checks += 1
                return self._checks > 1

        async def _read_first_chunk() -> tuple[object, bytes | str]:
            response = await main.pipeline_activity_stream(_RequestStub(), limit=3)
            iterator = response.body_iterator
            first_chunk = await anext(iterator)
            await iterator.aclose()
            return response, first_chunk

        response, chunk = asyncio.run(_read_first_chunk())
        self.assertEqual(response.headers.get("content-type"), "text/event-stream; charset=utf-8")
        text = chunk.decode("utf-8") if isinstance(chunk, bytes) else str(chunk)
        self.assertTrue(text.startswith("data: "))
        self.assertTrue(text.endswith("\n\n"))
        payload = json.loads(text[len("data: ") : -2])
        self.assertIn("worker_running", payload)
        self.assertIn("in_progress", payload)
        self.assertIn("queued", payload)
        self.assertIn("recent_events", payload)
        self.assertLessEqual(len(payload["recent_events"]), 3)

    def test_enqueue_job_deduplicates_by_stage_and_page(self) -> None:
        self._write_image("queue/a.png", b"a")
        self._write_image("queue/b.png", b"b")
        main.scan_images()
        pages = sorted(main.list_pages()["pages"], key=lambda row: int(row["id"]))
        self.assertEqual(len(pages), 2)
        page_a = int(pages[0]["id"])
        page_b = int(pages[1]["id"])

        with patch.object(pipeline_runtime, "_ensure_worker_running", return_value=None):
            self.assertTrue(pipeline_runtime.enqueue_job("layout_detect", page_id=page_a, payload={"trigger": "x"}))
            self.assertFalse(pipeline_runtime.enqueue_job("layout_detect", page_id=page_a, payload={"trigger": "y"}))
            self.assertTrue(pipeline_runtime.enqueue_job("layout_detect", page_id=page_b, payload={"trigger": "z"}))
            self.assertTrue(pipeline_runtime.enqueue_job("layout_detect", page_id=None, payload={"global": True}))
            self.assertFalse(pipeline_runtime.enqueue_job("layout_detect", page_id=None, payload={"global": False}))

        with db.get_session() as session:
            rows = session.query(main.PipelineJob).order_by(main.PipelineJob.id.asc()).all()
            self.assertEqual(len(rows), 3)
            self.assertEqual([str(row.status) for row in rows], ["queued", "queued", "queued"])
            self.assertEqual([row.page_id for row in rows], [page_a, page_b, None])

    def test_claim_next_job_moves_to_running_and_increments_attempts(self) -> None:
        self._write_image("claim-next.png", b"x")
        main.scan_images()
        page_id = self._first_page_id()

        with patch.object(pipeline_runtime, "_ensure_worker_running", return_value=None):
            enqueued = pipeline_runtime.enqueue_job("layout_detect", page_id=page_id, payload={"trigger": "test"})
        self.assertTrue(enqueued)

        claimed = pipeline_runtime._claim_next_job()
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed["stage"], "layout_detect")
        self.assertEqual(claimed["page_id"], page_id)
        self.assertEqual(claimed["payload"], {"trigger": "test"})

        with db.get_session() as session:
            row = session.get(main.PipelineJob, int(claimed["id"]))
            self.assertIsNotNone(row)
            self.assertEqual(str(row.status), "running")
            self.assertEqual(int(row.attempts), 1)
            self.assertIsNotNone(row.started_at)

    def test_worker_loop_finalizes_success_and_failure_jobs(self) -> None:
        now = main._utc_now()
        with db.get_session() as session:
            success_job = main.PipelineJob(
                stage="stage_ok",
                page_id=None,
                status="queued",
                payload_json=None,
                result_json=None,
                error=None,
                attempts=0,
                created_at=now,
                updated_at=now,
                started_at=None,
                finished_at=None,
            )
            failed_job = main.PipelineJob(
                stage="stage_fail",
                page_id=None,
                status="queued",
                payload_json=None,
                result_json=None,
                error=None,
                attempts=0,
                created_at=now,
                updated_at=now,
                started_at=None,
                finished_at=None,
            )
            session.add(success_job)
            session.add(failed_job)
            session.flush()
            success_job_id = int(success_job.id)
            failed_job_id = int(failed_job.id)

        def _ok_handler(_job: dict[str, object]) -> dict[str, object]:
            return {"done": True}

        def _fail_handler(_job: dict[str, object]) -> dict[str, object]:
            raise RuntimeError("boom")

        with patch.dict(pipeline_runtime._HANDLERS, {"stage_ok": _ok_handler, "stage_fail": _fail_handler}, clear=True), patch.object(
            pipeline_runtime,
            "_claim_next_job",
            side_effect=[
                {"id": success_job_id, "stage": "stage_ok", "page_id": None, "payload": {}},
                {"id": failed_job_id, "stage": "stage_fail", "page_id": None, "payload": {}},
                None,
            ],
        ):
            pipeline_runtime._worker_loop()

        with db.get_session() as session:
            success_row = session.get(main.PipelineJob, success_job_id)
            failed_row = session.get(main.PipelineJob, failed_job_id)
            self.assertIsNotNone(success_row)
            self.assertIsNotNone(failed_row)
            self.assertEqual(str(success_row.status), "completed")
            self.assertIn('"done":true', str(success_row.result_json))
            self.assertEqual(str(failed_row.status), "failed")
            self.assertEqual(str(failed_row.error), "boom")

            completed_events = (
                session.query(main.PipelineEvent)
                .filter(main.PipelineEvent.event_type == "job_completed")
                .count()
            )
            failed_events = (
                session.query(main.PipelineEvent)
                .filter(main.PipelineEvent.event_type == "job_failed")
                .count()
            )
            self.assertGreaterEqual(int(completed_events), 1)
            self.assertGreaterEqual(int(failed_events), 1)

    def test_caption_binding_rejects_cross_page_target(self) -> None:
        self._write_image("cross-page/caption-page.png", b"a")
        self._write_image("cross-page/target-page.png", b"b")
        main.scan_images()

        pages = sorted(main.list_pages()["pages"], key=lambda row: row["rel_path"])
        caption_page_id = int(pages[0]["id"])
        target_page_id = int(pages[1]["id"])

        caption_layout = main.create_page_layout(
            caption_page_id,
            main.CreateLayoutRequest(
                class_name="caption",
                reading_order=1,
                bbox=main.BBoxPayload(x1=0.1, y1=0.7, x2=0.9, y2=0.9),
            ),
        )["layout"]
        target_layout = main.create_page_layout(
            target_page_id,
            main.CreateLayoutRequest(
                class_name="table",
                reading_order=1,
                bbox=main.BBoxPayload(x1=0.1, y1=0.2, x2=0.9, y2=0.6),
            ),
        )["layout"]

        with self.assertRaises(main.HTTPException) as bind_error:
            main.put_page_caption_bindings(
                caption_page_id,
                main.ReplaceCaptionBindingsRequest(
                    bindings=[
                        main.CaptionBindingPayload(
                            caption_layout_id=int(caption_layout["id"]),
                            target_layout_ids=[int(target_layout["id"])],
                        )
                    ]
                ),
            )
        self.assertEqual(bind_error.exception.status_code, 400)
        self.assertIn("same page", str(bind_error.exception.detail).lower())

    def test_caption_binding_requires_rebind_after_target_deletion(self) -> None:
        self._write_image("caption-delete-target.png", b"img")
        main.scan_images()
        page_id = self._first_page_id()

        caption_layout = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="caption",
                reading_order=1,
                bbox=main.BBoxPayload(x1=0.1, y1=0.7, x2=0.9, y2=0.9),
            ),
        )["layout"]
        table_layout = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="table",
                reading_order=2,
                bbox=main.BBoxPayload(x1=0.1, y1=0.1, x2=0.9, y2=0.6),
            ),
        )["layout"]

        main.put_page_caption_bindings(
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

        main.remove_layout(int(table_layout["id"]))
        layouts_payload = main.page_layouts(page_id)
        caption_rows = [row for row in layouts_payload["layouts"] if row["class_name"] == "caption"]
        self.assertEqual(len(caption_rows), 1)
        self.assertEqual(caption_rows[0]["bound_target_ids"], [])

        with self.assertRaises(main.HTTPException) as review_error:
            main.complete_layout_review(page_id)
        self.assertEqual(review_error.exception.status_code, 400)
        self.assertIn("caption layouts must be bound", str(review_error.exception.detail).lower())

    def test_settings_parse_bool_extensions_and_env_overrides(self) -> None:
        config_path = self.project_root / "config.yml"
        config_path.write_text(
            "\n".join(
                [
                    "source_dir: input",
                    "db_path: data/test.db",
                    "result_dir: result",
                    "allowed_image_extensions:",
                    "  - png",
                    "  - .JPG",
                    "enable_background_jobs: \"off\"",
                    "gemini_keys:",
                    "  batch_a:",
                    "    - key-a",
                    "    - key-b",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        with patch.dict(
            os.environ,
            {"PROJECT_ROOT": str(self.project_root), "APP_CONFIG_PATH": str(config_path)},
            clear=False,
        ):
            loaded = config.load_settings()

        self.assertEqual(loaded.allowed_extensions, (".png", ".jpg"))
        self.assertFalse(loaded.enable_background_jobs)
        self.assertEqual(loaded.gemini_keys, ("key-a", "key-b"))

        with patch.dict(
            os.environ,
            {
                "PROJECT_ROOT": str(self.project_root),
                "APP_CONFIG_PATH": str(config_path),
                "ALLOWED_IMAGE_EXTENSIONS": "webp, tif",
                "GEMINI_KEYS": "env-a, env-a, env-b ",
            },
            clear=False,
        ):
            loaded_env = config.load_settings()

        self.assertEqual(loaded_env.allowed_extensions, (".webp", ".tif"))
        self.assertEqual(loaded_env.gemini_keys, ("env-a", "env-b"))

    def test_runtime_options_reset_uses_current_settings_defaults(self) -> None:
        custom_settings = Settings(
            project_root=self.project_root,
            source_dir=self.project_root / "input",
            db_path=self.project_root / "data" / "test.db",
            result_dir=self.project_root / "result",
            allowed_extensions=DEFAULT_EXTENSIONS,
            enable_background_jobs=True,
        )
        with patch.object(runtime_options, "settings", custom_settings):
            snapshot = runtime_options.reset_runtime_options_from_settings()

        self.assertTrue(snapshot.enable_background_jobs)
        runtime_options.reset_runtime_options_from_settings()

    def test_final_export_contract_and_page_filtering(self) -> None:
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow is required for final export tests.")

        def write_png(rel_path: str, color: tuple[int, int, int]) -> None:
            path = self.test_settings.source_dir / rel_path
            path.parent.mkdir(parents=True, exist_ok=True)
            image = Image.new("RGB", (16, 12), color)
            image.save(path, format="PNG")

        write_png("export/reviewed.png", (70, 90, 110))
        self._write_image("export/pending.png", b"pending-non-image")
        main.scan_images()
        pages_by_path = {str(page["rel_path"]): int(page["id"]) for page in main.list_pages()["pages"]}
        reviewed_page_id = pages_by_path["export/reviewed.png"]
        pending_page_id = pages_by_path["export/pending.png"]

        text_layout = main.create_page_layout(
            reviewed_page_id,
            main.CreateLayoutRequest(
                class_name="text",
                reading_order=1,
                bbox=main.BBoxPayload(x1=0.05, y1=0.05, x2=0.95, y2=0.3),
            ),
        )["layout"]
        picture_layout = main.create_page_layout(
            reviewed_page_id,
            main.CreateLayoutRequest(
                class_name="picture",
                reading_order=2,
                bbox=main.BBoxPayload(x1=0.1, y1=0.35, x2=0.9, y2=0.8),
            ),
        )["layout"]
        caption_layout = main.create_page_layout(
            reviewed_page_id,
            main.CreateLayoutRequest(
                class_name="caption",
                reading_order=3,
                bbox=main.BBoxPayload(x1=0.1, y1=0.82, x2=0.9, y2=0.95),
            ),
        )["layout"]
        main.put_page_caption_bindings(
            reviewed_page_id,
            main.ReplaceCaptionBindingsRequest(
                bindings=[
                    main.CaptionBindingPayload(
                        caption_layout_id=int(caption_layout["id"]),
                        target_layout_ids=[int(picture_layout["id"])],
                    )
                ]
            ),
        )
        main.complete_layout_review(reviewed_page_id)
        self._set_page_ocr_done_with_outputs(
            reviewed_page_id,
            [
                (int(text_layout["id"]), "text", "markdown", "body"),
                (int(picture_layout["id"]), "picture", "skip", ""),
                (int(caption_layout["id"]), "caption", "markdown", "caption"),
            ],
        )
        main.complete_ocr_review(reviewed_page_id)

        main.create_page_layout(
            pending_page_id,
            main.CreateLayoutRequest(
                class_name="text",
                reading_order=1,
                bbox=main.BBoxPayload(x1=0.1, y1=0.1, x2=0.9, y2=0.3),
            ),
        )
        main.complete_layout_review(pending_page_id)
        pending_layout_id = int(main.page_layouts(pending_page_id)["layouts"][0]["id"])
        self._set_page_ocr_done_with_outputs(
            pending_page_id,
            [(pending_layout_id, "text", "markdown", "pending")],
        )

        result = final_export.export_final_dataset()
        self.assertEqual(result["page_count"], 1)
        self.assertEqual(result["image_count"], 1)
        self.assertEqual(result["reconstructed_count"], 1)

        metadata_path = Path(result["metadata_file"])
        self.assertTrue(metadata_path.exists())
        rows = [
            json.loads(line)
            for line in metadata_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(int(row["page_id"]), reviewed_page_id)
        self.assertEqual(row["file_name"], "images/export/reviewed.png")
        self.assertEqual(row["reconstructed_file_name"], "reconstructed/export/reviewed.png")
        self.assertEqual(int(row["width"]), 16)
        self.assertEqual(int(row["height"]), 12)

        items = list(row["items"])
        self.assertEqual([int(item["order"]) for item in items], [1, 2, 3])
        text_item = next(item for item in items if item["class_name"] == "text")
        picture_item = next(item for item in items if item["class_name"] == "picture")
        caption_item = next(item for item in items if item["class_name"] == "caption")
        self.assertEqual(text_item["content"], "body")
        self.assertEqual(text_item["content_format"], "markdown")
        self.assertNotIn("content", picture_item)
        self.assertNotIn("content_format", picture_item)
        self.assertEqual(caption_item["content"], "caption")
        self.assertEqual(caption_item["caption_targets"], [int(picture_layout["id"])])

        for item in items:
            for coord in ("x1", "y1", "x2", "y2"):
                value = float(item["bbox"][coord])
                self.assertGreaterEqual(value, 0.0)
                self.assertLessEqual(value, 1.0)


if __name__ == "__main__":
    unittest.main()
