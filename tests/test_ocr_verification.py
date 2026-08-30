from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch

from PIL import Image
from sqlalchemy import select
from starlette.requests import Request

from app import config, db, discovery, final_export, layouts, main, ocr_extract, ocr_verification, runtime_options
from app.api.verification import get_ocr_verification_crop
from app.config import DEFAULT_EXTENSIONS, Settings


class OcrVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.settings = Settings(
            project_root=self.root,
            source_dir=self.root / "input",
            db_path=self.root / "data" / "test.db",
            result_dir=self.root / "result",
            allowed_extensions=DEFAULT_EXTENSIONS,
            enable_background_jobs=False,
            gemini_keys=("key-a", "key-b"),
            gemini_usage_path=self.root / "usage.json",
            supported_ocr_models=("source-model", "validator-a", "validator-b"),
            ocr_verification_models=("source-model", "validator-a", "validator-b"),
            ocr_verification_total_models=3,
            ocr_verification_attempts_per_model=2,
            ocr_verification_prompt_version=1,
        )
        self.settings.source_dir.mkdir(parents=True)
        self.stack = ExitStack()
        for module in (
            config,
            db,
            discovery,
            final_export,
            layouts,
            main,
            ocr_extract,
            ocr_verification,
            runtime_options,
        ):
            self.stack.enter_context(patch.object(module, "settings", self.settings))
        db.init_db()
        runtime_options.reset_runtime_options_from_settings()
        self.page_id, self.layout_id = self._create_reviewed_region()

    def tearDown(self) -> None:
        self.stack.close()
        self.temp_dir.cleanup()

    def _create_reviewed_region(self) -> tuple[int, int]:
        image_path = self.settings.source_dir / "page.png"
        Image.new("RGB", (240, 120), "white").save(image_path)
        now = main._utc_now()
        with db.get_session() as session:
            page = main.Page(
                rel_path="page.png",
                file_hash="file-hash",
                status="ocr_reviewed",
                layout_order_mode="auto",
                qa_bbox_status="reviewed",
                qa_class_status="reviewed",
                qa_order_status="reviewed",
                qa_ocr_status="reviewed",
                created_at=now,
                updated_at=now,
                last_seen_at=now,
                is_missing=False,
            )
            session.add(page)
            session.flush()
            layout = main.Layout(
                page_id=int(page.id),
                class_name="text",
                x1=0.1,
                y1=0.1,
                x2=0.9,
                y2=0.8,
                reading_order=1,
                orientation="horizontal",
                confidence=None,
                source="manual",
                created_at=now,
                updated_at=now,
            )
            session.add(layout)
            session.flush()
            session.add(
                main.OcrOutput(
                    layout_id=int(layout.id),
                    page_id=int(page.id),
                    class_name="text",
                    output_format="markdown",
                    content="Reviewed text",
                    model_name="source-model",
                    key_alias="source-key",
                    extraction_status="manual",
                    error_message=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            return int(page.id), int(layout.id)

    def _tasks(self):
        with db.get_session() as session:
            return session.execute(
                select(main.OcrVerificationTask).order_by(main.OcrVerificationTask.id.asc())
            ).scalars().all()

    def test_start_selects_two_models_and_excludes_original(self) -> None:
        result = ocr_verification.start_verification()
        self.assertTrue(result["started"])
        self.assertEqual(result["total_tasks"], 2)
        self.assertEqual([task.model_name for task in self._tasks()], ["validator-a", "validator-b"])

    def test_full_and_reduced_comparison_states(self) -> None:
        ocr_verification.start_verification()
        tasks = self._tasks()
        now = main._utc_now()
        with db.get_session() as session:
            for task in tasks:
                row = session.get(main.OcrVerificationTask, int(task.id))
                row.status = "succeeded"
                row.content = "Reviewed text"
                row.finished_at = now
                row.updated_at = now
        finding = ocr_verification.refresh_finding(self.layout_id)
        self.assertEqual(finding["state"], "agreed_full")
        self.assertEqual(len(finding["groups"]), 1)

        with db.get_session() as session:
            second = session.get(main.OcrVerificationTask, int(tasks[1].id))
            second.content = "Reviewed text with invented ending"
        finding = ocr_verification.refresh_finding(self.layout_id)
        self.assertEqual(finding["state"], "disagreement_full")
        self.assertEqual(len(finding["groups"]), 2)

        with db.get_session() as session:
            second = session.get(main.OcrVerificationTask, int(tasks[1].id))
            second.status = "unavailable"
            second.content = None
        finding = ocr_verification.refresh_finding(self.layout_id)
        self.assertEqual(finding["state"], "agreed_reduced")
        self.assertEqual(finding["responded_count"], 1)

    def test_no_validator_response_requires_manual_check(self) -> None:
        ocr_verification.start_verification()
        with db.get_session() as session:
            for task in session.execute(select(main.OcrVerificationTask)).scalars():
                task.status = "unavailable"
                task.error_message = "No response"
        finding = ocr_verification.refresh_finding(self.layout_id)
        self.assertEqual(finding["state"], "manual_check")
        self.assertEqual(len(finding["groups"]), 1)
        self.assertEqual(finding["groups"][0]["content"], "Reviewed text")

    def test_listing_findings_does_not_recalculate_all_findings(self) -> None:
        ocr_verification.start_verification()

        with patch.object(
            ocr_verification,
            "recalculate_findings",
            side_effect=AssertionError("read endpoint must not recalculate findings"),
        ):
            payload = ocr_verification.list_findings(limit=50)

        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["findings"][0]["layout_id"], self.layout_id)

    def test_listing_findings_filters_server_side_and_returns_compact_page(self) -> None:
        ocr_verification.start_verification()

        payload = ocr_verification.list_findings(category="waiting", limit=1, offset=0)

        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["limit"], 1)
        summary = payload["findings"][0]
        self.assertEqual(summary["state"], "waiting")
        self.assertNotIn("groups", summary)
        self.assertNotIn("tasks", summary)
        self.assertNotIn("baseline_content", summary)

        empty = ocr_verification.list_findings(category="attention", limit=1, offset=0)
        self.assertEqual(empty["total"], 0)
        self.assertEqual(empty["findings"], [])

    def test_finding_detail_contains_variants_and_tasks(self) -> None:
        ocr_verification.start_verification()

        detail = ocr_verification.get_finding_detail(self.layout_id)

        self.assertEqual(detail["layout_id"], self.layout_id)
        self.assertEqual(detail["baseline_content"], "Reviewed text")
        self.assertEqual(len(detail["groups"]), 1)
        self.assertEqual(len(detail["tasks"]), 2)

    def test_verification_crop_returns_png_with_stable_version(self) -> None:
        ocr_verification.start_verification()

        with patch.object(
            ocr_verification,
            "_crop_layout_png_bytes",
            wraps=ocr_verification._crop_layout_png_bytes,
        ) as generate_crop:
            crop, version = ocr_verification.verification_crop(self.layout_id)
            cached_crop, cached_version = ocr_verification.verification_crop(self.layout_id)

        self.assertTrue(crop.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertGreater(len(crop), 50)
        self.assertEqual(len(version), 64)
        self.assertEqual(cached_crop, crop)
        self.assertEqual(cached_version, version)
        self.assertEqual(generate_crop.call_count, 1)

        request = Request({"type": "http", "headers": []})
        response = get_ocr_verification_crop(self.layout_id, request)
        self.assertEqual(response.media_type, "image/png")
        self.assertIn("max-age=86400", response.headers["cache-control"])
        self.assertEqual(response.headers["etag"], f'"{version}"')

    def test_status_uses_persisted_run_progress(self) -> None:
        started = ocr_verification.start_verification()
        with db.get_session() as session:
            run = session.get(main.OcrVerificationRun, int(started["run_id"]))
            run.total_tasks = 11
            run.completed_tasks = 7

        status = ocr_verification.verification_status()

        self.assertEqual(status["run"]["total_tasks"], 11)
        self.assertEqual(status["run"]["completed_tasks"], 7)

    def test_start_reuses_page_layout_context_for_regions_on_same_page(self) -> None:
        now = main._utc_now()
        with db.get_session() as session:
            layout = main.Layout(
                page_id=self.page_id,
                class_name="text",
                x1=0.1,
                y1=0.81,
                x2=0.9,
                y2=0.95,
                reading_order=2,
                orientation="horizontal",
                confidence=None,
                source="manual",
                created_at=now,
                updated_at=now,
            )
            session.add(layout)
            session.flush()
            session.add(
                main.OcrOutput(
                    layout_id=int(layout.id),
                    page_id=self.page_id,
                    class_name="text",
                    output_format="markdown",
                    content="Second region",
                    model_name="source-model",
                    key_alias="source-key",
                    extraction_status="manual",
                    error_message=None,
                    created_at=now,
                    updated_at=now,
                )
            )

        original_fetch = ocr_verification._fetch_page_layouts
        with patch.object(
            ocr_verification,
            "_fetch_page_layouts",
            wraps=original_fetch,
        ) as fetch_layouts:
            result = ocr_verification.start_verification()

        self.assertEqual(result["total_tasks"], 4)
        self.assertEqual(fetch_layouts.call_count, 1)

    def test_recalculation_can_run_in_background_and_reports_status(self) -> None:
        entered = Event()
        release = Event()

        def slow_recalculation():
            entered.set()
            release.wait(timeout=2)
            return {"refreshed": 1}

        with patch.object(
            ocr_verification,
            "recalculate_findings",
            side_effect=slow_recalculation,
        ):
            result = ocr_verification.request_findings_recalculation()
            self.assertTrue(result["started"])
            self.assertTrue(entered.wait(timeout=1))
            self.assertTrue(ocr_verification.verification_status()["recalculation_running"])
            release.set()
            thread = ocr_verification._RECALCULATION_THREAD
            if thread is not None:
                thread.join(timeout=2)

        self.assertFalse(ocr_verification.verification_status()["recalculation_running"])

    def test_stop_classifies_pending_models_from_available_evidence_and_resume_reactivates(self) -> None:
        ocr_verification.start_verification()
        stopped = ocr_verification.request_verification_stop()
        self.assertTrue(stopped["stop_requested"])
        finding = ocr_verification.refresh_finding(self.layout_id)
        self.assertEqual(finding["state"], "manual_check")

        resumed = ocr_verification.start_verification()
        self.assertTrue(resumed["started"])
        finding = ocr_verification.refresh_finding(self.layout_id)
        self.assertEqual(finding["state"], "waiting")

    def test_503_defers_without_consuming_attempt(self) -> None:
        ocr_verification.start_verification()
        task = self._tasks()[0]
        with patch.object(
            ocr_verification,
            "gemini_generate_content",
            side_effect=RuntimeError("Gemini request failed with HTTP 503: overloaded"),
        ):
            result = ocr_verification._execute_task(int(task.id))
        self.assertEqual(result, "waiting")
        with db.get_session() as session:
            row = session.get(main.OcrVerificationTask, int(task.id))
            self.assertEqual(row.status, "waiting")
            self.assertEqual(row.attempts, 0)
            self.assertEqual(row.transient_count, 1)
            self.assertIsNotNone(row.next_retry_at)

    def test_worker_persists_each_model_and_completes_full_agreement(self) -> None:
        started = ocr_verification.start_verification()
        with patch.object(
            ocr_verification,
            "gemini_generate_content",
            return_value="Reviewed text",
        ) as generate:
            ocr_verification._worker_loop(int(started["run_id"]))
        self.assertEqual(generate.call_count, 2)
        status = ocr_verification.verification_status()
        self.assertFalse(status["is_running"])
        self.assertEqual(status["run"]["status"], "completed")
        finding = ocr_verification.refresh_finding(self.layout_id)
        self.assertEqual(finding["state"], "agreed_full")

    def test_two_counted_failures_make_only_that_model_unavailable(self) -> None:
        ocr_verification.start_verification()
        task = self._tasks()[0]
        with patch.object(
            ocr_verification,
            "gemini_generate_content",
            side_effect=RuntimeError("Gemini response is not valid JSON: bad output"),
        ):
            self.assertEqual(ocr_verification._execute_task(int(task.id)), "failed_attempt")
            self.assertEqual(ocr_verification._execute_task(int(task.id)), "failed_attempt")
        with db.get_session() as session:
            row = session.get(main.OcrVerificationTask, int(task.id))
            self.assertEqual(row.status, "unavailable")
            self.assertEqual(row.attempts, 2)

    def test_apply_resolution_preserves_page_and_qa_statuses(self) -> None:
        ocr_verification.start_verification()
        with db.get_session() as session:
            for task in session.execute(select(main.OcrVerificationTask)).scalars():
                task.status = "unavailable"
        ocr_verification.refresh_finding(self.layout_id)
        result = ocr_verification.resolve_finding(
            self.layout_id,
            action="apply",
            content="Corrected text",
        )
        self.assertTrue(result["resolved"])
        with db.get_session() as session:
            output = session.get(main.OcrOutput, self.layout_id)
            page = session.get(main.Page, self.page_id)
            self.assertEqual(output.content, "Corrected text")
            self.assertEqual(page.status, "ocr_reviewed")
            self.assertEqual(page.qa_ocr_status, "reviewed")


if __name__ == "__main__":
    unittest.main()
