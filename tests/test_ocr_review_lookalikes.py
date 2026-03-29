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

    def test_patch_ocr_output_flags_standalone_latin_confusable_on_save(self) -> None:
        self._write_image("review/confusable-latin-letter.png")
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

        patched = main.patch_ocr_output(int(layout["id"]), main.UpdateOcrOutputRequest(content="Бу Á"))
        self.assertEqual(int(patched["output"]["lookalike_warning_count"]), 1)
        self.assertEqual(str(patched["output"]["lookalike_warnings"][0]["token"]), "Á")
        self.assertEqual(str(patched["output"]["lookalike_warnings"][0]["normalized_token"]), "А")

    def test_page_ocr_outputs_includes_caption_bound_target_ids(self) -> None:
        self._write_image("review/caption-bounds.png")
        main.scan_images()
        page_id = int(main.list_pages()["pages"][0]["id"])

        caption_layout = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="caption",
                reading_order=1,
                bbox=main.BBoxPayload(x1=0.1, y1=0.8, x2=0.9, y2=0.95),
            ),
        )["layout"]
        picture_layout = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="picture",
                reading_order=2,
                bbox=main.BBoxPayload(x1=0.1, y1=0.1, x2=0.9, y2=0.7),
            ),
        )["layout"]

        main.put_page_caption_bindings(
            page_id,
            main.ReplaceCaptionBindingsRequest(
                bindings=[
                    main.CaptionBindingPayload(
                        caption_layout_id=int(caption_layout["id"]),
                        target_layout_ids=[int(picture_layout["id"])],
                    )
                ]
            ),
        )

        now = main._utc_now()
        with db.get_session() as session:
            session.add(
                main.OcrOutput(
                    layout_id=int(caption_layout["id"]),
                    page_id=page_id,
                    class_name="caption",
                    output_format="markdown",
                    content="Figure 1",
                    model_name="test",
                    key_alias="k",
                    created_at=now,
                    updated_at=now,
                )
            )
            session.add(
                main.OcrOutput(
                    layout_id=int(picture_layout["id"]),
                    page_id=page_id,
                    class_name="picture",
                    output_format="skip",
                    content="",
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

        outputs_by_layout_id = {
            int(row["layout_id"]): row for row in main.page_ocr_outputs(page_id)["outputs"]
        }
        self.assertEqual(
            outputs_by_layout_id[int(caption_layout["id"])]["bound_target_ids"],
            [int(picture_layout["id"])],
        )
        self.assertEqual(outputs_by_layout_id[int(picture_layout["id"])]["bound_target_ids"], [])

    def test_mark_ocr_reviewed_allows_ocr_failed_when_outputs_exist(self) -> None:
        self._write_image("review/failed-status-review.png")
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
                    content="Recovered OCR text",
                    model_name="test",
                    key_alias="k",
                    created_at=now,
                    updated_at=now,
                )
            )
            page = session.get(main.Page, page_id)
            self.assertIsNotNone(page)
            page.status = "ocr_failed"
            page.updated_at = now

        reviewed = main.complete_ocr_review(page_id)
        self.assertEqual(reviewed["status"], "ocr_reviewed")
        self.assertEqual(reviewed["output_count"], 1)
        self.assertEqual(main.page_details(page_id)["page"]["status"], "ocr_reviewed")

    def test_mark_ocr_reviewed_allows_layout_reviewed_when_outputs_exist(self) -> None:
        self._write_image("review/layout-reviewed-status-review.png")
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
                    content="Reviewed OCR text",
                    model_name="test",
                    key_alias="k",
                    created_at=now,
                    updated_at=now,
                )
            )
            page = session.get(main.Page, page_id)
            self.assertIsNotNone(page)
            page.status = "layout_reviewed"
            page.updated_at = now

        reviewed = main.complete_ocr_review(page_id)
        self.assertEqual(reviewed["status"], "ocr_reviewed")
        self.assertEqual(reviewed["output_count"], 1)

    def test_mark_ocr_reviewed_requires_failed_outputs_to_be_resolved(self) -> None:
        self._write_image("review/failed-output-must-be-resolved.png")
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
                    content="",
                    model_name="test",
                    key_alias="k",
                    extraction_status="failed",
                    error_message="timeout",
                    created_at=now,
                    updated_at=now,
                )
            )
            page = session.get(main.Page, page_id)
            self.assertIsNotNone(page)
            page.status = "ocr_done"
            page.updated_at = now

        with self.assertRaises(main.HTTPException) as error:
            main.complete_ocr_review(page_id)
        self.assertEqual(error.exception.status_code, 400)
        self.assertIn("failed", str(error.exception.detail).lower())

        patched = main.patch_ocr_output(int(layout["id"]), main.UpdateOcrOutputRequest(content="Manual fixed text"))
        self.assertEqual(str(patched["output"]["extraction_status"]), "manual")

        reviewed = main.complete_ocr_review(page_id)
        self.assertEqual(reviewed["status"], "ocr_reviewed")
        self.assertEqual(main.page_details(page_id)["page"]["status"], "ocr_reviewed")

    def test_mark_ocr_reviewed_requires_outputs_for_all_extractable_layouts(self) -> None:
        self._write_image("review/ocr-review-missing-required-output.png")
        main.scan_images()
        page_id = int(main.list_pages()["pages"][0]["id"])
        first = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="text",
                reading_order=1,
                bbox=main.BBoxPayload(x1=0.0, y1=0.0, x2=0.5, y2=0.5),
            ),
        )["layout"]
        second = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="text",
                reading_order=2,
                bbox=main.BBoxPayload(x1=0.5, y1=0.5, x2=1.0, y2=1.0),
            ),
        )["layout"]

        now = main._utc_now()
        with db.get_session() as session:
            session.add(
                main.OcrOutput(
                    layout_id=int(first["id"]),
                    page_id=page_id,
                    class_name="text",
                    output_format="markdown",
                    content="Only first output",
                    model_name="test",
                    key_alias="k",
                    created_at=now,
                    updated_at=now,
                )
            )
            page = session.get(main.Page, page_id)
            self.assertIsNotNone(page)
            page.status = "layout_reviewed"
            page.updated_at = now

        with self.assertRaises(main.HTTPException) as review_error:
            main.complete_ocr_review(page_id)
        self.assertEqual(review_error.exception.status_code, 400)
        self.assertIn("missing ocr outputs", str(review_error.exception.detail).lower())

        now = main._utc_now()
        with db.get_session() as session:
            session.add(
                main.OcrOutput(
                    layout_id=int(second["id"]),
                    page_id=page_id,
                    class_name="text",
                    output_format="markdown",
                    content="Second output",
                    model_name="test",
                    key_alias="k",
                    created_at=now,
                    updated_at=now,
                )
            )

        reviewed = main.complete_ocr_review(page_id)
        self.assertEqual(reviewed["status"], "ocr_reviewed")
        self.assertEqual(reviewed["output_count"], 2)


if __name__ == "__main__":
    unittest.main()
