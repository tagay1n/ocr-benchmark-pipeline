from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import select

from app import (
    config,
    db,
    discovery,
    final_export,
    layout_benchmark,
    layout_detection_defaults,
    layouts,
    main,
    ocr_extract,
    runtime_options,
)
from app.config import DEFAULT_EXTENSIONS, Settings
from app.pipeline_constants import STAGE_LAYOUT_BENCHMARK


class LayoutBenchmarkTests(unittest.TestCase):
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
        self.stack.enter_context(patch.object(layout_benchmark, "settings", self.test_settings))
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

    def _seed_reviewed_pages(self, count: int) -> list[int]:
        for idx in range(count):
            self._write_image(f"bench/{idx:04d}.png", f"img-{idx}".encode("utf-8"))
        main.scan_images()
        page_ids = [int(page["id"]) for page in main.list_pages()["pages"]]
        for page_id in page_ids:
            main.create_page_layout(
                page_id,
                main.CreateLayoutRequest(
                    class_name="text",
                    reading_order=1,
                    bbox=main.BBoxPayload(x1=0.1, y1=0.1, x2=0.8, y2=0.8),
                ),
            )
            main.complete_layout_review(page_id)
        return page_ids

    def _seed_reviewed_page_with_layouts(
        self,
        rel_path: str,
        layouts_payload: list[main.CreateLayoutRequest],
    ) -> int:
        self._write_image(rel_path, rel_path.encode("utf-8"))
        main.scan_images()
        pages = main.list_pages()["pages"]
        matching = next((page for page in pages if str(page.get("rel_path")) == rel_path), None)
        if matching is None:
            raise AssertionError(f"Page not found after scan: {rel_path}")
        page_id = int(matching["id"])
        for payload in layouts_payload:
            main.create_page_layout(page_id, payload)
        main.complete_layout_review(page_id)
        return page_id

    def _fake_detect(self, model_checkpoint: str) -> tuple[list[dict[str, float | str]], dict[str, object]]:
        rows = []
        if model_checkpoint.endswith("b.pt"):
            rows = [
                {
                    "class_name": "text",
                    "confidence": 0.9,
                    "x1": 0.1,
                    "y1": 0.1,
                    "x2": 0.8,
                    "y2": 0.8,
                }
            ]
        return (
            rows,
            {
                "model_checkpoint": model_checkpoint,
                "confidence_threshold": 0.2,
                "iou_threshold": 0.5,
                "image_size": 512,
                "max_detections": 300,
                "agnostic_nms": False,
            },
        )

    def test_layout_detection_defaults_endpoint_returns_defaults_and_available_models(self) -> None:
        payload = main.layout_detection_defaults()
        self.assertIn("defaults", payload)
        self.assertIn("available_models", payload)
        self.assertGreaterEqual(len(payload["available_models"]), 1)
        self.assertEqual(payload["defaults"]["model_checkpoint"], "yolo26m-doclaynet.pt")

    def test_layout_benchmark_run_endpoint_emits_enqueue_events(self) -> None:
        with patch.object(main, "enqueue_job", return_value=True):
            started = main.run_layout_benchmark_job(main.RunLayoutBenchmarkRequest(force_full_rerun=False))
        self.assertEqual(started, {"enqueued": True})

        with patch.object(main, "enqueue_job", return_value=False):
            skipped = main.run_layout_benchmark_job(main.RunLayoutBenchmarkRequest(force_full_rerun=True))
        self.assertEqual(skipped, {"enqueued": False})

        activity = main.pipeline_activity()
        benchmark_events = [
            event
            for event in activity["recent_events"]
            if str(event.get("stage")) == "layout_benchmark"
        ]
        self.assertGreaterEqual(len(benchmark_events), 2)
        event_types = {str(event.get("event_type")) for event in benchmark_events}
        self.assertIn("job_enqueued", event_types)
        self.assertIn("job_enqueue_skipped", event_types)

    def test_run_layout_benchmark_uses_incremental_cache_on_second_run(self) -> None:
        self._seed_reviewed_pages(1)
        layout_detection_defaults.update_layout_detection_defaults(
            model_checkpoint="bench-a.pt",
            confidence_threshold=0.2,
            iou_threshold=0.5,
            image_size=512,
            updated_by="test",
        )

        with (
            patch.object(layout_benchmark, "BENCHMARK_MODEL_CHECKPOINTS", ("bench-a.pt",)),
            patch.object(layout_benchmark, "BENCHMARK_IMAGE_SIZES", (512,)),
            patch.object(layout_benchmark, "BENCHMARK_CONFIDENCE_THRESHOLDS", (0.2,)),
            patch.object(layout_benchmark, "BENCHMARK_IOU_THRESHOLDS", (0.5,)),
            patch.object(
                layout_benchmark,
                "_detect_doclaynet_layouts",
                return_value=self._fake_detect("bench-a.pt"),
            ) as detect_mock,
        ):
            first = layout_benchmark.run_layout_benchmark(force_full_rerun=False)
            second = layout_benchmark.run_layout_benchmark(force_full_rerun=False)

        self.assertEqual(first["processed_tasks"], 1)
        self.assertEqual(first["skipped_tasks"], 0)
        self.assertEqual(first["cached_tasks"], 0)
        self.assertEqual(second["processed_tasks"], 1)
        self.assertEqual(second["skipped_tasks"], 0)
        self.assertEqual(second["cached_tasks"], 1)
        self.assertEqual(detect_mock.call_count, 1)

    def test_run_layout_benchmark_auto_applies_better_defaults(self) -> None:
        self._seed_reviewed_pages(10)
        layout_detection_defaults.update_layout_detection_defaults(
            model_checkpoint="bench-a.pt",
            confidence_threshold=0.2,
            iou_threshold=0.5,
            image_size=512,
            updated_by="test",
        )

        def detect_side_effect(
            _image_path: Path,
            *,
            model_checkpoint: str | None,
            confidence_threshold: float | None,
            iou_threshold: float | None,
            image_size: int | None,
            max_detections: int | None,
            agnostic_nms: bool | None,
        ):
            checkpoint = str(model_checkpoint or "bench-a.pt")
            del confidence_threshold, iou_threshold, image_size, max_detections, agnostic_nms
            return self._fake_detect(checkpoint)

        with (
            patch.object(layout_benchmark, "BENCHMARK_MODEL_CHECKPOINTS", ("bench-a.pt", "bench-b.pt")),
            patch.object(layout_benchmark, "BENCHMARK_IMAGE_SIZES", (512,)),
            patch.object(layout_benchmark, "BENCHMARK_CONFIDENCE_THRESHOLDS", (0.2,)),
            patch.object(layout_benchmark, "BENCHMARK_IOU_THRESHOLDS", (0.5,)),
            patch.object(layout_benchmark, "_detect_doclaynet_layouts", side_effect=detect_side_effect),
        ):
            result = layout_benchmark.run_layout_benchmark(force_full_rerun=False)

        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["applied_defaults"])
        self.assertEqual(result["best_config"]["model_checkpoint"], "bench-b.pt")
        latest_defaults = layout_detection_defaults.get_layout_detection_defaults()
        self.assertEqual(latest_defaults["model_checkpoint"], "bench-b.pt")
        self.assertEqual(main.layout_benchmark_status()["run"]["status"], "completed")

    def test_layout_benchmark_grid_endpoint_returns_aggregated_rows(self) -> None:
        self._seed_reviewed_pages(2)
        layout_detection_defaults.update_layout_detection_defaults(
            model_checkpoint="bench-b.pt",
            confidence_threshold=0.2,
            iou_threshold=0.5,
            image_size=512,
            updated_by="test",
        )

        with (
            patch.object(layout_benchmark, "BENCHMARK_MODEL_CHECKPOINTS", ("bench-b.pt",)),
            patch.object(layout_benchmark, "BENCHMARK_IMAGE_SIZES", (512,)),
            patch.object(layout_benchmark, "BENCHMARK_CONFIDENCE_THRESHOLDS", (0.2,)),
            patch.object(layout_benchmark, "BENCHMARK_IOU_THRESHOLDS", (0.5,)),
            patch.object(layout_benchmark, "_detect_doclaynet_layouts", return_value=self._fake_detect("bench-b.pt")),
        ):
            layout_benchmark.run_layout_benchmark(force_full_rerun=False)

        payload = main.layout_benchmark_grid()
        self.assertIn("rows", payload)
        self.assertGreaterEqual(len(payload["rows"]), 1)
        self.assertEqual(payload["best_config"]["model_checkpoint"], "bench-b.pt")
        self.assertGreater(float(payload["best_score"]), 0.0)
        first_row = payload["rows"][0]
        self.assertIn("min_score", first_row)
        self.assertIn("max_score", first_row)
        self.assertIn("std_dev", first_row)
        self.assertIn("hard_case_score", first_row)
        self.assertIn("hard_case_page_count", first_row)
        self.assertIn("per_class", first_row)
        self.assertGreaterEqual(float(first_row["min_score"]), 0.0)
        self.assertGreaterEqual(float(first_row["max_score"]), float(first_row["min_score"]))
        self.assertGreaterEqual(float(first_row["std_dev"]), 0.0)
        self.assertIn("class_names", payload)
        self.assertIn("text", payload["class_names"])

    def test_layout_benchmark_grid_reports_hard_case_and_per_class_metrics(self) -> None:
        self._seed_reviewed_page_with_layouts(
            "bench/text_only.png",
            [
                main.CreateLayoutRequest(
                    class_name="text",
                    reading_order=1,
                    bbox=main.BBoxPayload(x1=0.1, y1=0.1, x2=0.85, y2=0.8),
                )
            ],
        )
        self._seed_reviewed_page_with_layouts(
            "bench/table_page.png",
            [
                main.CreateLayoutRequest(
                    class_name="table",
                    reading_order=1,
                    bbox=main.BBoxPayload(x1=0.1, y1=0.1, x2=0.9, y2=0.75),
                )
            ],
        )

        def detect_side_effect(
            image_path: Path,
            *,
            model_checkpoint: str | None,
            confidence_threshold: float | None,
            iou_threshold: float | None,
            image_size: int | None,
            max_detections: int | None,
            agnostic_nms: bool | None,
        ):
            del model_checkpoint, confidence_threshold, iou_threshold, image_size, max_detections, agnostic_nms
            image_name = image_path.name
            if image_name == "text_only.png":
                return (
                    [
                        {
                            "class_name": "text",
                            "confidence": 0.9,
                            "x1": 0.1,
                            "y1": 0.1,
                            "x2": 0.85,
                            "y2": 0.8,
                        }
                    ],
                    {
                        "model_checkpoint": "bench-b.pt",
                        "confidence_threshold": 0.2,
                        "iou_threshold": 0.5,
                        "image_size": 512,
                        "max_detections": 300,
                        "agnostic_nms": False,
                    },
                )
            return (
                [],
                {
                    "model_checkpoint": "bench-b.pt",
                    "confidence_threshold": 0.2,
                    "iou_threshold": 0.5,
                    "image_size": 512,
                    "max_detections": 300,
                    "agnostic_nms": False,
                },
            )

        with (
            patch.object(layout_benchmark, "BENCHMARK_MODEL_CHECKPOINTS", ("bench-b.pt",)),
            patch.object(layout_benchmark, "BENCHMARK_IMAGE_SIZES", (512,)),
            patch.object(layout_benchmark, "BENCHMARK_CONFIDENCE_THRESHOLDS", (0.2,)),
            patch.object(layout_benchmark, "BENCHMARK_IOU_THRESHOLDS", (0.5,)),
            patch.object(layout_benchmark, "_detect_doclaynet_layouts", side_effect=detect_side_effect),
        ):
            layout_benchmark.run_layout_benchmark(force_full_rerun=False)

        payload = main.layout_benchmark_grid()
        row = payload["rows"][0]
        self.assertEqual(int(row["page_count"]), 2)
        self.assertEqual(int(row["hard_case_page_count"]), 1)
        self.assertEqual(float(row["hard_case_score"]), 0.0)
        self.assertIn("text", row["per_class"])
        self.assertIn("table", row["per_class"])
        self.assertGreater(float(row["per_class"]["text"]["ap50_95"]), float(row["per_class"]["table"]["ap50_95"]))

    def test_layout_benchmark_stop_endpoint_cancels_queued_jobs(self) -> None:
        now = main._utc_now()
        with db.get_session() as session:
            session.add(
                main.PipelineJob(
                    stage=STAGE_LAYOUT_BENCHMARK,
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
        with patch.object(layout_benchmark, "request_layout_benchmark_stop") as stop_mock:
            payload = main.stop_layout_benchmark_job()
        self.assertEqual(payload["running_stop_requested"], False)
        self.assertEqual(payload["queued_cancelled"], 1)
        stop_mock.assert_not_called()

        with db.get_session() as session:
            job = session.execute(
                select(main.PipelineJob).where(main.PipelineJob.stage == STAGE_LAYOUT_BENCHMARK).limit(1)
            ).scalar_one()
            self.assertEqual(job.status, "failed")
            self.assertIn("Stopped by user request", str(job.error))

    def test_run_layout_benchmark_stops_when_stop_requested(self) -> None:
        self._seed_reviewed_pages(1)
        layout_detection_defaults.update_layout_detection_defaults(
            model_checkpoint="bench-a.pt",
            confidence_threshold=0.2,
            iou_threshold=0.5,
            image_size=512,
            updated_by="test",
        )

        call_count = {"value": 0}

        def detect_side_effect(
            _image_path: Path,
            *,
            model_checkpoint: str | None,
            confidence_threshold: float | None,
            iou_threshold: float | None,
            image_size: int | None,
            max_detections: int | None,
            agnostic_nms: bool | None,
        ):
            del confidence_threshold, iou_threshold, image_size, max_detections, agnostic_nms
            call_count["value"] += 1
            if call_count["value"] == 1:
                layout_benchmark.request_layout_benchmark_stop()
            checkpoint = str(model_checkpoint or "bench-a.pt")
            return self._fake_detect(checkpoint)

        with (
            patch.object(layout_benchmark, "BENCHMARK_MODEL_CHECKPOINTS", ("bench-a.pt", "bench-b.pt")),
            patch.object(layout_benchmark, "BENCHMARK_IMAGE_SIZES", (512,)),
            patch.object(layout_benchmark, "BENCHMARK_CONFIDENCE_THRESHOLDS", (0.2,)),
            patch.object(layout_benchmark, "BENCHMARK_IOU_THRESHOLDS", (0.5,)),
            patch.object(layout_benchmark, "_detect_doclaynet_layouts", side_effect=detect_side_effect),
        ):
            result = layout_benchmark.run_layout_benchmark(force_full_rerun=False)

        self.assertEqual(result["status"], "stopped")
        self.assertTrue(result["stopped"])
        self.assertEqual(result["processed_tasks"], 1)
        self.assertEqual(result["total_tasks"], 2)

    def test_recover_layout_benchmark_after_restart_clears_stale_jobs_and_run(self) -> None:
        now = main._utc_now()
        with db.get_session() as session:
            session.add(
                layout_benchmark.LayoutBenchmarkRun(
                    status="running",
                    force_full_rerun=False,
                    total_pages=2,
                    total_configs=1,
                    total_tasks=2,
                    processed_tasks=1,
                    skipped_tasks=0,
                    current_page_id=None,
                    current_config_json=None,
                    best_config_json=None,
                    applied_defaults=False,
                    error=None,
                    created_at=now,
                    updated_at=now,
                    finished_at=None,
                )
            )
            session.add(
                main.PipelineJob(
                    stage=STAGE_LAYOUT_BENCHMARK,
                    page_id=None,
                    status="running",
                    payload_json='{"force_full_rerun":false}',
                    result_json=None,
                    error=None,
                    attempts=1,
                    created_at=now,
                    updated_at=now,
                    started_at=now,
                    finished_at=None,
                )
            )
            session.add(
                main.PipelineJob(
                    stage=STAGE_LAYOUT_BENCHMARK,
                    page_id=None,
                    status="queued",
                    payload_json='{"force_full_rerun":false}',
                    result_json=None,
                    error=None,
                    attempts=0,
                    created_at=now,
                    updated_at=now,
                    started_at=None,
                    finished_at=None,
                )
            )

        recovered = layout_benchmark.recover_layout_benchmark_after_restart()
        self.assertEqual(recovered["recovered_jobs"], 2)
        self.assertEqual(recovered["recovered_runs"], 1)

        status_payload = main.layout_benchmark_status()
        self.assertFalse(bool(status_payload["is_running"]))
        self.assertEqual(status_payload["run"]["status"], "failed")
        self.assertIn("Interrupted by service restart", str(status_payload["run"]["error"]))

    def test_rescore_endpoint_recalculates_scores_from_stored_predictions(self) -> None:
        self._seed_reviewed_pages(1)
        with (
            patch.object(layout_benchmark, "BENCHMARK_MODEL_CHECKPOINTS", ("bench-b.pt",)),
            patch.object(layout_benchmark, "BENCHMARK_IMAGE_SIZES", (512,)),
            patch.object(layout_benchmark, "BENCHMARK_CONFIDENCE_THRESHOLDS", (0.2,)),
            patch.object(layout_benchmark, "BENCHMARK_IOU_THRESHOLDS", (0.5,)),
            patch.object(layout_benchmark, "_detect_doclaynet_layouts", return_value=self._fake_detect("bench-b.pt")),
        ):
            layout_benchmark.run_layout_benchmark(force_full_rerun=False)

        with db.get_session() as session:
            rows = session.execute(select(layout_benchmark.LayoutBenchmarkResult)).scalars().all()
            self.assertGreaterEqual(len(rows), 1)
            for row in rows:
                row.score = 1.0
                row.metrics_json = "{}"
                row.predictions_json = "[]"
                row.updated_at = main._utc_now()

        result = main.rescore_layout_benchmark()
        self.assertGreaterEqual(int(result["recalculated_rows"]), 1)
        self.assertEqual(int(result["skipped_no_predictions"]), 0)

        payload = main.layout_benchmark_grid()
        for row_payload in payload["rows"]:
            self.assertEqual(float(row_payload["mean_score"]), 0.0)

    def test_rescore_endpoint_rejects_while_benchmark_running(self) -> None:
        now = main._utc_now()
        with db.get_session() as session:
            session.add(
                layout_benchmark.LayoutBenchmarkRun(
                    status="running",
                    force_full_rerun=False,
                    total_pages=0,
                    total_configs=0,
                    total_tasks=0,
                    processed_tasks=0,
                    skipped_tasks=0,
                    current_page_id=None,
                    current_config_json=None,
                    best_config_json=None,
                    applied_defaults=False,
                    error=None,
                    created_at=now,
                    updated_at=now,
                    finished_at=None,
                )
            )

        with self.assertRaises(HTTPException) as error:
            main.rescore_layout_benchmark()
        self.assertEqual(error.exception.status_code, 409)

    def test_benchmark_scoring_uses_map50_95(self) -> None:
        gt = (
            {
                "class_name": "text",
                "bbox": {"x1": 0.1, "y1": 0.1, "x2": 0.6, "y2": 0.6},
            },
        )
        perfect_pred = [
            {
                "class_name": "text",
                "x1": 0.1,
                "y1": 0.1,
                "x2": 0.6,
                "y2": 0.6,
            }
        ]
        shifted_pred = [
            {
                "class_name": "text",
                "x1": 0.15,
                "y1": 0.15,
                "x2": 0.65,
                "y2": 0.65,
            }
        ]

        perfect_score, perfect_metrics = layout_benchmark._map50_95_score(gt, perfect_pred)
        shifted_score, shifted_metrics = layout_benchmark._map50_95_score(gt, shifted_pred)
        self.assertGreater(perfect_score, shifted_score)
        self.assertGreater(shifted_score, 0.0)
        self.assertEqual(float(perfect_metrics["per_class"]["text"]["ap50"]), 1.0)
        self.assertLess(float(shifted_metrics["per_class"]["text"]["ap50_95"]), 1.0)

    def test_benchmark_class_normalization_maps_title_but_keeps_list_item(self) -> None:
        gt_header = (
            {
                "class_name": "section_header",
                "bbox": {"x1": 0.1, "y1": 0.1, "x2": 0.6, "y2": 0.2},
            },
        )
        title_pred = [
            {
                "class_name": "title",
                "x1": 0.1,
                "y1": 0.1,
                "x2": 0.6,
                "y2": 0.2,
            }
        ]
        title_score, _title_metrics = layout_benchmark._map50_95_score(gt_header, title_pred)
        self.assertEqual(title_score, 1.0)

        gt_list_item = (
            {
                "class_name": "list_item",
                "bbox": {"x1": 0.1, "y1": 0.2, "x2": 0.7, "y2": 0.4},
            },
        )
        text_pred = [
            {
                "class_name": "text",
                "x1": 0.1,
                "y1": 0.2,
                "x2": 0.7,
                "y2": 0.4,
            }
        ]
        mismatch_score, _mismatch_metrics = layout_benchmark._map50_95_score(gt_list_item, text_pred)
        self.assertEqual(mismatch_score, 0.0)


if __name__ == "__main__":
    unittest.main()
