from __future__ import annotations

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app import config, db, discovery, final_export, layouts, main, ocr_extract, runtime_options
from app.config import DEFAULT_EXTENSIONS, Settings


class PipelineStreamContractsTests(unittest.TestCase):
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

        self._patchers = [
            patch.object(config, "settings", self.test_settings),
            patch.object(db, "settings", self.test_settings),
            patch.object(discovery, "settings", self.test_settings),
            patch.object(final_export, "settings", self.test_settings),
            patch.object(layouts, "settings", self.test_settings),
            patch.object(main, "settings", self.test_settings),
            patch.object(ocr_extract, "settings", self.test_settings),
            patch.object(runtime_options, "settings", self.test_settings),
        ]
        for patcher in self._patchers:
            patcher.start()
        db.init_db()
        runtime_options.reset_runtime_options_from_settings()

    def tearDown(self) -> None:
        for patcher in reversed(self._patchers):
            patcher.stop()
        self.temp_dir.cleanup()

    def test_stream_chunk_uses_sse_data_prefix_and_double_newline(self) -> None:
        class RequestStub:
            def __init__(self) -> None:
                self.calls = 0

            async def is_disconnected(self) -> bool:
                self.calls += 1
                return self.calls > 1

        async def fast_sleep(_seconds: float) -> None:
            return None

        snapshot = {
            "worker_running": False,
            "in_progress": None,
            "queued": {"total": 0, "by_stage": {}, "preview": []},
            "recent_events": [],
            "registered_stages": [],
        }

        async def collect_chunk() -> str:
            response = await main.pipeline_activity_stream(RequestStub(), limit=30)
            iterator = response.body_iterator
            chunk = await anext(iterator)
            await iterator.aclose()
            return chunk.decode("utf-8") if isinstance(chunk, bytes) else str(chunk)

        with patch("app.api.pipeline.get_activity_snapshot", return_value=snapshot), patch(
            "app.api.pipeline.asyncio.sleep",
            new=fast_sleep,
        ):
            text = asyncio.run(collect_chunk())

        self.assertTrue(text.startswith("data: "))
        self.assertTrue(text.endswith("\n\n"))
        payload = json.loads(text[len("data: ") : -2])
        self.assertEqual(payload["queued"]["total"], 0)

    def test_stream_clamps_limit_to_bounds(self) -> None:
        class RequestStub:
            def __init__(self) -> None:
                self.calls = 0

            async def is_disconnected(self) -> bool:
                self.calls += 1
                return self.calls > 1

        async def fast_sleep(_seconds: float) -> None:
            return None

        async def consume_once(limit: int, call_log: list[int]) -> None:
            def fake_snapshot(*, limit: int) -> dict[str, object]:
                call_log.append(int(limit))
                return {
                    "worker_running": False,
                    "in_progress": None,
                    "queued": {"total": 0, "by_stage": {}, "preview": []},
                    "recent_events": [],
                    "registered_stages": [],
                }

            with patch("app.api.pipeline.get_activity_snapshot", side_effect=fake_snapshot), patch(
                "app.api.pipeline.asyncio.sleep",
                new=fast_sleep,
            ):
                response = await main.pipeline_activity_stream(RequestStub(), limit=limit)
                iterator = response.body_iterator
                await anext(iterator)
                await iterator.aclose()

        calls_low: list[int] = []
        calls_high: list[int] = []
        asyncio.run(consume_once(0, calls_low))
        asyncio.run(consume_once(999, calls_high))
        self.assertEqual(calls_low, [1])
        self.assertEqual(calls_high, [200])


if __name__ == "__main__":
    unittest.main()
