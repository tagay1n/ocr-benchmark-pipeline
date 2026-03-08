from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app import config, db, discovery, final_export, layouts, main, ocr_extract, ocr_review, runtime_options
from app.config import DEFAULT_EXTENSIONS, Settings


class OcrReviewLookalikesTests(unittest.TestCase):
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

    def test_page_ocr_outputs_returns_lookalike_warnings_for_markdown(self) -> None:
        self._write_image("review/lookalike.png")
        main.scan_images()
        page_id = int(main.list_pages()["pages"][0]["id"])
        layout = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="text",
                reading_order=1,
                bbox=main.BBoxPayload(x1=0.0, y1=0.0, x2=1.0, y2=1.0),
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
                    content="Бу сeр",
                    model_name="test",
                    key_alias="k",
                    created_at=now,
                    updated_at=now,
                )
            )
            page = session.get(main.Page, page_id)
            self.assertIsNotNone(page)
            page.status = "ocr_done"
            page.updated_at = now

        outputs = main.page_ocr_outputs(page_id)["outputs"]
        self.assertEqual(len(outputs), 1)
        first = outputs[0]
        self.assertEqual(first["lookalike_warning_count"], 1)
        self.assertEqual(first["lookalike_warning_line_indexes"], [0])
        self.assertEqual(first["lookalike_warnings"][0]["token"], "сeр")
        self.assertEqual(first["lookalike_warnings"][0]["normalized_token"], "сер")

    def test_update_ocr_output_normalizes_nfc_before_persist(self) -> None:
        self._write_image("review/nfc.png")
        main.scan_images()
        page_id = int(main.list_pages()["pages"][0]["id"])
        layout = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="text",
                reading_order=1,
                bbox=main.BBoxPayload(x1=0.0, y1=0.0, x2=1.0, y2=1.0),
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
                    content="placeholder",
                    model_name="test",
                    key_alias="k",
                    created_at=now,
                    updated_at=now,
                )
            )
            page = session.get(main.Page, page_id)
            self.assertIsNotNone(page)
            page.status = "ocr_done"
            page.updated_at = now

        updated = main.patch_ocr_output(int(layout["id"]), main.UpdateOcrOutputRequest(content="е\u0308"))
        self.assertEqual(updated["output"]["content"], "ё")

        outputs = main.page_ocr_outputs(page_id)["outputs"]
        self.assertEqual(outputs[0]["content"], "ё")


if __name__ == "__main__":
    unittest.main()
