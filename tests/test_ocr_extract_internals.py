from __future__ import annotations

from contextlib import ExitStack
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app import config, db, discovery, final_export, layouts, main, ocr_extract, runtime_options
from app.config import DEFAULT_EXTENSIONS, Settings


class OcrExtractInternalsTests(unittest.TestCase):
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
            gemini_keys=("k1", "k2"),
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

    def _write_image(self, rel_path: str, content: bytes = b"fake-image-bytes") -> None:
        path = self.test_settings.source_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def _single_page_id(self) -> int:
        pages = main.list_pages()["pages"]
        self.assertEqual(len(pages), 1)
        return int(pages[0]["id"])

    def test_prompt_for_layout_maps_output_formats_and_caption_targets(self) -> None:
        prompt_template = (
            "Layout class: {class_name}.{caption_line}\n"
            "Targets: {caption_targets}\n"
            "{format_rule}"
        )

        markdown_prompt, markdown_fmt = ocr_extract._prompt_for_layout(
            {"class_name": "text"},
            [],
            prompt_template=prompt_template,
        )
        self.assertEqual(markdown_fmt, "markdown")
        self.assertIn("valid Markdown", markdown_prompt)

        html_prompt, html_fmt = ocr_extract._prompt_for_layout(
            {"class_name": "table"},
            [],
            prompt_template=prompt_template,
        )
        self.assertEqual(html_fmt, "html")
        self.assertIn("<table>", html_prompt)

        latex_prompt, latex_fmt = ocr_extract._prompt_for_layout(
            {"class_name": "formula"},
            [],
            prompt_template=prompt_template,
        )
        self.assertEqual(latex_fmt, "latex")
        self.assertIn("LaTeX", latex_prompt)

        skip_prompt, skip_fmt = ocr_extract._prompt_for_layout(
            {"class_name": "picture"},
            [],
            prompt_template=prompt_template,
        )
        self.assertEqual(skip_fmt, "skip")
        self.assertEqual(skip_prompt, "")

        caption_prompt, caption_fmt = ocr_extract._prompt_for_layout(
            {"class_name": "caption"},
            ["table [id:9]", "formula [id:11]"],
            prompt_template=prompt_template,
        )
        self.assertEqual(caption_fmt, "markdown")
        self.assertIn("Caption targets: table [id:9], formula [id:11].", caption_prompt)
        self.assertIn("Targets: table [id:9], formula [id:11]", caption_prompt)

    def test_prompt_for_layout_class_matrix_regression(self) -> None:
        template = "class={class_name}; targets={caption_targets}; rule={format_rule}{caption_line}"
        expected = {
            "text": "markdown",
            "title": "markdown",
            "section_header": "markdown",
            "page_header": "markdown",
            "page_footer": "markdown",
            "list_item": "markdown",
            "footnote": "markdown",
            "caption": "markdown",
            "table": "html",
            "formula": "latex",
            "picture": "skip",
            "unknown_custom": "markdown",
        }
        for class_name, output_format in expected.items():
            prompt, fmt = ocr_extract._prompt_for_layout(
                {"class_name": class_name},
                ["table [id:1]"] if class_name == "caption" else [],
                prompt_template=template,
            )
            self.assertEqual(fmt, output_format)
            if output_format == "skip":
                self.assertEqual(prompt, "")
            else:
                self.assertIn(f"class={class_name}", prompt)

    def test_key_alias_short_and_long_keys(self) -> None:
        self.assertEqual(ocr_extract._key_alias("abcd1234"), "abcd1234")
        self.assertEqual(ocr_extract._key_alias("very-long-secret-key"), "very...-key")

    def test_is_quota_error_matches_relevant_messages(self) -> None:
        self.assertTrue(ocr_extract._is_quota_error("HTTP 429 quota exceeded"))
        self.assertTrue(ocr_extract._is_quota_error("RESOURCE_EXHAUSTED"))
        self.assertTrue(ocr_extract._is_quota_error("rate limit reached"))
        self.assertFalse(ocr_extract._is_quota_error("HTTP 500 internal error"))

    def test_usage_state_roundtrip_and_invalid_payload_handling(self) -> None:
        usage_path = self.test_settings.gemini_usage_path
        self.assertIsNotNone(usage_path)
        path = Path(usage_path)

        self.assertEqual(ocr_extract._load_usage_state(), [])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{bad json", encoding="utf-8")
        self.assertEqual(ocr_extract._load_usage_state(), [])

        path.write_text(json.dumps({"exhausted": ["k1"]}), encoding="utf-8")
        self.assertEqual(ocr_extract._load_usage_state(), [])

        ocr_extract._save_usage_state(["k1", "k2"])
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), ["k1", "k2"])

        path.write_text(json.dumps(["k1", "k1", " ", "k2"]), encoding="utf-8")
        self.assertEqual(ocr_extract._load_usage_state(), ["k1", "k2"])

    def test_next_available_key_skips_exhausted_and_raises_when_empty(self) -> None:
        self.assertEqual(ocr_extract._next_available_key([]), "k1")
        self.assertEqual(ocr_extract._next_available_key(["k1"]), "k2")
        with self.assertRaises(ocr_extract.GeminiQuotaExhaustedError):
            ocr_extract._next_available_key(["k1", "k2"])

    def test_extract_text_from_response_collects_nonempty_parts(self) -> None:
        payload = {
            "candidates": [
                {"content": {"parts": [{"text": "A"}, {"text": "  "}, {"text": "B"}]}},
                {"content": {"parts": [{"text": "C"}]}},
                {"not_content": True},
            ]
        }
        self.assertEqual(ocr_extract._extract_text_from_response(payload), "A\nB\nC")

    def test_extract_ocr_for_page_rejects_unknown_layout_ids(self) -> None:
        self._write_image("ocr/a.png")
        main.scan_images()
        page_id = self._single_page_id()
        layout = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="text",
                reading_order=1,
                bbox=main.BBoxPayload(x1=0.0, y1=0.0, x2=1.0, y2=1.0),
            ),
        )["layout"]

        with patch.object(ocr_extract, "_crop_layout_png_bytes", return_value=b"png-bytes"), patch.object(
            ocr_extract, "_gemini_generate_content", return_value="ok"
        ):
            with self.assertRaisesRegex(ValueError, "not present on this page"):
                ocr_extract.extract_ocr_for_page(page_id, layout_ids=[int(layout["id"]), 99999])

    def test_extract_ocr_for_page_selection_normalization_and_ordering(self) -> None:
        self._write_image("ocr/selection.png")
        main.scan_images()
        page_id = self._single_page_id()

        first = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="text",
                reading_order=1,
                bbox=main.BBoxPayload(x1=0.0, y1=0.0, x2=0.3, y2=0.3),
            ),
        )["layout"]
        second = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="text",
                reading_order=2,
                bbox=main.BBoxPayload(x1=0.35, y1=0.0, x2=0.65, y2=0.3),
            ),
        )["layout"]
        third = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="text",
                reading_order=3,
                bbox=main.BBoxPayload(x1=0.7, y1=0.0, x2=1.0, y2=0.3),
            ),
        )["layout"]

        # Existing output to verify selected-layout deletion/replacement only.
        with db.get_session() as session:
            now = main._utc_now()
            session.add(
                main.OcrOutput(
                    layout_id=int(second["id"]),
                    page_id=page_id,
                    class_name="text",
                    output_format="markdown",
                    content="old-second",
                    model_name="test",
                    key_alias="k",
                    created_at=now,
                    updated_at=now,
                )
            )

        with patch.object(ocr_extract, "_crop_layout_png_bytes", return_value=b"png-bytes"), patch.object(
            ocr_extract, "_gemini_generate_content", side_effect=["new-first", "new-third"]
        ):
            result = ocr_extract.extract_ocr_for_page(
                page_id,
                layout_ids=[int(third["id"]), int(third["id"]), -1, int(first["id"])],
            )

        self.assertEqual(result["layouts_total"], 3)
        self.assertEqual(result["layouts_selected"], 2)
        self.assertEqual(result["extracted_count"], 2)
        self.assertEqual(result["requests_count"], 2)

        outputs = main.page_ocr_outputs(page_id)["outputs"]
        by_layout = {int(output["layout_id"]): output["content"] for output in outputs}
        self.assertEqual(by_layout[int(first["id"])], "new-first")
        self.assertEqual(by_layout[int(third["id"])], "new-third")
        self.assertEqual(by_layout[int(second["id"])], "old-second")

    def test_extract_ocr_for_page_skip_layout_writes_skip_output_without_requests(self) -> None:
        self.test_settings = Settings(
            project_root=self.project_root,
            source_dir=self.project_root / "input",
            db_path=self.project_root / "data" / "test.db",
            result_dir=self.project_root / "result",
            allowed_extensions=DEFAULT_EXTENSIONS,
            enable_background_jobs=False,
            gemini_keys=(),
            gemini_usage_path=self.project_root / "_artifacts" / "gemini_usage.json",
        )
        self.stack.close()
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

        self._write_image("ocr/picture-only.png")
        main.scan_images()
        page_id = self._single_page_id()
        picture = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="picture",
                reading_order=1,
                bbox=main.BBoxPayload(x1=0.1, y1=0.1, x2=0.9, y2=0.9),
            ),
        )["layout"]

        with patch.object(ocr_extract, "_gemini_generate_content") as gemini_mock:
            result = ocr_extract.extract_ocr_for_page(page_id)

        gemini_mock.assert_not_called()
        self.assertEqual(result["skipped_count"], 1)
        self.assertEqual(result["requests_count"], 0)
        outputs = main.page_ocr_outputs(page_id)["outputs"]
        self.assertEqual(len(outputs), 1)
        self.assertEqual(int(outputs[0]["layout_id"]), int(picture["id"]))
        self.assertEqual(outputs[0]["output_format"], "skip")
        self.assertEqual(outputs[0]["content"], "")

    def test_extract_ocr_retries_with_next_key_on_quota_error(self) -> None:
        self._write_image("ocr/keys.png")
        main.scan_images()
        page_id = self._single_page_id()
        layout = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="text",
                reading_order=1,
                bbox=main.BBoxPayload(x1=0.0, y1=0.0, x2=1.0, y2=1.0),
            ),
        )["layout"]

        def fake_call(api_key: str, prompt: str, image_bytes: bytes, *, temperature: float = 0.0) -> str:
            del prompt, image_bytes, temperature
            if api_key == "k1":
                raise RuntimeError("HTTP 429 quota exceeded")
            return "from-k2"

        with patch.object(ocr_extract, "_crop_layout_png_bytes", return_value=b"png-bytes"), patch.object(
            ocr_extract, "_gemini_generate_content", side_effect=fake_call
        ):
            result = ocr_extract.extract_ocr_for_page(page_id, layout_ids=[int(layout["id"])], max_retries_per_layout=2)

        self.assertEqual(result["requests_count"], 1)
        outputs = main.page_ocr_outputs(page_id)["outputs"]
        self.assertEqual(outputs[0]["content"], "from-k2")
        self.assertEqual(outputs[0]["key_alias"], "k2")
        usage_path = Path(self.test_settings.gemini_usage_path or "")
        self.assertEqual(json.loads(usage_path.read_text(encoding="utf-8")), ["k1"])

    def test_extract_ocr_non_quota_error_does_not_mark_key_exhausted(self) -> None:
        self._write_image("ocr/non-quota.png")
        main.scan_images()
        page_id = self._single_page_id()
        layout = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="text",
                reading_order=1,
                bbox=main.BBoxPayload(x1=0.0, y1=0.0, x2=1.0, y2=1.0),
            ),
        )["layout"]

        with patch.object(ocr_extract, "_crop_layout_png_bytes", return_value=b"png-bytes"), patch.object(
            ocr_extract, "_gemini_generate_content", side_effect=RuntimeError("HTTP 500 transient")
        ):
            with self.assertRaisesRegex(RuntimeError, f"layout {int(layout['id'])}"):
                ocr_extract.extract_ocr_for_page(page_id, layout_ids=[int(layout["id"])], max_retries_per_layout=2)

        usage_path = Path(self.test_settings.gemini_usage_path or "")
        if usage_path.exists():
            self.assertEqual(json.loads(usage_path.read_text(encoding="utf-8")), [])


if __name__ == "__main__":
    unittest.main()
