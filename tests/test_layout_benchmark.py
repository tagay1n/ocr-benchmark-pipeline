from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

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
        self.assertEqual(second["processed_tasks"], 0)
        self.assertEqual(second["skipped_tasks"], 1)
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


if __name__ == "__main__":
    unittest.main()
