from __future__ import annotations

from contextlib import ExitStack
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from sqlalchemy import select

from app import config, db, discovery, final_export, layouts, main, ocr_extract, runtime_options
from app.config import DEFAULT_EXTENSIONS, Settings


class ReviewApiEventContractsTests(unittest.TestCase):
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

    def _prepare_layout_reviewed_page(self) -> tuple[int, int]:
        self._write_image("review/reextract.png")
        main.scan_images()
        page_id = int(main.list_pages()["pages"][0]["id"])
        layout = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="text",
                reading_order=1,
                bbox=main.BBoxPayload(x1=0.1, y1=0.1, x2=0.9, y2=0.3),
            ),
        )["layout"]
        main.complete_layout_review(page_id)
        return page_id, int(layout["id"])

    def _prepare_ocr_done_page(self) -> tuple[int, int]:
        page_id, layout_id = self._prepare_layout_reviewed_page()
        now = main._utc_now()
        with db.get_session() as session:
            session.add(
                main.OcrOutput(
                    layout_id=layout_id,
                    page_id=page_id,
                    class_name="text",
                    output_format="markdown",
                    content="ready",
                    model_name="test-model",
                    key_alias="k",
                    created_at=now,
                    updated_at=now,
                )
            )
            page = session.get(main.Page, page_id)
            self.assertIsNotNone(page)
            page.status = "ocr_done"
            page.updated_at = now
        return page_id, layout_id

    def _events_for_page(self, page_id: int, event_type: str) -> list[main.PipelineEvent]:
        with db.get_session() as session:
            return list(
                session.execute(
                    select(main.PipelineEvent)
                    .where(main.PipelineEvent.page_id == page_id)
                    .where(main.PipelineEvent.event_type == event_type)
                    .order_by(main.PipelineEvent.id.asc())
                ).scalars()
            )

    def test_manual_reextract_failure_sets_ocr_failed_and_emits_job_failed_event(self) -> None:
        page_id, layout_id = self._prepare_layout_reviewed_page()

        with patch.object(main, "extract_ocr_for_page", side_effect=RuntimeError("boom")):
            with self.assertRaises(main.HTTPException) as error:
                main.reextract_ocr(
                    page_id,
                    main.ReextractOcrRequest(
                        layout_ids=[layout_id],
                        prompt_template="prompt",
                        temperature=0.11,
                        max_retries_per_layout=2,
                    ),
                )

        self.assertEqual(error.exception.status_code, 400)
        self.assertIn("boom", str(error.exception.detail))

        page = main.page_details(page_id)["page"]
        self.assertEqual(page["status"], "ocr_failed")

        failed_events = self._events_for_page(page_id, "job_failed")
        self.assertGreaterEqual(len(failed_events), 1)
        failed_payload = json.loads(str(failed_events[-1].data_json or "{}"))
        self.assertEqual(failed_payload["trigger"], "manual_reextract")

    def test_manual_reextract_started_event_contains_requested_parameters(self) -> None:
        page_id, layout_id = self._prepare_layout_reviewed_page()
        fake_result = {
            "page_id": page_id,
            "status": "ocr_done",
            "extracted_count": 1,
            "skipped_count": 0,
            "requests_count": 3,
        }
        with patch.object(main, "extract_ocr_for_page", return_value=fake_result):
            payload = main.reextract_ocr(
                page_id,
                main.ReextractOcrRequest(
                    layout_ids=[layout_id],
                    model_name="gemini-2.5-flash",
                    prompt_template="custom prompt",
                    temperature=0.25,
                    max_retries_per_layout=3,
                ),
            )

        self.assertEqual(payload, fake_result)
        started_events = self._events_for_page(page_id, "job_started")
        completed_events = self._events_for_page(page_id, "job_completed")
        self.assertGreaterEqual(len(started_events), 1)
        self.assertGreaterEqual(len(completed_events), 1)

        started_payload = json.loads(str(started_events[-1].data_json or "{}"))
        self.assertEqual(started_payload["trigger"], "manual_reextract")
        self.assertEqual(started_payload["layout_ids"], [layout_id])
        self.assertEqual(started_payload["model_name"], "gemini-2.5-flash")
        self.assertEqual(started_payload["prompt_template"], "custom prompt")
        self.assertEqual(started_payload["temperature"], 0.25)
        self.assertEqual(started_payload["max_retries_per_layout"], 3)

        completed_payload = json.loads(str(completed_events[-1].data_json or "{}"))
        self.assertEqual(completed_payload["trigger"], "manual_reextract")
        self.assertEqual(completed_payload["result"]["requests_count"], 3)

    def test_complete_layout_review_emits_started_and_completed_events(self) -> None:
        self._write_image("review/layout-review-complete-events.png")
        main.scan_images()
        page_id = int(main.list_pages()["pages"][0]["id"])
        main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="text",
                reading_order=1,
                bbox=main.BBoxPayload(x1=0.1, y1=0.1, x2=0.9, y2=0.3),
            ),
        )

        payload = main.complete_layout_review(page_id)
        self.assertEqual(payload["status"], "layout_reviewed")

        started_events = self._events_for_page(page_id, "manual_review_complete_started")
        completed_events = self._events_for_page(page_id, "manual_review_completed")
        self.assertGreaterEqual(len(started_events), 1)
        self.assertGreaterEqual(len(completed_events), 1)
        self.assertIn("requested", str(started_events[-1].message).lower())
        self.assertIn("completed", str(completed_events[-1].message).lower())

    def test_complete_layout_review_completed_event_contains_invalidation_fields(self) -> None:
        page_id, layout_id = self._prepare_layout_reviewed_page()
        now = main._utc_now()
        with db.get_session() as session:
            session.add(
                main.OcrOutput(
                    layout_id=layout_id,
                    page_id=page_id,
                    class_name="text",
                    output_format="markdown",
                    content="seed",
                    model_name="test-model",
                    key_alias="k",
                    created_at=now,
                    updated_at=now,
                )
            )
            page = session.get(main.Page, page_id)
            self.assertIsNotNone(page)
            page.status = "ocr_done"
            page.updated_at = now

        main.patch_layout(
            layout_id,
            main.UpdateLayoutRequest(
                class_name=None,
                reading_order=None,
                bbox=main.BBoxPayload(x1=0.11, y1=0.1, x2=0.9, y2=0.3),
            ),
        )
        payload = main.complete_layout_review(page_id)
        self.assertEqual(payload["status"], "layout_reviewed")
        self.assertEqual(int(payload["ocr_invalidated_count"]), 1)
        self.assertEqual(int(payload["ocr_missing_layout_count"]), 1)

        completed_events = self._events_for_page(page_id, "manual_review_completed")
        self.assertGreaterEqual(len(completed_events), 1)
        completed_payload = json.loads(str(completed_events[-1].data_json or "{}"))
        self.assertEqual(completed_payload["status"], "layout_reviewed")
        self.assertEqual(int(completed_payload["layout_count"]), 1)
        self.assertEqual(int(completed_payload["ocr_invalidated_count"]), 1)
        self.assertEqual(int(completed_payload["ocr_missing_layout_count"]), 1)

    def test_complete_ocr_review_emits_started_and_completed_events(self) -> None:
        page_id, _layout_id = self._prepare_ocr_done_page()

        payload = main.complete_ocr_review(page_id)
        self.assertEqual(payload["status"], "ocr_reviewed")
        self.assertEqual(int(payload["output_count"]), 1)

        started_events = self._events_for_page(page_id, "manual_review_complete_started")
        completed_events = self._events_for_page(page_id, "manual_review_completed")
        self.assertGreaterEqual(len(started_events), 1)
        self.assertGreaterEqual(len(completed_events), 1)
        self.assertIn("ocr review completion requested", str(started_events[-1].message).lower())
        self.assertIn("ocr review completed", str(completed_events[-1].message).lower())

    def test_complete_layout_review_emits_failed_event_when_page_has_no_layouts(self) -> None:
        self._write_image("review/layout-review-no-layouts.png")
        main.scan_images()
        page_id = int(main.list_pages()["pages"][0]["id"])

        with self.assertRaises(main.HTTPException) as error:
            main.complete_layout_review(page_id)
        self.assertEqual(error.exception.status_code, 400)
        self.assertIn("no layouts found", str(error.exception.detail).lower())

        started_events = self._events_for_page(page_id, "manual_review_complete_started")
        failed_events = self._events_for_page(page_id, "manual_review_complete_failed")
        self.assertGreaterEqual(len(started_events), 1)
        self.assertGreaterEqual(len(failed_events), 1)
        self.assertIn("requested", str(started_events[-1].message).lower())
        self.assertIn("failed", str(failed_events[-1].message).lower())

    def test_complete_ocr_review_emits_failed_event_when_outputs_missing(self) -> None:
        page_id, _layout_id = self._prepare_layout_reviewed_page()
        with db.get_session() as session:
            page = session.get(main.Page, page_id)
            self.assertIsNotNone(page)
            page.status = "ocr_done"
            page.updated_at = main._utc_now()

        with self.assertRaises(main.HTTPException) as error:
            main.complete_ocr_review(page_id)
        self.assertEqual(error.exception.status_code, 400)
        self.assertIn("no ocr outputs found", str(error.exception.detail).lower())

        started_events = self._events_for_page(page_id, "manual_review_complete_started")
        failed_events = self._events_for_page(page_id, "manual_review_complete_failed")
        self.assertGreaterEqual(len(started_events), 1)
        self.assertGreaterEqual(len(failed_events), 1)
        self.assertIn("ocr review completion requested", str(started_events[-1].message).lower())
        self.assertIn("failed", str(failed_events[-1].message).lower())

    def test_final_export_emits_started_and_completed_events(self) -> None:
        fake_export = {
            "export_dir": "/tmp/export-x",
            "metadata_file": "/tmp/export-x/metadata.jsonl",
            "page_count": 2,
            "image_count": 2,
            "reconstructed_count": 2,
        }
        with patch("app.api.review.export_final_dataset", return_value=fake_export):
            payload = main.run_final_export(main.FinalExportRequest(confirm=True))
        self.assertEqual(payload, fake_export)

        with db.get_session() as session:
            started = session.execute(
                select(main.PipelineEvent)
                .where(main.PipelineEvent.event_type == "export_started")
                .order_by(main.PipelineEvent.id.desc())
                .limit(1)
            ).scalar_one()
            completed = session.execute(
                select(main.PipelineEvent)
                .where(main.PipelineEvent.event_type == "export_completed")
                .order_by(main.PipelineEvent.id.desc())
                .limit(1)
            ).scalar_one()

        self.assertIn("started", str(started.message).lower())
        completed_payload = json.loads(str(completed.data_json or "{}"))
        self.assertEqual(completed_payload["page_count"], 2)
        self.assertEqual(completed_payload["image_count"], 2)
        self.assertEqual(completed_payload["reconstructed_count"], 2)

    def test_final_export_emits_failed_event_on_value_error(self) -> None:
        with patch("app.api.review.export_final_dataset", side_effect=ValueError("nothing to export")):
            with self.assertRaises(main.HTTPException) as error:
                main.run_final_export(main.FinalExportRequest(confirm=True))

        self.assertEqual(error.exception.status_code, 400)
        self.assertIn("nothing to export", str(error.exception.detail))

        with db.get_session() as session:
            failed = session.execute(
                select(main.PipelineEvent)
                .where(main.PipelineEvent.event_type == "export_failed")
                .order_by(main.PipelineEvent.id.desc())
                .limit(1)
            ).scalar_one()
        self.assertIn("failed", str(failed.message).lower())


if __name__ == "__main__":
    unittest.main()
