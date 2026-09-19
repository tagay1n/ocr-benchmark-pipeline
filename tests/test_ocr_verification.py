from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
import json
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

    def test_primary_pool_is_first_and_fallback_is_ordered_deduplicated(self) -> None:
        configured = replace(
            self.settings,
            ocr_verification_models=("source-model", "validator-a", "validator-a", "validator-b"),
            ocr_verification_fallback_models=("validator-b", "fallback-a", "fallback-a", "fallback-b"),
        )
        with patch.object(ocr_verification, "settings", configured):
            self.assertEqual(ocr_verification.verification_models(), ("source-model", "validator-a", "validator-b"))
            self.assertEqual(ocr_verification.fallback_models(), ("validator-b", "fallback-a", "fallback-b"))
            self.assertEqual(
                ocr_verification.validator_candidates("source-model"),
                ("validator-a", "validator-b", "fallback-a", "fallback-b"),
            )
            self.assertEqual(ocr_verification.select_validator_models("source-model"), ("validator-a", "validator-b"))

    def test_third_transient_failure_unavailable_and_schedules_fallback(self) -> None:
        configured = replace(self.settings, ocr_verification_fallback_models=("fallback-a",))
        with patch.object(ocr_verification, "settings", configured):
            ocr_verification.start_verification()
            task = self._tasks()[0]
            with patch.object(
                ocr_verification,
                "gemini_generate_content",
                side_effect=RuntimeError("Gemini request failed with HTTP 503: overloaded"),
            ):
                self.assertEqual(ocr_verification._execute_task(task.id), "waiting")
                self.assertEqual(ocr_verification._execute_task(task.id), "waiting")
                self.assertEqual(ocr_verification._execute_task(task.id), "waiting")
            rows = self._tasks()
            self.assertEqual(rows[0].status, "unavailable")
            self.assertEqual(rows[0].transient_count, 3)
            self.assertEqual([(row.model_name, row.status) for row in rows], [
                ("validator-a", "unavailable"), ("validator-b", "pending"), ("fallback-a", "pending"),
            ])

    def test_resume_replaces_persisted_unavailable_or_three_transient_task(self) -> None:
        configured = replace(self.settings, ocr_verification_fallback_models=("fallback-a", "fallback-b"))
        with patch.object(ocr_verification, "settings", configured):
            ocr_verification.start_verification()
            first, second = self._tasks()
            with db.get_session() as session:
                session.get(main.OcrVerificationTask, first.id).status = "waiting"
                session.get(main.OcrVerificationTask, first.id).transient_count = 3
                session.get(main.OcrVerificationTask, second.id).status = "unavailable"
            ocr_verification.request_verification_stop()
            resumed = ocr_verification.start_verification()
            self.assertTrue(resumed["started"])
            self.assertEqual(
                [(row.model_name, row.status) for row in self._tasks()],
                [("validator-a", "unavailable"), ("validator-b", "unavailable"), ("fallback-a", "pending"), ("fallback-b", "pending")],
            )

    def test_fallback_successes_are_full_evidence_and_detail_variants(self) -> None:
        configured = replace(self.settings, ocr_verification_models=("validator-a",), ocr_verification_fallback_models=("fallback-a", "fallback-b"))
        with patch.object(ocr_verification, "settings", configured):
            ocr_verification.start_verification()
            initial = self._tasks()[0]
            with db.get_session() as session:
                session.get(main.OcrVerificationTask, initial.id).status = "unavailable"
            ocr_verification._schedule_replacements(self.layout_id, int(initial.run_id))
            tasks = self._tasks()
            with db.get_session() as session:
                for task in tasks[1:]:
                    row = session.get(main.OcrVerificationTask, task.id)
                    row.status = "succeeded"
                    row.content = "Fallback result" if task.model_name == "fallback-a" else "Other fallback result"
            finding = ocr_verification.refresh_finding(self.layout_id)
            self.assertEqual(finding["state"], "disagreement_full")
            self.assertEqual(finding["responded_count"], 2)
            self.assertEqual(finding["required_count"], 2)
            self.assertEqual({task["model_name"] for task in finding["tasks"]}, {"validator-a", "fallback-a", "fallback-b"})

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

    def test_extraction_reuses_full_resolution_crop_and_invalidates_edits(self) -> None:
        ocr_verification.start_verification()
        tasks = self._tasks()
        with patch.object(ocr_verification, "_crop_layout_png_bytes", wraps=ocr_verification._crop_layout_png_bytes) as crop:
            first = ocr_verification._task_inputs(tasks[0].id)[-1]
            self.assertEqual(ocr_verification._task_inputs(tasks[1].id)[-1], first)
            self.assertEqual(crop.call_count, 1)
            with db.get_session() as session:
                session.get(main.Layout, self.layout_id).x1 = 0.2
            ocr_verification._task_inputs(tasks[0].id)
            self.assertEqual(crop.call_count, 2)
            Image.new("RGB", (300, 200), "black").save(self.settings.source_dir / "page.png")
            ocr_verification._task_inputs(tasks[0].id)
            self.assertEqual(crop.call_count, 3)

    def test_extraction_crop_cache_is_bounded_and_preserves_orientation(self) -> None:
        ocr_verification._EXTRACTION_CROP_CACHE.clear()
        path = self.settings.source_dir / "page.png"
        bbox = {"x1": 0.1, "y1": 0.1, "x2": 0.9, "y2": 0.8}
        with patch.object(ocr_verification, "_EXTRACTION_CROP_CACHE_BYTES", 5), patch.object(
            ocr_verification, "_crop_layout_png_bytes", side_effect=[b"aaa", b"bbb", b"cccccc", b"ddd"]
        ) as crop:
            self.assertEqual(ocr_verification._cached_extraction_crop(path, bbox), b"aaa")
            self.assertEqual(ocr_verification._cached_extraction_crop(path, bbox, rotate_for_vertical=True), b"bbb")
            self.assertEqual(ocr_verification._cached_extraction_crop(path, bbox), b"cccccc")
            self.assertEqual(ocr_verification._cached_extraction_crop(path, bbox), b"ddd")
            self.assertEqual(crop.call_count, 4)
            self.assertLessEqual(sum(map(len, ocr_verification._EXTRACTION_CROP_CACHE.values())), 5)

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

    def test_scheduler_finishes_untouched_pass_before_retries(self) -> None:
        run_id = int(ocr_verification.start_verification()["run_id"])
        older, fresh = self._tasks()
        for counter in ("attempts", "transient_count"):
            with self.subTest(counter=counter):
                with db.get_session() as session:
                    row = session.get(main.OcrVerificationTask, older.id)
                    row.attempts = 0
                    row.transient_count = 0
                    setattr(row, counter, 1)
                    row.status = "waiting"
                self.assertEqual(ocr_verification._claim_ready_task(run_id), fresh.id)
                with db.get_session() as session:
                    row = session.get(main.OcrVerificationTask, fresh.id)
                    row.status = "waiting"
                    row.error_message = "Shared model cooldown"
                    row.next_retry_at = "2999-01-01T00:00:00+00:00"
                self.assertIsNone(ocr_verification._claim_ready_task(run_id))
                with db.get_session() as session:
                    row = session.get(main.OcrVerificationTask, fresh.id)
                    row.next_retry_at = None
        for terminal in ("succeeded", "unavailable"):
            with db.get_session() as session:
                session.get(main.OcrVerificationTask, fresh.id).status = terminal
            self.assertEqual(ocr_verification._claim_ready_task(run_id), older.id)
        with db.get_session() as session:
            session.get(main.OcrVerificationTask, fresh.id).status = "pending"
            session.get(main.OcrVerificationTask, fresh.id).attempts = 1
        self.assertIsNotNone(ocr_verification._claim_ready_task(run_id))

    def test_scheduler_orders_retries_by_failure_count_then_age_then_id(self) -> None:
        run_id = int(ocr_verification.start_verification()["run_id"])
        older, newer = self._tasks()
        with db.get_session() as session:
            session.get(main.OcrVerificationTask, older.id).transient_count = 618
            session.get(main.OcrVerificationTask, newer.id).attempts = 1
        self.assertEqual(ocr_verification._claim_ready_task(run_id), newer.id)
        with db.get_session() as session:
            row = session.get(main.OcrVerificationTask, older.id)
            row.transient_count = 1
            row.updated_at = "2026-01-02T00:00:00+00:00"
            session.get(main.OcrVerificationTask, newer.id).updated_at = "2026-01-01T00:00:00+00:00"
        self.assertEqual(ocr_verification._claim_ready_task(run_id), newer.id)
        with db.get_session() as session:
            session.get(main.OcrVerificationTask, older.id).updated_at = "2026-01-01T00:00:00+00:00"
        self.assertEqual(ocr_verification._claim_ready_task(run_id), older.id)
        with db.get_session() as session:
            session.get(main.OcrVerificationTask, older.id).next_retry_at = "2999-01-01T00:00:00+00:00"
        self.assertEqual(ocr_verification._claim_ready_task(run_id), newer.id)

    def test_resume_preserves_cooldowns_and_retry_priority(self) -> None:
        ocr_verification.start_verification()
        retry, untouched = self._tasks()
        deadline = "2999-01-01T00:00:00+00:00"
        with db.get_session() as session:
            for task in (retry, untouched):
                row = session.get(main.OcrVerificationTask, task.id)
                row.status = "waiting"
                row.next_retry_at = deadline
            session.get(main.OcrVerificationTask, retry.id).transient_count = 2
        ocr_verification.request_verification_stop()
        run_id = int(ocr_verification.start_verification()["run_id"])
        for task in self._tasks():
            self.assertEqual(task.next_retry_at, deadline)
            self.assertEqual(task.run_id, run_id)
            self.assertEqual(task.transient_count, 2 if task.id == retry.id else 0)
        self.assertIsNone(ocr_verification._claim_ready_task(run_id))
        with patch.object(ocr_verification.time, "sleep", side_effect=lambda _: ocr_verification.request_verification_stop()), patch.object(
            ocr_verification, "_execute_task"
        ) as execute:
            ocr_verification._worker_loop(run_id)
        execute.assert_not_called()
        self.assertEqual(ocr_verification.verification_status()["run"]["status"], "stopped")

    def test_attempt_log_records_each_request_including_key_rotation(self) -> None:
        started = ocr_verification.start_verification()
        task = self._tasks()[0]
        with patch.object(ocr_verification, "gemini_generate_content", side_effect=[
            RuntimeError("HTTP 429 rate limit key-a secret-response"), "Reviewed text"
        ]), patch.object(ocr_verification.time, "monotonic", side_effect=[10, 12, 20, 23]):
            self.assertEqual(ocr_verification._execute_task(task.id), "succeeded")
        path = self.root / "_artifacts" / "ocr_verification_attempts" / f"run_{started['run_id']}.jsonl"
        raw = path.read_text()
        records = [json.loads(line) for line in raw.splitlines()]
        self.assertEqual([row["outcome"] for row in records], ["rate_limit", "success"])
        self.assertEqual([row["duration_ms"] for row in records], [2000, 3000])
        self.assertEqual(records[0]["http_status"], 429)
        for row in records:
            self.assertEqual(row["task_id"], task.id)
            self.assertEqual(row["model_name"], task.model_name)
            self.assertIn("started_at", row)
            self.assertIn("finished_at", row)
        for secret in ("key-a", "key-b", "secret-response", "Reviewed text"):
            self.assertNotIn(secret, raw)

    def test_attempt_log_categorizes_failures_and_preserves_exceptions(self) -> None:
        ocr_verification.start_verification()
        task = self._tasks()[0]
        for message, category in [
            ("The read operation timed out", "timeout"),
            ("HTTP 503 overloaded", "server_error"),
            ("HTTP 429 requests per day quota", "daily_quota"),
            ("Gemini response is not valid JSON: Extra data.", "invalid_response"),
            ("Gemini request returned an empty response.", "invalid_response"),
            ("HTTP 403 forbidden", "request_error"),
            ("Remote end closed connection without response", "other_error"),
        ]:
            error = RuntimeError(message)
            with patch.object(ocr_verification, "gemini_generate_content", side_effect=error):
                with self.assertRaises(RuntimeError) as raised:
                    ocr_verification._generate_verification_content(task, "key-a", "prompt", b"image")
            self.assertIs(raised.exception, error)
            path = self.root / "_artifacts" / "ocr_verification_attempts" / f"run_{task.run_id}.jsonl"
            self.assertEqual(json.loads(path.read_text().splitlines()[-1])["outcome"], category)

    def test_attempt_logging_failure_does_not_fail_extraction(self) -> None:
        ocr_verification.start_verification()
        task = self._tasks()[0]
        with patch.object(ocr_verification, "gemini_generate_content", return_value="Reviewed text"), patch.object(
            Path, "open", side_effect=OSError("Disk full secret-data")
        ), self.assertLogs(ocr_verification.__name__, level="WARNING") as logs:
            result = ocr_verification._generate_verification_content(task, "key-a", "prompt", b"image")
        self.assertEqual(result, "Reviewed text")
        self.assertNotIn("secret-data", " ".join(logs.output))

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

    def test_worker_keeps_processing_after_one_task_waits_for_quota(self) -> None:
        started = ocr_verification.start_verification()
        tasks = self._tasks()
        processed: list[int] = []

        def execute(task_id: int) -> str:
            processed.append(task_id)
            return "quota_wait" if task_id == int(tasks[0].id) else "succeeded"

        with patch.object(
            ocr_verification,
            "_claim_ready_task",
            side_effect=[int(tasks[0].id), int(tasks[1].id), None],
        ), patch.object(
            ocr_verification,
            "_execute_task",
            side_effect=execute,
        ), patch.object(
            ocr_verification,
            "_has_active_tasks",
            return_value=False,
        ), patch.object(
            ocr_verification,
            "_finish_run",
        ) as finish, patch.object(
            ocr_verification,
            "request_verification_stop",
        ) as stop:
            ocr_verification._worker_loop(int(started["run_id"]))

        self.assertEqual(processed, [int(tasks[0].id), int(tasks[1].id)])
        stop.assert_not_called()
        finish.assert_called_once_with(int(started["run_id"]), stopped=False)

    def test_quota_cooldown_shares_longest_retry_delay_without_touching_sibling_counters(self) -> None:
        run_id = ocr_verification.start_verification()["run_id"]
        tasks = self._tasks()
        with db.get_session() as session:
            session.get(main.OcrVerificationTask, tasks[1].id).model_name = tasks[0].model_name
        with patch.object(ocr_verification, "gemini_generate_content", side_effect=[
            RuntimeError('HTTP 429 {"error":{"details":[{"retryDelay":"120s"}]}}'),
            RuntimeError('HTTP 429 {"error":{"details":[{"retryDelay":"30s"}]}}'),
        ]):
            self.assertEqual(ocr_verification._execute_task(tasks[0].id), "quota_wait")
        from datetime import datetime, UTC
        with db.get_session() as session:
            first = session.get(main.OcrVerificationTask, tasks[0].id)
            sibling = session.get(main.OcrVerificationTask, tasks[1].id)
            self.assertGreater((datetime.fromisoformat(first.next_retry_at) - datetime.now(UTC)).total_seconds(), 110)
            self.assertEqual(first.next_retry_at, sibling.next_retry_at)
            self.assertEqual(sibling.transient_count, 0)
            self.assertEqual(sibling.attempts, 0)
        self.assertIsNone(ocr_verification._claim_ready_task(run_id))

    def test_rate_limited_key_is_skipped_on_next_task_for_same_model(self) -> None:
        ocr_verification.start_verification()
        first, second = self._tasks()
        with db.get_session() as session:
            session.get(main.OcrVerificationTask, second.id).model_name = first.model_name
        calls = []
        def generate(key, *args, **kwargs):
            calls.append(key)
            if len(calls) == 1:
                raise RuntimeError('HTTP 429 {"retryDelay":"120s"}')
            return "Reviewed text"
        with patch.object(ocr_verification, "gemini_generate_content", side_effect=generate):
            self.assertEqual(ocr_verification._execute_task(first.id), "succeeded")
            self.assertEqual(ocr_verification._execute_task(second.id), "succeeded")
        self.assertEqual(len(calls), 3)
        self.assertNotEqual(calls[0], calls[1])
        self.assertEqual(calls[1], calls[2])

    def test_removing_exhaustion_file_unblocks_model_without_daily_timer(self) -> None:
        run_id = ocr_verification.start_verification()["run_id"]
        first, second = self._tasks()
        ocr_extract._save_usage_state(list(self.settings.gemini_keys), model_name=first.model_name)
        self.assertEqual(ocr_verification._execute_task(first.id), "quota_wait")
        self.assertEqual(ocr_verification._claim_ready_task(run_id), second.id)
        with db.get_session() as session:
            session.get(main.OcrVerificationTask, second.id).status = "succeeded"
        self.assertIsNone(ocr_verification._claim_ready_task(run_id))
        Path(self.settings.gemini_usage_path).unlink()
        self.assertEqual(ocr_verification._claim_ready_task(run_id), first.id)
        with patch.object(ocr_verification, "gemini_generate_content", return_value="Reviewed text"):
            self.assertEqual(ocr_verification._execute_task(first.id), "succeeded")

    def test_temporary_rate_limits_defer_only_the_current_task(self) -> None:
        ocr_verification.start_verification()
        tasks = self._tasks()
        with patch.object(
            ocr_verification,
            "gemini_generate_content",
            side_effect=RuntimeError("HTTP 429 rate limit reached"),
        ):
            result = ocr_verification._execute_task(int(tasks[0].id))

        self.assertEqual(result, "quota_wait")
        self.assertEqual(ocr_extract._load_usage_state(model_name="validator-a"), [])
        with db.get_session() as session:
            limited = session.get(main.OcrVerificationTask, int(tasks[0].id))
            unaffected = session.get(main.OcrVerificationTask, int(tasks[1].id))
            self.assertEqual(limited.status, "waiting")
            self.assertIn("rate limit reached", str(limited.error_message))
            self.assertIsNotNone(limited.next_retry_at)
            self.assertEqual(unaffected.status, "pending")
            self.assertIsNone(unaffected.next_retry_at)

    def test_daily_exhaustion_defers_only_the_affected_model(self) -> None:
        ocr_verification.start_verification()
        tasks = self._tasks()
        ocr_extract._save_usage_state(
            list(self.settings.gemini_keys),
            model_name="validator-a",
        )

        with patch.object(ocr_verification, "gemini_generate_content") as generate:
            result = ocr_verification._execute_task(int(tasks[0].id))

        self.assertEqual(result, "quota_wait")
        generate.assert_not_called()
        with db.get_session() as session:
            exhausted = session.get(main.OcrVerificationTask, int(tasks[0].id))
            unaffected = session.get(main.OcrVerificationTask, int(tasks[1].id))
            run = session.get(main.OcrVerificationRun, int(exhausted.run_id))
            self.assertEqual(exhausted.status, "waiting")
            self.assertIn("exhausted for today", str(exhausted.error_message))
            self.assertIsNone(exhausted.next_retry_at)
            self.assertEqual(unaffected.status, "pending")
            self.assertIsNone(unaffected.next_retry_at)
            self.assertEqual(run.status, "running")
            self.assertFalse(run.stop_requested)

    def test_worker_stops_when_all_remaining_models_are_daily_quota_exhausted(self) -> None:
        started = ocr_verification.start_verification()
        tasks = self._tasks()
        with db.get_session() as session:
            first = session.get(main.OcrVerificationTask, int(tasks[0].id))
            first.status = "waiting"
            first.error_message = "Daily quota exhausted"
            first.transient_count = 1
        for model_name in ("validator-a", "validator-b"):
            ocr_extract._save_usage_state(
                list(self.settings.gemini_keys),
                model_name=model_name,
            )

        with patch.object(
            ocr_verification.time,
            "sleep",
            side_effect=AssertionError("daily exhaustion must not leave the worker polling"),
        ), patch.object(ocr_verification, "_execute_task") as execute:
            ocr_verification._worker_loop(int(started["run_id"]))

        execute.assert_not_called()
        status = ocr_verification.verification_status()
        self.assertFalse(status["is_running"])
        self.assertEqual(status["run"]["status"], "quota_exhausted")
        preserved = self._tasks()
        self.assertEqual([task.status for task in preserved], ["waiting", "pending"])
        self.assertEqual([task.transient_count for task in preserved], [1, 0])
        self.assertEqual(preserved[0].error_message, "Daily quota exhausted")

        Path(self.settings.gemini_usage_path).unlink()
        resumed = ocr_verification.start_verification()
        self.assertTrue(resumed["started"])
        self.assertEqual(
            [task.run_id for task in self._tasks()],
            [int(resumed["run_id"]), int(resumed["run_id"])],
        )

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
