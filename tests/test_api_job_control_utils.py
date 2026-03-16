from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from sqlalchemy import select

from app import config, db, discovery, final_export, layouts, main, ocr_extract, runtime_options
from app.api.job_control_utils import (
    coerce_int,
    parse_json_object,
    resolve_main_callable,
    stop_stage_jobs,
    utc_now_iso,
)
from app.config import DEFAULT_EXTENSIONS, Settings


class ApiJobControlUtilsTests(unittest.TestCase):
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

    def test_parse_json_object_returns_only_dict_objects(self) -> None:
        self.assertEqual(parse_json_object(None), {})
        self.assertEqual(parse_json_object(""), {})
        self.assertEqual(parse_json_object("{broken"), {})
        self.assertEqual(parse_json_object("[]"), {})
        self.assertEqual(parse_json_object('{"a":1}'), {"a": 1})

    def test_coerce_int_applies_default_and_bounds(self) -> None:
        self.assertEqual(coerce_int("12"), 12)
        self.assertEqual(coerce_int("x"), 0)
        self.assertEqual(coerce_int("x", default=7), 7)
        self.assertEqual(coerce_int("-5", minimum=0), 0)
        self.assertEqual(coerce_int("500", maximum=100), 100)
        self.assertEqual(coerce_int("500", minimum=10, maximum=100), 100)

    def test_resolve_main_callable_prefers_main_module_callable(self) -> None:
        def fallback() -> str:
            return "fallback"

        def override() -> str:
            return "override"

        with patch.object(main, "enqueue_job", override):
            resolved = resolve_main_callable("enqueue_job", fallback)
        self.assertIs(resolved, override)
        self.assertEqual(resolved(), "override")

    def test_resolve_main_callable_falls_back_for_missing_or_non_callable_attr(self) -> None:
        def fallback() -> str:
            return "fallback"

        with patch.object(main, "enqueue_job", 123):
            resolved_non_callable = resolve_main_callable("enqueue_job", fallback)
        resolved_missing = resolve_main_callable("__missing_attr__", fallback)

        self.assertIs(resolved_non_callable, fallback)
        self.assertIs(resolved_missing, fallback)
        self.assertEqual(fallback(), "fallback")

    def test_utc_now_iso_returns_iso8601_utc_timestamp(self) -> None:
        value = utc_now_iso()
        self.assertIn("T", value)
        self.assertTrue(value.endswith("+00:00"))

    def test_stop_stage_jobs_cancels_only_matching_queued_and_flags_running(self) -> None:
        now = main._utc_now()
        with db.get_session() as session:
            session.add_all(
                [
                    main.PipelineJob(
                        stage="ocr_extract",
                        page_id=None,
                        status="queued",
                        payload_json='{"trigger":"batch_ocr"}',
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
                        payload_json='{"trigger":"manual"}',
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
                        payload_json='{"trigger":"batch_ocr"}',
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

        result = stop_stage_jobs(
            "ocr_extract",
            payload_matcher=lambda payload: str(payload.get("trigger")) == "batch_ocr",
            now_iso=now,
        )
        self.assertEqual(result, {"running_found": True, "queued_cancelled": 1})

        with db.get_session() as session:
            rows = session.execute(
                select(main.PipelineJob.status, main.PipelineJob.error)
                .where(main.PipelineJob.stage == "ocr_extract")
                .order_by(main.PipelineJob.id.asc())
            ).all()
        self.assertEqual(str(rows[0][0]), "failed")
        self.assertIn("Stopped by user request", str(rows[0][1]))
        self.assertEqual(str(rows[1][0]), "queued")
        self.assertEqual(str(rows[2][0]), "running")

    def test_stop_stage_jobs_handles_no_matching_rows(self) -> None:
        result = stop_stage_jobs(
            "ocr_extract",
            payload_matcher=lambda _payload: False,
            now_iso=main._utc_now(),
        )
        self.assertEqual(result, {"running_found": False, "queued_cancelled": 0})


if __name__ == "__main__":
    unittest.main()
