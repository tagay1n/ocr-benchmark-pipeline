from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from app import config, db, discovery, final_export, layouts, main, ocr_extract, pipeline_runtime, runtime_options
from app.config import DEFAULT_EXTENSIONS, Settings


class PipelineRuntimeConcurrencyTests(unittest.TestCase):
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

    def test_concurrent_enqueue_same_stage_and_page_deduplicates(self) -> None:
        self._write_image("c/same.png")
        main.scan_images()
        page_id = int(main.list_pages()["pages"][0]["id"])

        barrier = threading.Barrier(10)

        def enqueue_once() -> bool:
            barrier.wait(timeout=5)
            return pipeline_runtime.enqueue_job("layout_detect", page_id=page_id, payload={"source": "concurrent"})

        with patch.object(pipeline_runtime, "_ensure_worker_running", return_value=None):
            with ThreadPoolExecutor(max_workers=10) as pool:
                results = list(pool.map(lambda _x: enqueue_once(), range(10)))

        self.assertEqual(sum(1 for value in results if value), 1)
        with db.get_session() as session:
            jobs = (
                session.query(main.PipelineJob)
                .filter(main.PipelineJob.stage == "layout_detect")
                .filter(main.PipelineJob.page_id == page_id)
                .filter(main.PipelineJob.status == "queued")
                .all()
            )
            self.assertEqual(len(jobs), 1)

    def test_concurrent_enqueue_distinct_pages_all_queue(self) -> None:
        for index in range(1, 6):
            self._write_image(f"c/distinct-{index}.png", f"img-{index}".encode("utf-8"))
        main.scan_images()
        page_ids = [int(row["id"]) for row in main.list_pages()["pages"]]
        self.assertEqual(len(page_ids), 5)

        barrier = threading.Barrier(len(page_ids))

        def enqueue_for(page_id: int) -> bool:
            barrier.wait(timeout=5)
            return pipeline_runtime.enqueue_job("ocr_extract", page_id=page_id, payload={"source": "concurrent"})

        with patch.object(pipeline_runtime, "_ensure_worker_running", return_value=None):
            with ThreadPoolExecutor(max_workers=5) as pool:
                results = list(pool.map(enqueue_for, page_ids))

        self.assertTrue(all(results))
        with db.get_session() as session:
            queued = (
                session.query(main.PipelineJob)
                .filter(main.PipelineJob.stage == "ocr_extract")
                .filter(main.PipelineJob.status == "queued")
                .count()
            )
            self.assertEqual(int(queued), 5)


if __name__ == "__main__":
    unittest.main()
