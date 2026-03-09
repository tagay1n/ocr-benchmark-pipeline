from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app import config, db, discovery, final_export, layouts, main, ocr_extract, pipeline_runtime, runtime_options, statuses
from app.config import DEFAULT_EXTENSIONS, Settings


class LayoutsAndRuntimeInternalsTests(unittest.TestCase):
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

    def _write_image(self, rel_path: str, content: bytes = b"fake") -> None:
        path = self.test_settings.source_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def _single_page_id(self) -> int:
        pages = main.list_pages()["pages"]
        self.assertEqual(len(pages), 1)
        return int(pages[0]["id"])

    def test_status_helpers_normalize_and_api_convert(self) -> None:
        self.assertEqual(statuses.normalize_db_status(" layout reviewed "), "LAYOUT_REVIEWED")
        self.assertEqual(statuses.normalize_db_status("ocr-done"), "OCR_DONE")
        self.assertEqual(statuses.to_api_status("OCR_DONE"), "ocr_done")
        self.assertEqual(statuses.to_api_status(None), "")

    def test_create_layout_normalizes_class_name_and_auto_increments_order(self) -> None:
        self._write_image("layout/normalize.png")
        main.scan_images()
        page_id = self._single_page_id()

        first = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="Section Header",
                reading_order=None,
                bbox=main.BBoxPayload(x1=0.1, y1=0.1, x2=0.9, y2=0.2),
            ),
        )["layout"]
        second = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="Text",
                reading_order=None,
                bbox=main.BBoxPayload(x1=0.1, y1=0.3, x2=0.9, y2=0.4),
            ),
        )["layout"]
        third = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="Title",
                reading_order=None,
                bbox=main.BBoxPayload(x1=0.1, y1=0.41, x2=0.9, y2=0.5),
            ),
        )["layout"]
        fourth = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="List item",
                reading_order=None,
                bbox=main.BBoxPayload(x1=0.1, y1=0.51, x2=0.9, y2=0.6),
            ),
        )["layout"]
        self.assertEqual(first["class_name"], "section_header")
        self.assertEqual(second["class_name"], "text")
        self.assertEqual(third["class_name"], "section_header")
        self.assertEqual(fourth["class_name"], "list_item")
        self.assertEqual(int(first["reading_order"]), 1)
        self.assertEqual(int(second["reading_order"]), 2)
        self.assertEqual(int(third["reading_order"]), 3)
        self.assertEqual(int(fourth["reading_order"]), 4)

    def test_replace_caption_bindings_deduplicates_and_sorts_target_ids(self) -> None:
        self._write_image("layout/caption-binding.png")
        main.scan_images()
        page_id = self._single_page_id()

        caption = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="caption",
                reading_order=1,
                bbox=main.BBoxPayload(x1=0.1, y1=0.8, x2=0.9, y2=0.95),
            ),
        )["layout"]
        table = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="table",
                reading_order=2,
                bbox=main.BBoxPayload(x1=0.1, y1=0.1, x2=0.9, y2=0.5),
            ),
        )["layout"]
        formula = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="formula",
                reading_order=3,
                bbox=main.BBoxPayload(x1=0.1, y1=0.55, x2=0.9, y2=0.75),
            ),
        )["layout"]

        result = main.put_page_caption_bindings(
            page_id,
            main.ReplaceCaptionBindingsRequest(
                bindings=[
                    main.CaptionBindingPayload(
                        caption_layout_id=int(caption["id"]),
                        target_layout_ids=[int(formula["id"]), int(table["id"]), int(formula["id"])],
                    )
                ]
            ),
        )
        self.assertEqual(result["binding_count"], 2)
        self.assertEqual(
            result["bindings"],
            [
                {
                    "caption_layout_id": int(caption["id"]),
                    "target_layout_ids": sorted([int(table["id"]), int(formula["id"])]),
                }
            ],
        )

    def test_mark_layout_reviewed_requires_all_captions_bound(self) -> None:
        self._write_image("layout/captions-multi.png")
        main.scan_images()
        page_id = self._single_page_id()

        caption_a = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="caption",
                reading_order=1,
                bbox=main.BBoxPayload(x1=0.1, y1=0.7, x2=0.9, y2=0.8),
            ),
        )["layout"]
        caption_b = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="caption",
                reading_order=2,
                bbox=main.BBoxPayload(x1=0.1, y1=0.81, x2=0.9, y2=0.9),
            ),
        )["layout"]
        table = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="table",
                reading_order=3,
                bbox=main.BBoxPayload(x1=0.1, y1=0.2, x2=0.9, y2=0.65),
            ),
        )["layout"]

        with self.assertRaises(main.HTTPException) as partial_bind_error:
            main.put_page_caption_bindings(
                page_id,
                main.ReplaceCaptionBindingsRequest(
                    bindings=[
                        main.CaptionBindingPayload(
                            caption_layout_id=int(caption_a["id"]),
                            target_layout_ids=[int(table["id"])],
                        )
                    ]
                ),
            )
        self.assertEqual(partial_bind_error.exception.status_code, 400)
        self.assertIn("caption layouts must be bound", str(partial_bind_error.exception.detail).lower())

        with self.assertRaises(main.HTTPException) as review_error:
            main.complete_layout_review(page_id)
        self.assertEqual(review_error.exception.status_code, 400)
        self.assertIn("caption layouts must be bound", str(review_error.exception.detail).lower())

        main.put_page_caption_bindings(
            page_id,
            main.ReplaceCaptionBindingsRequest(
                bindings=[
                    main.CaptionBindingPayload(
                        caption_layout_id=int(caption_a["id"]),
                        target_layout_ids=[int(table["id"])],
                    ),
                    main.CaptionBindingPayload(
                        caption_layout_id=int(caption_b["id"]),
                        target_layout_ids=[int(table["id"])],
                    ),
                ]
            ),
        )
        reviewed = main.complete_layout_review(page_id)
        self.assertEqual(reviewed["status"], "layout_reviewed")

    def test_detect_layouts_replace_existing_false_appends_orders(self) -> None:
        self._write_image("layout/detect-append.png")
        main.scan_images()
        page_id = self._single_page_id()
        main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="text",
                reading_order=1,
                bbox=main.BBoxPayload(x1=0.0, y1=0.0, x2=0.2, y2=0.2),
            ),
        )

        detected_rows = [
            {"class_name": "list_item", "confidence": 0.9, "x1": 0.2, "y1": 0.2, "x2": 0.4, "y2": 0.4},
            {"class_name": "title", "confidence": 0.8, "x1": 0.45, "y1": 0.45, "x2": 0.8, "y2": 0.8},
        ]
        params = {
            "confidence_threshold": 0.25,
            "iou_threshold": 0.45,
            "image_size": 1024,
            "max_detections": 300,
            "agnostic_nms": False,
        }
        with patch.object(layouts, "_detect_doclaynet_layouts", return_value=(detected_rows, params)):
            result = main.detect_page_layouts(page_id, main.DetectLayoutsRequest(replace_existing=False))
        self.assertEqual(result["created"], 2)
        self.assertEqual(result["class_counts"], {"text": 1, "section_header": 1})

        page_layouts = main.page_layouts(page_id)["layouts"]
        self.assertEqual([int(row["reading_order"]) for row in page_layouts], [1, 2, 3])
        self.assertEqual([row["class_name"] for row in page_layouts], ["text", "text", "section_header"])

    def test_get_activity_snapshot_starts_worker_when_jobs_queued(self) -> None:
        now = main._utc_now()
        with db.get_session() as session:
            session.add(
                main.PipelineJob(
                    stage="layout_detect",
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
            )

        with patch.object(pipeline_runtime, "_WORKER_THREAD", None), patch.object(
            pipeline_runtime, "_ensure_worker_running", return_value=None
        ) as ensure_mock:
            payload = pipeline_runtime.get_activity_snapshot(limit=10)

        ensure_mock.assert_called_once()
        self.assertEqual(payload["queued"]["total"], 1)
        self.assertIn("layout_detect", payload["queued"]["by_stage"])

    def test_register_default_handlers_is_idempotent(self) -> None:
        with patch.object(pipeline_runtime, "_DEFAULT_HANDLERS_REGISTERED", False), patch.object(
            pipeline_runtime, "register_stage_handler"
        ) as register_mock:
            pipeline_runtime.register_default_handlers()
            pipeline_runtime.register_default_handlers()

        calls = [(str(call.args[0]), call.args[1].__name__) for call in register_mock.mock_calls]
        self.assertEqual(calls, [("layout_detect", "_layout_detect_handler"), ("ocr_extract", "_ocr_extract_handler")])

    def test_completion_message_handles_skipped_and_default_paths(self) -> None:
        skipped = pipeline_runtime._completion_message("ocr_extract", {"skipped": True, "reason": "page is missing"})
        self.assertIn("Skipped OCR extraction", skipped)
        default = pipeline_runtime._completion_message("unknown_stage", {"x": 1})
        self.assertIn("Completed unknown stage", default)


if __name__ == "__main__":
    unittest.main()
