from __future__ import annotations

import asyncio
from contextlib import ExitStack
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import func, select

from app import config, db, discovery, final_export, layouts, main, ocr_extract, runtime_options
from app.config import DEFAULT_EXTENSIONS, Settings
from app.models import CaptionBinding


class LayoutClassContractsTests(unittest.TestCase):
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

    def _write_image(self, rel_path: str, content: bytes = b"fake-image") -> Path:
        path = self.test_settings.source_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def _single_page_id(self) -> int:
        pages = main.list_pages()["pages"]
        self.assertEqual(len(pages), 1)
        return int(pages[0]["id"])

    def _assert_no_title_class_in_layouts_db_and_api(self, page_id: int) -> None:
        payload = main.page_layouts(page_id)
        classes = [str(layout["class_name"]) for layout in payload["layouts"]]
        self.assertNotIn("title", classes)
        with db.get_session() as session:
            title_count = int(
                session.execute(
                    select(func.count()).select_from(main.Layout).where(main.Layout.class_name == "title")
                ).scalar_one()
            )
        self.assertEqual(title_count, 0)

    def test_contract_detected_layout_classes_are_remapped_before_persist(self) -> None:
        self._write_image("contract/remap.png")
        main.scan_images()
        page_id = self._single_page_id()

        detected_rows = [
            {"class_name": "title", "confidence": 0.91, "x1": 0.05, "y1": 0.05, "x2": 0.95, "y2": 0.2},
            {"class_name": "list_item", "confidence": 0.82, "x1": 0.1, "y1": 0.25, "x2": 0.9, "y2": 0.5},
        ]
        params = {
            "confidence_threshold": 0.25,
            "iou_threshold": 0.45,
            "image_size": 1024,
            "max_detections": 300,
            "agnostic_nms": False,
        }
        with patch.object(layouts, "_detect_doclaynet_layouts", return_value=(detected_rows, params)):
            result = main.detect_page_layouts(page_id, main.DetectLayoutsRequest(replace_existing=True))

        self.assertEqual(result["class_counts"], {"section_header": 1, "text": 1})

        payload = main.page_layouts(page_id)
        classes = [str(layout["class_name"]) for layout in payload["layouts"]]
        self.assertEqual(classes, ["section_header", "text"])
        self.assertNotIn("title", classes)
        self.assertNotIn("list_item", classes)

        with db.get_session() as session:
            title_count = int(
                session.execute(
                    select(func.count()).select_from(main.Layout).where(main.Layout.class_name == "title")
                ).scalar_one()
            )
        self.assertEqual(title_count, 0)

    def test_contract_manual_layout_edits_remap_title_but_preserve_list_item(self) -> None:
        self._write_image("contract/manual.png")
        main.scan_images()
        page_id = self._single_page_id()

        from_title = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="Title",
                reading_order=1,
                bbox=main.BBoxPayload(x1=0.05, y1=0.05, x2=0.95, y2=0.2),
            ),
        )["layout"]
        self.assertEqual(from_title["class_name"], "section_header")

        from_list_item = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="List item",
                reading_order=2,
                bbox=main.BBoxPayload(x1=0.1, y1=0.25, x2=0.9, y2=0.5),
            ),
        )["layout"]
        self.assertEqual(from_list_item["class_name"], "list_item")

        patched = main.patch_layout(
            int(from_list_item["id"]),
            main.UpdateLayoutRequest(class_name="title"),
        )["layout"]
        self.assertEqual(patched["class_name"], "section_header")

        with db.get_session() as session:
            title_count = int(
                session.execute(
                    select(func.count()).select_from(main.Layout).where(main.Layout.class_name == "title")
                ).scalar_one()
            )
        self.assertEqual(title_count, 0)

    def test_contract_layouts_api_payload_never_exposes_title_class(self) -> None:
        self._write_image("contract/api-layouts.png")
        main.scan_images()
        page_id = self._single_page_id()

        created = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="title",
                reading_order=1,
                bbox=main.BBoxPayload(x1=0.05, y1=0.05, x2=0.95, y2=0.2),
            ),
        )["layout"]
        self.assertEqual(created["class_name"], "section_header")

        patched = main.patch_layout(
            int(created["id"]),
            main.UpdateLayoutRequest(class_name="title"),
        )["layout"]
        self.assertEqual(patched["class_name"], "section_header")

        detected_rows = [
            {"class_name": "title", "confidence": 0.7, "x1": 0.05, "y1": 0.25, "x2": 0.95, "y2": 0.45},
            {"class_name": "list_item", "confidence": 0.8, "x1": 0.05, "y1": 0.5, "x2": 0.95, "y2": 0.7},
        ]
        params = {
            "confidence_threshold": 0.25,
            "iou_threshold": 0.45,
            "image_size": 1024,
            "max_detections": 300,
            "agnostic_nms": False,
        }
        with patch.object(layouts, "_detect_doclaynet_layouts", return_value=(detected_rows, params)):
            main.detect_page_layouts(page_id, main.DetectLayoutsRequest(replace_existing=False))

        payload = main.page_layouts(page_id)
        classes = [str(layout["class_name"]) for layout in payload["layouts"]]
        self.assertNotIn("title", classes)
        self.assertTrue(all(class_name in {"section_header", "text"} for class_name in classes))

    def test_contract_pipeline_activity_stream_manual_detect_event_uses_remapped_class_counts(self) -> None:
        self._write_image("contract/sse-remap.png")
        main.scan_images()
        page_id = self._single_page_id()

        detected_rows = [
            {"class_name": "title", "confidence": 0.9, "x1": 0.1, "y1": 0.1, "x2": 0.8, "y2": 0.2},
            {"class_name": "list_item", "confidence": 0.85, "x1": 0.1, "y1": 0.25, "x2": 0.8, "y2": 0.5},
        ]
        params = {
            "confidence_threshold": 0.25,
            "iou_threshold": 0.45,
            "image_size": 1024,
            "max_detections": 300,
            "agnostic_nms": False,
        }

        class _RequestStub:
            def __init__(self) -> None:
                self.calls = 0

            async def is_disconnected(self) -> bool:
                self.calls += 1
                return self.calls > 2

        async def _fast_sleep(_seconds: float) -> None:
            return None

        async def _collect_payload_after_detect() -> dict[str, object]:
            response = await main.pipeline_activity_stream(_RequestStub(), limit=200)
            iterator = response.body_iterator
            await anext(iterator)
            with patch.object(layouts, "_detect_doclaynet_layouts", return_value=(detected_rows, params)):
                main.detect_page_layouts(page_id, main.DetectLayoutsRequest(replace_existing=True))
            second_chunk = await anext(iterator)
            await iterator.aclose()
            text = second_chunk.decode("utf-8") if isinstance(second_chunk, bytes) else str(second_chunk)
            return json.loads(text[len("data: ") : -2])

        with patch("app.main.asyncio.sleep", new=_fast_sleep):
            payload = asyncio.run(_collect_payload_after_detect())

        matching_events = [
            event
            for event in payload["recent_events"]
            if event.get("event_type") == "manual_detect_completed" and int(event.get("page_id") or 0) == page_id
        ]
        self.assertTrue(matching_events, "manual_detect_completed event for the page was not found in SSE payload")
        class_counts = matching_events[-1]["data"]["class_counts"]
        self.assertEqual(class_counts, {"section_header": 1, "text": 1})
        self.assertNotIn("title", class_counts)
        self.assertNotIn("list_item", class_counts)

    def test_contract_end_to_end_detection_remap_flows_into_ocr_outputs(self) -> None:
        self._write_image("contract/remap-to-ocr.png")
        main.scan_images()
        page_id = self._single_page_id()

        detected_rows = [
            {"class_name": "title", "confidence": 0.91, "x1": 0.05, "y1": 0.05, "x2": 0.95, "y2": 0.2},
            {"class_name": "list_item", "confidence": 0.82, "x1": 0.1, "y1": 0.25, "x2": 0.9, "y2": 0.5},
        ]
        params = {
            "confidence_threshold": 0.25,
            "iou_threshold": 0.45,
            "image_size": 1024,
            "max_detections": 300,
            "agnostic_nms": False,
        }
        with patch.object(layouts, "_detect_doclaynet_layouts", return_value=(detected_rows, params)):
            main.detect_page_layouts(page_id, main.DetectLayoutsRequest(replace_existing=True))

        review_result = main.complete_layout_review(page_id)
        self.assertEqual(review_result["status"], "layout_reviewed")

        with patch.object(ocr_extract, "_crop_layout_png_bytes", return_value=b"png-bytes"), patch.object(
            ocr_extract, "_next_available_key", return_value="test-key"
        ), patch.object(ocr_extract, "_gemini_generate_content", side_effect=["Header line", "Body line"]):
            extract_result = main.reextract_ocr(page_id, main.ReextractOcrRequest())

        self.assertEqual(extract_result["status"], "ocr_done")
        outputs = main.page_ocr_outputs(page_id)["outputs"]
        output_classes = {str(output["class_name"]) for output in outputs}
        self.assertEqual(output_classes, {"section_header", "text"})
        self.assertNotIn("title", output_classes)
        self.assertNotIn("list_item", output_classes)

    def test_contract_mixed_workflow_never_produces_title_class(self) -> None:
        self._write_image("contract/mixed-workflow.png")
        main.scan_images()
        page_id = self._single_page_id()

        initial_rows = [
            {"class_name": "title", "confidence": 0.9, "x1": 0.05, "y1": 0.05, "x2": 0.95, "y2": 0.2},
            {"class_name": "list_item", "confidence": 0.8, "x1": 0.05, "y1": 0.25, "x2": 0.95, "y2": 0.5},
        ]
        params = {
            "confidence_threshold": 0.25,
            "iou_threshold": 0.45,
            "image_size": 1024,
            "max_detections": 300,
            "agnostic_nms": False,
        }
        with patch.object(layouts, "_detect_doclaynet_layouts", return_value=(initial_rows, params)):
            main.detect_page_layouts(page_id, main.DetectLayoutsRequest(replace_existing=True))

        first_layout_id = int(main.page_layouts(page_id)["layouts"][0]["id"])
        patched = main.patch_layout(first_layout_id, main.UpdateLayoutRequest(class_name="title"))["layout"]
        self.assertEqual(patched["class_name"], "section_header")

        appended_rows = [
            {"class_name": "TITLE", "confidence": 0.7, "x1": 0.1, "y1": 0.55, "x2": 0.9, "y2": 0.7},
            {"class_name": "List Item", "confidence": 0.65, "x1": 0.1, "y1": 0.72, "x2": 0.9, "y2": 0.9},
        ]
        with patch.object(layouts, "_detect_doclaynet_layouts", return_value=(appended_rows, params)):
            main.detect_page_layouts(page_id, main.DetectLayoutsRequest(replace_existing=False))

        self._assert_no_title_class_in_layouts_db_and_api(page_id)

        main.complete_layout_review(page_id)
        with patch.object(ocr_extract, "_crop_layout_png_bytes", return_value=b"png-bytes"), patch.object(
            ocr_extract, "_next_available_key", return_value="test-key"
        ), patch.object(ocr_extract, "_gemini_generate_content", return_value="OCR text"):
            result = main.reextract_ocr(page_id, main.ReextractOcrRequest())
        self.assertEqual(result["status"], "ocr_done")

        outputs = main.page_ocr_outputs(page_id)["outputs"]
        self.assertTrue(outputs)
        self.assertNotIn("title", {str(row["class_name"]) for row in outputs})

    def test_contract_detector_name_variants_remap_to_canonical_classes(self) -> None:
        self._write_image("contract/normalize-variants.png")
        main.scan_images()
        page_id = self._single_page_id()

        variant_rows = [
            {"class_name": " Title ", "confidence": 0.9, "x1": 0.05, "y1": 0.05, "x2": 0.95, "y2": 0.2},
            {"class_name": "title", "confidence": 0.88, "x1": 0.05, "y1": 0.21, "x2": 0.95, "y2": 0.35},
            {"class_name": "list-item", "confidence": 0.84, "x1": 0.05, "y1": 0.36, "x2": 0.95, "y2": 0.5},
            {"class_name": "LIST ITEM", "confidence": 0.8, "x1": 0.05, "y1": 0.51, "x2": 0.95, "y2": 0.65},
            {"class_name": "list/item", "confidence": 0.79, "x1": 0.05, "y1": 0.66, "x2": 0.95, "y2": 0.8},
        ]
        params = {
            "confidence_threshold": 0.25,
            "iou_threshold": 0.45,
            "image_size": 1024,
            "max_detections": 300,
            "agnostic_nms": False,
        }
        with patch.object(layouts, "_detect_doclaynet_layouts", return_value=(variant_rows, params)):
            result = main.detect_page_layouts(page_id, main.DetectLayoutsRequest(replace_existing=True))

        self.assertEqual(result["class_counts"], {"section_header": 2, "text": 3})
        classes = [str(layout["class_name"]) for layout in main.page_layouts(page_id)["layouts"]]
        self.assertEqual(classes.count("section_header"), 2)
        self.assertEqual(classes.count("text"), 3)
        self.assertNotIn("title", classes)
        self.assertNotIn("list_item", classes)

    def test_contract_sse_manual_detect_event_has_stable_shape_and_forbidden_classes_absent(self) -> None:
        self._write_image("contract/sse-schema.png")
        main.scan_images()
        page_id = self._single_page_id()

        detected_rows = [
            {"class_name": "title", "confidence": 0.9, "x1": 0.1, "y1": 0.1, "x2": 0.8, "y2": 0.2},
            {"class_name": "list_item", "confidence": 0.85, "x1": 0.1, "y1": 0.25, "x2": 0.8, "y2": 0.5},
        ]
        params = {
            "confidence_threshold": 0.25,
            "iou_threshold": 0.45,
            "image_size": 1024,
            "max_detections": 300,
            "agnostic_nms": False,
        }

        class _RequestStub:
            def __init__(self) -> None:
                self.calls = 0

            async def is_disconnected(self) -> bool:
                self.calls += 1
                return self.calls > 2

        async def _fast_sleep(_seconds: float) -> None:
            return None

        async def _collect_payload_after_detect() -> dict[str, object]:
            response = await main.pipeline_activity_stream(_RequestStub(), limit=200)
            iterator = response.body_iterator
            await anext(iterator)
            with patch.object(layouts, "_detect_doclaynet_layouts", return_value=(detected_rows, params)):
                main.detect_page_layouts(page_id, main.DetectLayoutsRequest(replace_existing=True))
            second_chunk = await anext(iterator)
            await iterator.aclose()
            text = second_chunk.decode("utf-8") if isinstance(second_chunk, bytes) else str(second_chunk)
            return json.loads(text[len("data: ") : -2])

        with patch("app.main.asyncio.sleep", new=_fast_sleep):
            payload = asyncio.run(_collect_payload_after_detect())

        event = next(
            (
                row
                for row in payload["recent_events"]
                if row.get("event_type") == "manual_detect_completed" and int(row.get("page_id") or 0) == page_id
            ),
            None,
        )
        self.assertIsNotNone(event, "manual_detect_completed event for the page was not found")
        expected_event_keys = {"id", "ts", "stage", "event_type", "page_id", "rel_path", "message", "data"}
        self.assertEqual(set(event.keys()), expected_event_keys)
        self.assertEqual(event["stage"], "layout_detect")
        self.assertEqual(event["event_type"], "manual_detect_completed")
        self.assertIsInstance(event["data"], dict)
        self.assertIn("class_counts", event["data"])
        class_counts = event["data"]["class_counts"]
        self.assertEqual(class_counts, {"section_header": 1, "text": 1})
        self.assertNotIn("title", class_counts)
        self.assertNotIn("list_item", class_counts)

    def test_contract_reextract_subset_preserves_remapped_classes(self) -> None:
        self._write_image("contract/reextract-subset.png")
        main.scan_images()
        page_id = self._single_page_id()

        detected_rows = [
            {"class_name": "title", "confidence": 0.9, "x1": 0.05, "y1": 0.05, "x2": 0.95, "y2": 0.2},
            {"class_name": "list_item", "confidence": 0.82, "x1": 0.1, "y1": 0.25, "x2": 0.9, "y2": 0.5},
        ]
        params = {
            "confidence_threshold": 0.25,
            "iou_threshold": 0.45,
            "image_size": 1024,
            "max_detections": 300,
            "agnostic_nms": False,
        }
        with patch.object(layouts, "_detect_doclaynet_layouts", return_value=(detected_rows, params)):
            main.detect_page_layouts(page_id, main.DetectLayoutsRequest(replace_existing=True))
        main.complete_layout_review(page_id)

        page_layouts = main.page_layouts(page_id)["layouts"]
        first_layout_id = int(page_layouts[0]["id"])
        second_layout_id = int(page_layouts[1]["id"])

        with patch.object(ocr_extract, "_crop_layout_png_bytes", return_value=b"png-bytes"), patch.object(
            ocr_extract, "_next_available_key", return_value="test-key"
        ), patch.object(ocr_extract, "_gemini_generate_content", side_effect=["Initial header", "Initial body"]):
            first_pass = main.reextract_ocr(page_id, main.ReextractOcrRequest())
        self.assertEqual(first_pass["status"], "ocr_done")

        with patch.object(ocr_extract, "_crop_layout_png_bytes", return_value=b"png-bytes"), patch.object(
            ocr_extract, "_next_available_key", return_value="test-key"
        ), patch.object(ocr_extract, "_gemini_generate_content", side_effect=["Updated header"]):
            second_pass = main.reextract_ocr(page_id, main.ReextractOcrRequest(layout_ids=[first_layout_id]))
        self.assertEqual(second_pass["status"], "ocr_done")

        outputs = {int(row["layout_id"]): row for row in main.page_ocr_outputs(page_id)["outputs"]}
        self.assertEqual(str(outputs[first_layout_id]["class_name"]), "section_header")
        self.assertEqual(str(outputs[second_layout_id]["class_name"]), "text")
        self.assertRegex(str(outputs[first_layout_id]["content"]), r"^#{2,6}\s+Updated header$")
        self.assertEqual(str(outputs[second_layout_id]["content"]), "Initial body")
        self.assertNotIn("title", {str(row["class_name"]) for row in outputs.values()})

    def test_contract_create_and_patch_reject_blank_class_names(self) -> None:
        self._write_image("contract/blank-class.png")
        main.scan_images()
        page_id = self._single_page_id()

        with self.assertRaises(HTTPException) as create_error:
            main.create_page_layout(
                page_id,
                main.CreateLayoutRequest(
                    class_name="   ",
                    reading_order=1,
                    bbox=main.BBoxPayload(x1=0.1, y1=0.1, x2=0.5, y2=0.3),
                ),
            )
        self.assertEqual(create_error.exception.status_code, 400)
        self.assertEqual(create_error.exception.detail, "class_name cannot be empty.")

        layout = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="text",
                reading_order=1,
                bbox=main.BBoxPayload(x1=0.1, y1=0.1, x2=0.5, y2=0.3),
            ),
        )["layout"]

        with self.assertRaises(HTTPException) as patch_error:
            main.patch_layout(int(layout["id"]), main.UpdateLayoutRequest(class_name="   "))
        self.assertEqual(patch_error.exception.status_code, 400)
        self.assertEqual(patch_error.exception.detail, "class_name cannot be empty.")

    def test_contract_layout_db_invariants_hold_after_mixed_operations(self) -> None:
        self._write_image("contract/db-invariants.png")
        main.scan_images()
        page_id = self._single_page_id()

        detected_rows = [
            {"class_name": "title", "confidence": 0.9, "x1": 0.05, "y1": 0.05, "x2": 0.95, "y2": 0.2},
            {"class_name": "list_item", "confidence": 0.82, "x1": 0.1, "y1": 0.25, "x2": 0.9, "y2": 0.5},
        ]
        params = {
            "confidence_threshold": 0.25,
            "iou_threshold": 0.45,
            "image_size": 1024,
            "max_detections": 300,
            "agnostic_nms": False,
        }
        with patch.object(layouts, "_detect_doclaynet_layouts", return_value=(detected_rows, params)):
            main.detect_page_layouts(page_id, main.DetectLayoutsRequest(replace_existing=True))

        main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="list_item",
                reading_order=None,
                bbox=main.BBoxPayload(x1=0.05, y1=0.55, x2=0.95, y2=0.7),
            ),
        )
        first_layout_id = int(main.page_layouts(page_id)["layouts"][0]["id"])
        main.patch_layout(first_layout_id, main.UpdateLayoutRequest(class_name="title"))

        with db.get_session() as session:
            rows = session.execute(
                select(main.Layout.class_name, main.Layout.reading_order)
                .where(main.Layout.page_id == page_id)
                .order_by(main.Layout.id.asc())
            ).all()

        self.assertGreaterEqual(len(rows), 1)
        classes = [str(row[0]) for row in rows]
        reading_orders = [int(row[1]) for row in rows]
        self.assertNotIn("title", classes)
        self.assertTrue(all(value >= 1 for value in reading_orders))
        self.assertEqual(len(reading_orders), len(set(reading_orders)))

    def test_contract_redetect_replace_existing_clears_previous_layouts_and_caption_bindings(self) -> None:
        self._write_image("contract/redetect-replace.png")
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
                bbox=main.BBoxPayload(x1=0.1, y1=0.1, x2=0.9, y2=0.7),
            ),
        )["layout"]
        main.put_page_caption_bindings(
            page_id,
            main.ReplaceCaptionBindingsRequest(
                bindings=[
                    main.CaptionBindingPayload(
                        caption_layout_id=int(caption["id"]),
                        target_layout_ids=[int(table["id"])],
                    )
                ]
            ),
        )

        with db.get_session() as session:
            before_binding_count = int(
                session.execute(select(func.count()).select_from(CaptionBinding)).scalar_one()
            )
            self.assertEqual(before_binding_count, 1)

        detected_rows = [
            {"class_name": "text", "confidence": 0.9, "x1": 0.05, "y1": 0.05, "x2": 0.95, "y2": 0.5},
        ]
        params = {
            "confidence_threshold": 0.25,
            "iou_threshold": 0.45,
            "image_size": 1024,
            "max_detections": 300,
            "agnostic_nms": False,
        }
        with patch.object(layouts, "_detect_doclaynet_layouts", return_value=(detected_rows, params)):
            result = main.detect_page_layouts(page_id, main.DetectLayoutsRequest(replace_existing=True))
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["class_counts"], {"text": 1})

        payload = main.page_layouts(page_id)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["layouts"][0]["class_name"], "text")
        self.assertEqual(payload["layouts"][0]["bound_target_ids"], [])

        with db.get_session() as session:
            after_binding_count = int(session.execute(select(func.count()).select_from(CaptionBinding)).scalar_one())
        self.assertEqual(after_binding_count, 0)

    def test_contract_manual_detect_emits_started_before_completed_for_page(self) -> None:
        self._write_image("contract/sse-order.png")
        main.scan_images()
        page_id = self._single_page_id()

        detected_rows = [
            {"class_name": "text", "confidence": 0.9, "x1": 0.05, "y1": 0.05, "x2": 0.95, "y2": 0.5},
        ]
        params = {
            "confidence_threshold": 0.25,
            "iou_threshold": 0.45,
            "image_size": 1024,
            "max_detections": 300,
            "agnostic_nms": False,
        }
        with patch.object(layouts, "_detect_doclaynet_layouts", return_value=(detected_rows, params)):
            main.detect_page_layouts(page_id, main.DetectLayoutsRequest(replace_existing=True))

        events = [
            row
            for row in main.pipeline_activity(limit=200)["recent_events"]
            if int(row.get("page_id") or 0) == page_id
            and row.get("stage") == "layout_detect"
            and row.get("event_type") in {"manual_detect_started", "manual_detect_completed"}
        ]
        self.assertGreaterEqual(len(events), 2)
        started_indexes = [index for index, row in enumerate(events) if row["event_type"] == "manual_detect_started"]
        completed_indexes = [index for index, row in enumerate(events) if row["event_type"] == "manual_detect_completed"]
        self.assertTrue(started_indexes)
        self.assertTrue(completed_indexes)
        self.assertLess(started_indexes[-1], completed_indexes[-1])


if __name__ == "__main__":
    unittest.main()
