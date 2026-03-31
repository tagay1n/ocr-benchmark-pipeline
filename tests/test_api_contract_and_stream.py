from __future__ import annotations

import asyncio
from contextlib import ExitStack
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app import config, db, discovery, final_export, layouts, main, ocr_extract, runtime_options
from app.config import DEFAULT_EXTENSIONS, Settings


class ApiContractAndStreamTests(unittest.TestCase):
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

    def _mark_page_ocr_reviewed_with_single_output(self, page_id: int, *, content: str = "ok") -> None:
        layout = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="text",
                reading_order=1,
                bbox=main.BBoxPayload(x1=0.1, y1=0.1, x2=0.9, y2=0.3),
            ),
        )["layout"]
        now = main._utc_now()
        with db.get_session() as session:
            session.add(
                main.OcrOutput(
                    layout_id=int(layout["id"]),
                    page_id=page_id,
                    class_name="text",
                    output_format="markdown",
                    content=content,
                    model_name="test",
                    key_alias="k",
                    created_at=now,
                    updated_at=now,
                )
            )
            page = session.get(main.Page, page_id)
            self.assertIsNotNone(page)
            page.status = "ocr_reviewed"
            page.updated_at = now

    def test_openapi_includes_core_paths_and_final_export_route(self) -> None:
        schema = main.app.openapi()
        paths = schema.get("paths", {})
        self.assertIn("/api/discovery/scan", paths)
        self.assertIn("/api/pipeline/activity/stream", paths)
        self.assertIn("/api/pages/{page_id}/ocr/reextract", paths)
        self.assertIn("/api/pages/summary", paths)
        self.assertIn("/api/final/export", paths)
        self.assertIn("/api/layout-benchmark/status", paths)
        self.assertIn("/api/layout-benchmark/grid", paths)
        self.assertIn("/api/layout-benchmark/run", paths)
        self.assertIn("/api/layout-benchmark/stop", paths)
        self.assertIn("/api/layout-benchmark/rescore", paths)
        self.assertIn("/api/ocr-batch/status", paths)
        self.assertIn("/api/ocr-batch/run", paths)
        self.assertIn("/api/ocr-batch/stop", paths)
        self.assertIn("/api/pages/{page_id}/layout-order-mode", paths)
        self.assertIn("/api/pages/{page_id}/layouts/reorder", paths)
        self.assertIn("post", paths["/api/final/export"])
        final_export_post = paths["/api/final/export"]["post"]
        request_body = final_export_post.get("requestBody", {})
        self.assertIn("application/json", request_body.get("content", {}))

    def test_final_export_requires_confirmation(self) -> None:
        with self.assertRaises(HTTPException) as error:
            main.run_final_export(main.FinalExportRequest(confirm=False))
        self.assertEqual(error.exception.status_code, 400)
        self.assertIn("not confirmed", str(error.exception.detail).lower())

    def test_final_export_endpoint_returns_expected_payload(self) -> None:
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow is required for final export endpoint test.")

        image_path = self.test_settings.source_dir / "export/ready.png"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (10, 8), (220, 220, 220)).save(image_path, format="PNG")

        main.scan_images()
        page_id = self._single_page_id()
        self._mark_page_ocr_reviewed_with_single_output(page_id, content="hello")

        result = main.run_final_export(main.FinalExportRequest(confirm=True))
        self.assertIn("export_dir", result)
        self.assertIn("metadata_file", result)
        self.assertIn("dataset_file", result)
        self.assertEqual(Path(str(result["metadata_file"])), Path(str(result["dataset_file"])))
        self.assertEqual(Path(str(result["dataset_file"])).name, "dataset.jsonl")
        self.assertEqual(result["page_count"], 1)
        self.assertEqual(result["image_count"], 1)
        self.assertEqual(result["reconstructed_count"], 1)
        self.assertTrue(Path(str(result["metadata_file"])).exists())

    def test_final_export_endpoint_fails_without_reviewed_pages(self) -> None:
        with self.assertRaises(HTTPException) as error:
            main.run_final_export(main.FinalExportRequest(confirm=True))
        self.assertEqual(error.exception.status_code, 400)
        self.assertIn("no ocr reviewed pages", str(error.exception.detail).lower())

    def test_page_image_rejects_path_outside_source_dir(self) -> None:
        now = main._utc_now()
        with db.get_session() as session:
            row = main.Page(
                rel_path="../outside.png",
                file_hash="hash-outside",
                status="new",
                created_at=now,
                updated_at=now,
                last_seen_at=now,
                is_missing=False,
            )
            session.add(row)
            session.flush()
            page_id = int(row.id)

        with self.assertRaises(HTTPException) as error:
            main.page_image(page_id)
        self.assertEqual(error.exception.status_code, 400)
        self.assertIn("invalid page image path", str(error.exception.detail).lower())

    def test_pipeline_activity_stream_reflects_new_event_between_ticks(self) -> None:
        self._write_image("sse/delta.png")
        main.scan_images()

        class _RequestStub:
            def __init__(self) -> None:
                self.calls = 0

            async def is_disconnected(self) -> bool:
                self.calls += 1
                return self.calls > 2

        async def _fast_sleep(_seconds: float) -> None:
            return None

        async def _collect_two_payloads() -> list[dict[str, object]]:
            response = await main.pipeline_activity_stream(_RequestStub(), limit=100)
            iterator = response.body_iterator
            first_chunk = await anext(iterator)
            main.emit_event(
                stage="pipeline",
                event_type="custom_test_event",
                message="custom stream delta event",
            )
            second_chunk = await anext(iterator)
            await iterator.aclose()
            chunks = [first_chunk, second_chunk]
            payloads: list[dict[str, object]] = []
            for chunk in chunks:
                text = chunk.decode("utf-8") if isinstance(chunk, bytes) else str(chunk)
                payloads.append(json.loads(text[len("data: ") : -2]))
            return payloads

        with patch("app.main.asyncio.sleep", new=_fast_sleep):
            first_payload, second_payload = asyncio.run(_collect_two_payloads())

        first_ids = [int(event["id"]) for event in first_payload["recent_events"]]
        second_ids = [int(event["id"]) for event in second_payload["recent_events"]]
        self.assertGreaterEqual(len(second_ids), len(first_ids))
        self.assertGreater(max(second_ids), max(first_ids))
        self.assertTrue(
            any(str(event.get("event_type")) == "custom_test_event" for event in second_payload["recent_events"])
        )


if __name__ == "__main__":
    unittest.main()
