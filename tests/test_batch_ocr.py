from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from sqlalchemy import select

from app import config, db, discovery, final_export, layouts, main, ocr_extract, pipeline_runtime, runtime_options
from app.config import DEFAULT_EXTENSIONS, Settings


class BatchOcrApiTests(unittest.TestCase):
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
            gemini_keys=("k1",),
            gemini_usage_path=self.project_root / "_artifacts" / "gemini_usage.json",
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

    def _page_id_by_rel_path(self, rel_path: str) -> int:
        pages = main.list_pages()["pages"]
        for page in pages:
            if str(page["rel_path"]) == rel_path:
                return int(page["id"])
        raise AssertionError(f"Page {rel_path} not found.")

    def _add_text_layout(self, page_id: int, reading_order: int) -> int:
        payload = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="text",
                reading_order=reading_order,
                bbox=main.BBoxPayload(x1=0.1, y1=0.1, x2=0.9, y2=0.3),
            ),
        )
        return int(payload["layout"]["id"])

    def _set_page_status(self, page_id: int, status: str) -> None:
        now = main._utc_now()
        with db.get_session() as session:
            page_row = session.get(main.Page, page_id)
            self.assertIsNotNone(page_row)
            page_row.status = status
            page_row.updated_at = now

    def test_batch_ocr_run_queues_only_missing_layout_outputs(self) -> None:
        self._write_image("batch/p1.png", b"page-1")
        self._write_image("batch/p2.png", b"page-2")
        self._write_image("batch/p3.png", b"page-3")
        main.scan_images()

        page1 = self._page_id_by_rel_path("batch/p1.png")
        page2 = self._page_id_by_rel_path("batch/p2.png")
        page3 = self._page_id_by_rel_path("batch/p3.png")

        page1_layout1 = self._add_text_layout(page1, 1)
        page1_layout2 = self._add_text_layout(page1, 2)
        page2_layout1 = self._add_text_layout(page2, 1)
        _page3_layout1 = self._add_text_layout(page3, 1)

        now = main._utc_now()
        with db.get_session() as session:
            session.add(
                main.OcrOutput(
                    layout_id=page1_layout1,
                    page_id=page1,
                    class_name="text",
                    output_format="markdown",
                    content="already extracted",
                    model_name="gemini-3-flash-preview",
                    key_alias="k1",
                    created_at=now,
                    updated_at=now,
                )
            )

        self._set_page_status(page1, "layout_reviewed")
        self._set_page_status(page2, "ocr_failed")
        self._set_page_status(page3, "ocr_done")

        status_before = main.batch_ocr_status()
        self.assertEqual(int(status_before["pending_pages"]), 2)
        self.assertEqual(int(status_before["pending_layouts"]), 2)
        self.assertEqual(bool(status_before["is_running"]), False)

        enqueue_calls: list[tuple[str, int | None, dict[str, object] | None]] = []

        def _fake_enqueue(stage: str, *, page_id: int | None, payload: dict[str, object] | None = None) -> bool:
            enqueue_calls.append((stage, page_id, payload))
            return True

        with patch.object(main, "enqueue_job", side_effect=_fake_enqueue):
            run_payload = main.run_batch_ocr_job()

        self.assertEqual(bool(run_payload["enqueued"]), True)
        self.assertEqual(int(run_payload["considered_pages"]), 2)
        self.assertEqual(int(run_payload["considered_layouts"]), 2)
        self.assertEqual(int(run_payload["queued_pages"]), 2)

        self.assertEqual(len(enqueue_calls), 2)
        payload_by_page: dict[int, dict[str, object]] = {}
        for stage, page_id, payload in enqueue_calls:
            self.assertEqual(stage, "ocr_extract")
            self.assertIsNotNone(page_id)
            self.assertIsInstance(payload, dict)
            payload_dict = dict(payload or {})
            payload_by_page[int(page_id)] = payload_dict
            self.assertEqual(str(payload_dict.get("trigger")), "batch_ocr")
            self.assertEqual(bool(payload_dict.get("replace_existing")), False)

        self.assertEqual(set(payload_by_page.keys()), {page1, page2})
        self.assertEqual(payload_by_page[page1]["layout_ids"], [page1_layout2])
        self.assertEqual(payload_by_page[page2]["layout_ids"], [page2_layout1])

    def test_batch_ocr_stop_cancels_only_batch_queued_jobs(self) -> None:
        now = main._utc_now()
        with db.get_session() as session:
            session.add_all(
                [
                    main.PipelineJob(
                        stage="ocr_extract",
                        page_id=None,
                        status="queued",
                        payload_json='{"trigger":"batch_ocr","layout_ids":[1]}',
                        result_json=None,
                        error=None,
                        attempts=0,
                        created_at=now,
                        updated_at=now,
                        started_at=None,
                        finished_at=None,
                    ),
                    main.PipelineJob(
                        stage="ocr_extract",
                        page_id=None,
                        status="queued",
                        payload_json='{"trigger":"manual_test"}',
                        result_json=None,
                        error=None,
                        attempts=0,
                        created_at=now,
                        updated_at=now,
                        started_at=None,
                        finished_at=None,
                    ),
                    main.PipelineJob(
                        stage="ocr_extract",
                        page_id=None,
                        status="running",
                        payload_json='{"trigger":"batch_ocr","layout_ids":[2]}',
                        result_json=None,
                        error=None,
                        attempts=1,
                        created_at=now,
                        updated_at=now,
                        started_at=now,
                        finished_at=None,
                    ),
                ]
            )

        payload = main.stop_batch_ocr_job()
        self.assertEqual(bool(payload["running_stop_requested"]), True)
        self.assertEqual(int(payload["queued_cancelled"]), 1)

        with db.get_session() as session:
            jobs = session.execute(
                select(main.PipelineJob.id, main.PipelineJob.status, main.PipelineJob.error)
                .where(main.PipelineJob.stage == "ocr_extract")
                .order_by(main.PipelineJob.id.asc())
            ).all()
        self.assertEqual(str(jobs[0][1]), "failed")
        self.assertIn("Stopped by user request", str(jobs[0][2]))
        self.assertEqual(str(jobs[1][1]), "queued")
        self.assertEqual(str(jobs[2][1]), "running")

    def test_batch_ocr_stop_without_active_batch_jobs_returns_noop(self) -> None:
        now = main._utc_now()
        with db.get_session() as session:
            session.add_all(
                [
                    main.PipelineJob(
                        stage="ocr_extract",
                        page_id=None,
                        status="queued",
                        payload_json='{"trigger":"manual_reextract","layout_ids":[1]}',
                        result_json=None,
                        error=None,
                        attempts=0,
                        created_at=now,
                        updated_at=now,
                        started_at=None,
                        finished_at=None,
                    ),
                    main.PipelineJob(
                        stage="ocr_extract",
                        page_id=None,
                        status="running",
                        payload_json='{"trigger":"manual_reextract","layout_ids":[2]}',
                        result_json=None,
                        error=None,
                        attempts=1,
                        created_at=now,
                        updated_at=now,
                        started_at=now,
                        finished_at=None,
                    ),
                ]
            )

        payload = main.stop_batch_ocr_job()
        self.assertEqual(bool(payload["running_stop_requested"]), False)
        self.assertEqual(int(payload["queued_cancelled"]), 0)

        with db.get_session() as session:
            jobs = session.execute(
                select(main.PipelineJob.status)
                .where(main.PipelineJob.stage == "ocr_extract")
                .order_by(main.PipelineJob.id.asc())
            ).all()
        self.assertEqual([str(row[0]) for row in jobs], ["queued", "running"])

    def test_recover_pipeline_jobs_after_restart_clears_stale_running_batch_jobs(self) -> None:
        now = main._utc_now()
        with db.get_session() as session:
            session.add_all(
                [
                    main.PipelineJob(
                        stage="ocr_extract",
                        page_id=None,
                        status="running",
                        payload_json='{"trigger":"batch_ocr","layout_ids":[1,2]}',
                        result_json='{"progress":{"processed_layouts":1,"total_layouts":2}}',
                        error=None,
                        attempts=1,
                        created_at=now,
                        updated_at=now,
                        started_at=now,
                        finished_at=None,
                    ),
                    main.PipelineJob(
                        stage="layout_benchmark",
                        page_id=None,
                        status="running",
                        payload_json='{"trigger":"benchmark"}',
                        result_json='{"progress":{}}',
                        error=None,
                        attempts=1,
                        created_at=now,
                        updated_at=now,
                        started_at=now,
                        finished_at=None,
                    ),
                ]
            )

        recovered = pipeline_runtime.recover_pipeline_jobs_after_restart(exclude_stages={"layout_benchmark"})
        self.assertEqual(int(recovered["recovered_jobs"]), 1)

        with db.get_session() as session:
            jobs = session.execute(
                select(main.PipelineJob.stage, main.PipelineJob.status, main.PipelineJob.error)
                .order_by(main.PipelineJob.id.asc())
            ).all()
        self.assertEqual(str(jobs[0][0]), "ocr_extract")
        self.assertEqual(str(jobs[0][1]), "failed")
        self.assertIn("Interrupted by service restart", str(jobs[0][2]))
        self.assertEqual(str(jobs[1][0]), "layout_benchmark")
        self.assertEqual(str(jobs[1][1]), "running")

        status_payload = main.batch_ocr_status()
        self.assertEqual(bool(status_payload["is_running"]), False)
        self.assertEqual(int(status_payload["running_jobs"]), 0)
        self.assertEqual(int(status_payload["queued_jobs"]), 0)

    def test_ocr_extract_handler_respects_payload_layout_ids(self) -> None:
        self._write_image("batch/extract.png", b"extract-page")
        main.scan_images()
        page_id = self._page_id_by_rel_path("batch/extract.png")
        layout1 = self._add_text_layout(page_id, 1)
        layout2 = self._add_text_layout(page_id, 2)
        self._set_page_status(page_id, "layout_reviewed")

        now = main._utc_now()
        with db.get_session() as session:
            session.add(
                main.OcrOutput(
                    layout_id=layout1,
                    page_id=page_id,
                    class_name="text",
                    output_format="markdown",
                    content="existing content",
                    model_name="gemini-3-flash-preview",
                    key_alias="k1",
                    created_at=now,
                    updated_at=now,
                )
            )

        with patch.object(ocr_extract, "_crop_layout_png_bytes", return_value=b"png-bytes"), patch.object(
            ocr_extract, "_gemini_generate_content", return_value="updated content"
        ) as gemini_mock:
            result = pipeline_runtime._ocr_extract_handler(
                {
                    "page_id": page_id,
                    "payload": {"layout_ids": [layout2]},
                    "id": 1,
                    "stage": "ocr_extract",
                }
            )

        self.assertEqual(result["status"], "ocr_done")
        self.assertEqual(result["layouts_selected"], 1)
        self.assertEqual(result["extracted_count"], 1)
        gemini_mock.assert_called_once()

        outputs_payload = main.page_ocr_outputs(page_id)
        self.assertEqual(int(outputs_payload["count"]), 2)
        output_by_layout = {int(row["layout_id"]): str(row["content"]) for row in outputs_payload["outputs"]}
        self.assertEqual(output_by_layout[layout1], "existing content")
        self.assertEqual(output_by_layout[layout2], "updated content")

    def test_batch_ocr_handler_continues_on_gemini_server_error(self) -> None:
        self._write_image("batch/timeout-continue.png", b"extract-page")
        main.scan_images()
        page_id = self._page_id_by_rel_path("batch/timeout-continue.png")
        layout1 = self._add_text_layout(page_id, 1)
        layout2 = self._add_text_layout(page_id, 2)
        self._set_page_status(page_id, "layout_reviewed")

        call_index = {"value": 0}

        def fake_gemini(*_args, **_kwargs) -> str:
            call_index["value"] += 1
            if call_index["value"] <= 3:
                raise RuntimeError("The read operation timed out")
            return "second-ok"

        with patch.object(ocr_extract, "_crop_layout_png_bytes", return_value=b"png-bytes"), patch.object(
            ocr_extract,
            "_gemini_generate_content",
            side_effect=fake_gemini,
        ):
            result = pipeline_runtime._ocr_extract_handler(
                {
                    "page_id": page_id,
                    "payload": {"trigger": "batch_ocr", "layout_ids": [layout1, layout2]},
                    "id": 100,
                    "stage": "ocr_extract",
                }
            )

        self.assertEqual(result["status"], "ocr_failed")
        self.assertEqual(result["extracted_count"], 1)
        self.assertEqual(result["failed_count"], 1)
        self.assertEqual(result["failed_layout_ids"], [layout1])

        page_payload = main.page_details(page_id)
        self.assertEqual(str(page_payload["page"]["status"]), "ocr_failed")

        outputs_payload = main.page_ocr_outputs(page_id)
        self.assertEqual(int(outputs_payload["count"]), 1)
        self.assertEqual(int(outputs_payload["outputs"][0]["layout_id"]), layout2)
        self.assertEqual(str(outputs_payload["outputs"][0]["content"]), "second-ok")

    def test_batch_ocr_status_reports_bbox_progress_for_active_run(self) -> None:
        now = main._utc_now()
        with db.get_session() as session:
            session.add_all(
                [
                    main.PipelineJob(
                        stage="ocr_extract",
                        page_id=None,
                        status="completed",
                        payload_json=(
                            '{"trigger":"batch_ocr","batch_run_id":"run-123","batch_total_layouts":6,'
                            '"layout_ids":[1,2],"replace_existing":false}'
                        ),
                        result_json='{"extracted_count":1,"skipped_count":1}',
                        error=None,
                        attempts=1,
                        created_at=now,
                        updated_at=now,
                        started_at=now,
                        finished_at=now,
                    ),
                    main.PipelineJob(
                        stage="ocr_extract",
                        page_id=None,
                        status="running",
                        payload_json=(
                            '{"trigger":"batch_ocr","batch_run_id":"run-123","batch_total_layouts":6,'
                            '"layout_ids":[3,4,5],"replace_existing":false}'
                        ),
                        result_json='{"progress":{"processed_layouts":1,"total_layouts":3}}',
                        error=None,
                        attempts=1,
                        created_at=now,
                        updated_at=now,
                        started_at=now,
                        finished_at=None,
                    ),
                    main.PipelineJob(
                        stage="ocr_extract",
                        page_id=None,
                        status="queued",
                        payload_json=(
                            '{"trigger":"batch_ocr","batch_run_id":"run-123","batch_total_layouts":6,'
                            '"layout_ids":[6],"replace_existing":false}'
                        ),
                        result_json=None,
                        error=None,
                        attempts=0,
                        created_at=now,
                        updated_at=now,
                        started_at=None,
                        finished_at=None,
                    ),
                ]
            )

        payload = main.batch_ocr_status()
        self.assertEqual(bool(payload["is_running"]), True)
        self.assertEqual(int(payload["progress_total"]), 6)
        self.assertEqual(int(payload["progress_current"]), 3)
        self.assertEqual(int(payload["running_jobs"]), 1)
        self.assertEqual(int(payload["queued_jobs"]), 1)

    def test_batch_ocr_status_ignores_non_batch_active_jobs(self) -> None:
        now = main._utc_now()
        with db.get_session() as session:
            session.add_all(
                [
                    main.PipelineJob(
                        stage="ocr_extract",
                        page_id=None,
                        status="running",
                        payload_json='{"trigger":"manual_reextract","layout_ids":[1]}',
                        result_json='{"progress":{"processed_layouts":1,"total_layouts":1}}',
                        error=None,
                        attempts=1,
                        created_at=now,
                        updated_at=now,
                        started_at=now,
                        finished_at=None,
                    ),
                    main.PipelineJob(
                        stage="ocr_extract",
                        page_id=None,
                        status="queued",
                        payload_json='{"trigger":"manual_reextract","layout_ids":[2]}',
                        result_json=None,
                        error=None,
                        attempts=0,
                        created_at=now,
                        updated_at=now,
                        started_at=None,
                        finished_at=None,
                    ),
                ]
            )

        payload = main.batch_ocr_status()
        self.assertEqual(bool(payload["is_running"]), False)
        self.assertEqual(int(payload["running_jobs"]), 0)
        self.assertEqual(int(payload["queued_jobs"]), 0)
        self.assertEqual(int(payload["progress_current"]), 0)
        self.assertEqual(int(payload["progress_total"]), 0)

    def test_batch_ocr_status_uses_newest_active_batch_run_only(self) -> None:
        now = main._utc_now()
        with db.get_session() as session:
            session.add_all(
                [
                    # Older run: fully processed but not active.
                    main.PipelineJob(
                        stage="ocr_extract",
                        page_id=None,
                        status="completed",
                        payload_json=(
                            '{"trigger":"batch_ocr","batch_run_id":"run-old","batch_total_layouts":4,'
                            '"layout_ids":[1,2],"replace_existing":false}'
                        ),
                        result_json='{"extracted_count":2,"skipped_count":0}',
                        error=None,
                        attempts=1,
                        created_at=now,
                        updated_at=now,
                        started_at=now,
                        finished_at=now,
                    ),
                    main.PipelineJob(
                        stage="ocr_extract",
                        page_id=None,
                        status="completed",
                        payload_json=(
                            '{"trigger":"batch_ocr","batch_run_id":"run-old","batch_total_layouts":4,'
                            '"layout_ids":[3,4],"replace_existing":false}'
                        ),
                        result_json='{"extracted_count":1,"skipped_count":1}',
                        error=None,
                        attempts=1,
                        created_at=now,
                        updated_at=now,
                        started_at=now,
                        finished_at=now,
                    ),
                    # Newer active run: should be the one reflected in progress.
                    main.PipelineJob(
                        stage="ocr_extract",
                        page_id=None,
                        status="completed",
                        payload_json=(
                            '{"trigger":"batch_ocr","batch_run_id":"run-new","batch_total_layouts":5,'
                            '"layout_ids":[10,11],"replace_existing":false}'
                        ),
                        result_json='{"extracted_count":1,"skipped_count":1}',
                        error=None,
                        attempts=1,
                        created_at=now,
                        updated_at=now,
                        started_at=now,
                        finished_at=now,
                    ),
                    main.PipelineJob(
                        stage="ocr_extract",
                        page_id=None,
                        status="running",
                        payload_json=(
                            '{"trigger":"batch_ocr","batch_run_id":"run-new","batch_total_layouts":5,'
                            '"layout_ids":[12,13,14],"replace_existing":false}'
                        ),
                        result_json='{"progress":{"processed_layouts":1,"total_layouts":3}}',
                        error=None,
                        attempts=1,
                        created_at=now,
                        updated_at=now,
                        started_at=now,
                        finished_at=None,
                    ),
                ]
            )

        payload = main.batch_ocr_status()
        self.assertEqual(bool(payload["is_running"]), True)
        self.assertEqual(int(payload["running_jobs"]), 1)
        self.assertEqual(int(payload["queued_jobs"]), 0)
        self.assertEqual(int(payload["progress_total"]), 5)
        self.assertEqual(int(payload["progress_current"]), 3)

    def test_batch_ocr_run_no_pending_layouts_enqueues_nothing(self) -> None:
        self._write_image("batch/no-pending.png", b"page")
        main.scan_images()
        page_id = self._page_id_by_rel_path("batch/no-pending.png")
        layout_id = self._add_text_layout(page_id, 1)
        self._set_page_status(page_id, "ocr_done")

        now = main._utc_now()
        with db.get_session() as session:
            session.add(
                main.OcrOutput(
                    layout_id=layout_id,
                    page_id=page_id,
                    class_name="text",
                    output_format="markdown",
                    content="already extracted",
                    model_name="gemini-3-flash-preview",
                    key_alias="k1",
                    created_at=now,
                    updated_at=now,
                )
            )

        enqueue_calls: list[tuple[str, int | None, dict[str, object] | None]] = []

        def _fake_enqueue(stage: str, *, page_id: int | None, payload: dict[str, object] | None = None) -> bool:
            enqueue_calls.append((stage, page_id, payload))
            return True

        with patch.object(main, "enqueue_job", side_effect=_fake_enqueue):
            payload = main.run_batch_ocr_job()

        self.assertEqual(bool(payload["enqueued"]), False)
        self.assertEqual(int(payload["considered_pages"]), 0)
        self.assertEqual(int(payload["considered_layouts"]), 0)
        self.assertEqual(int(payload["queued_pages"]), 0)
        self.assertEqual(int(payload["already_queued_or_running"]), 0)
        self.assertEqual(enqueue_calls, [])


if __name__ == "__main__":
    unittest.main()
