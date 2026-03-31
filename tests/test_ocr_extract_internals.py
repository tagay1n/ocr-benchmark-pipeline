from __future__ import annotations

from contextlib import ExitStack
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app import config, db, discovery, final_export, layouts, main, ocr_extract, runtime_options
from app.config import DEFAULT_EXTENSIONS, Settings
from app.lookalikes import detect_suspicious_lookalikes, normalize_text_nfc


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

    def test_prompt_for_layout_maps_output_formats(self) -> None:
        prompt_template = (
            "{class_rule}\n"
            "{format_rule}"
        )

        markdown_prompt, markdown_fmt = ocr_extract._prompt_for_layout(
            {"class_name": "text"},
            prompt_template=prompt_template,
        )
        self.assertEqual(markdown_fmt, "markdown")
        self.assertIn("valid Markdown", markdown_prompt)
        self.assertIn("Keep text as normal Markdown paragraphs.", markdown_prompt)
        section_prompt, section_fmt = ocr_extract._prompt_for_layout(
            {"class_name": "section_header"},
            prompt_template=prompt_template,
        )
        self.assertEqual(section_fmt, "markdown")
        self.assertIn("Treat this crop as heading-like text.", section_prompt)
        self.assertIn("Keep text as normal Markdown paragraphs.", section_prompt)
        picture_text_prompt, picture_text_fmt = ocr_extract._prompt_for_layout(
            {"class_name": "picture_text"},
            prompt_template=prompt_template,
        )
        self.assertEqual(picture_text_fmt, "markdown")
        self.assertIn("Keep text as normal Markdown paragraphs.", picture_text_prompt)
        page_header_prompt, page_header_fmt = ocr_extract._prompt_for_layout(
            {"class_name": "page_header"},
            prompt_template=prompt_template,
        )
        self.assertEqual(page_header_fmt, "markdown")
        self.assertIn("Keep text as normal Markdown paragraphs.", page_header_prompt)
        page_footer_prompt, page_footer_fmt = ocr_extract._prompt_for_layout(
            {"class_name": "page_footer"},
            prompt_template=prompt_template,
        )
        self.assertEqual(page_footer_fmt, "markdown")
        self.assertIn("Keep text as normal Markdown paragraphs.", page_footer_prompt)
        list_item_prompt, list_item_fmt = ocr_extract._prompt_for_layout(
            {"class_name": "list_item"},
            prompt_template=prompt_template,
        )
        self.assertEqual(list_item_fmt, "markdown")
        self.assertIn("exactly one list item", list_item_prompt)
        self.assertIn("do not invent marker symbols or numbering", list_item_prompt)
        footnote_prompt, footnote_fmt = ocr_extract._prompt_for_layout(
            {"class_name": "footnote"},
            prompt_template=prompt_template,
        )
        self.assertEqual(footnote_fmt, "markdown")
        self.assertIn("Keep text as normal Markdown paragraphs.", footnote_prompt)
        self.assertIn("Keep content as literal footnote text.", footnote_prompt)
        self.assertIn("Do not convert output to Markdown footnote syntax", footnote_prompt)

        html_prompt, html_fmt = ocr_extract._prompt_for_layout(
            {"class_name": "table"},
            prompt_template=prompt_template,
        )
        self.assertEqual(html_fmt, "html")
        self.assertIn("<table>", html_prompt)

        latex_prompt, latex_fmt = ocr_extract._prompt_for_layout(
            {"class_name": "formula"},
            prompt_template=prompt_template,
        )
        self.assertEqual(latex_fmt, "latex")
        self.assertIn("standalone display formula", latex_prompt)
        self.assertIn("LaTeX", latex_prompt)

        skip_prompt, skip_fmt = ocr_extract._prompt_for_layout(
            {"class_name": "picture"},
            prompt_template=prompt_template,
        )
        self.assertEqual(skip_fmt, "skip")
        self.assertEqual(skip_prompt, "")

        caption_prompt, caption_fmt = ocr_extract._prompt_for_layout(
            {"class_name": "caption"},
            prompt_template=prompt_template,
        )
        self.assertEqual(caption_fmt, "markdown")
        self.assertIn("caption text only", caption_prompt)

    def test_prompt_for_layout_class_matrix_regression(self) -> None:
        template = "class_rule={class_rule}; rule={format_rule}"
        expected = {
            "text": "markdown",
            "section_header": "markdown",
            "page_header": "markdown",
            "page_footer": "markdown",
            "list_item": "markdown",
            "picture_text": "markdown",
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
                prompt_template=template,
            )
            self.assertEqual(fmt, output_format)
            if output_format == "skip":
                self.assertEqual(prompt, "")
            else:
                self.assertIn("rule=", prompt)

    def test_key_alias_short_and_long_keys(self) -> None:
        self.assertEqual(ocr_extract._key_alias("abcd1234"), "abcd1234")
        self.assertEqual(ocr_extract._key_alias("very-long-secret-key"), "very...-key")

    def test_is_quota_error_matches_relevant_messages(self) -> None:
        self.assertTrue(ocr_extract._is_quota_error("HTTP 429 quota exceeded"))
        self.assertTrue(ocr_extract._is_quota_error("RESOURCE_EXHAUSTED"))
        self.assertTrue(ocr_extract._is_quota_error("rate limit reached"))
        self.assertFalse(ocr_extract._is_quota_error("HTTP 500 internal error"))
        self.assertTrue(
            ocr_extract._is_daily_quota_exhausted_error(
                "HTTP 429 RESOURCE_EXHAUSTED GenerateRequestsPerDayPerProjectPerModel-FreeTier"
            )
        )
        self.assertFalse(ocr_extract._is_daily_quota_exhausted_error("HTTP 429 rate limit reached"))

    def test_is_gemini_server_error_matches_timeout_and_http_5xx(self) -> None:
        self.assertTrue(ocr_extract._is_gemini_server_error("The read operation timed out"))
        self.assertTrue(ocr_extract._is_gemini_server_error("Gemini request failed with HTTP 503: backend unavailable"))
        self.assertFalse(ocr_extract._is_gemini_server_error("HTTP 429 quota exceeded"))
        self.assertFalse(ocr_extract._is_gemini_server_error("validation error in prompt"))

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
        self.assertEqual(ocr_extract._next_available_key([], exclude_keys={"k1"}), "k2")
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
        self.assertEqual(ocr_extract._extract_text_from_response(payload), "A  B")

    def test_extract_content_from_json_response_validates_schema(self) -> None:
        self.assertEqual(
            ocr_extract._extract_content_from_json_response('{"content":"ok"}'),
            "ok",
        )
        with self.assertRaisesRegex(RuntimeError, "not valid JSON"):
            ocr_extract._extract_content_from_json_response("not-json")
        with self.assertRaisesRegex(RuntimeError, "must be an object"):
            ocr_extract._extract_content_from_json_response('["content"]')
        with self.assertRaisesRegex(RuntimeError, "exactly one key"):
            ocr_extract._extract_content_from_json_response('{"content":"ok","extra":"x"}')
        with self.assertRaisesRegex(RuntimeError, '"content" must be a string'):
            ocr_extract._extract_content_from_json_response('{"content":1}')

    def test_normalize_formula_latex_content_strips_wrappers(self) -> None:
        self.assertEqual(ocr_extract._normalize_formula_latex_content("$x+y$"), "x+y")
        self.assertEqual(ocr_extract._normalize_formula_latex_content("$$\n\\frac{a}{b}\n$$"), "\\frac{a}{b}")
        self.assertEqual(ocr_extract._normalize_formula_latex_content("\\[z^2\\]"), "z^2")
        self.assertEqual(ocr_extract._normalize_formula_latex_content("```latex\nx^2+y^2\n```"), "x^2+y^2")

    def test_section_header_level_assignment_from_geometry(self) -> None:
        layouts = [
            {"id": 1, "class_name": "text", "bbox": {"y1": 0.10, "y2": 0.13}},
            {"id": 2, "class_name": "text", "bbox": {"y1": 0.30, "y2": 0.33}},
            {"id": 3, "class_name": "section_header", "bbox": {"y1": 0.00, "y2": 0.09}},
            {"id": 4, "class_name": "section_header", "bbox": {"y1": 0.20, "y2": 0.255}},
            {"id": 5, "class_name": "section_header", "bbox": {"y1": 0.50, "y2": 0.54}},
        ]
        levels = ocr_extract._section_header_levels_by_layout_id(layouts)
        self.assertEqual(levels[3], 2)
        self.assertEqual(levels[4], 3)
        self.assertEqual(levels[5], 4)

    def test_apply_section_header_heading_level_normalizes_first_nonempty_line(self) -> None:
        self.assertEqual(
            ocr_extract._apply_section_header_heading_level("Title line", 3),
            "### Title line",
        )
        self.assertEqual(
            ocr_extract._apply_section_header_heading_level("\n  ## Existing heading", 2),
            "## Existing heading",
        )
        self.assertEqual(
            ocr_extract._apply_section_header_heading_level("***Header***.", 4),
            "#### Header.",
        )
        self.assertEqual(
            ocr_extract._apply_section_header_heading_level("Header with *term*", 4),
            "#### Header with *term*",
        )

    def test_list_item_indent_level_and_normalization(self) -> None:
        self.assertEqual(ocr_extract._list_item_indent_level_from_x1(0.20, 0.20), 0)
        self.assertEqual(ocr_extract._list_item_indent_level_from_x1(0.26, 0.20), 2)
        self.assertEqual(
            ocr_extract._normalize_list_item_line("1) Item", indent_level=1),
            "  1) Item",
        )
        self.assertEqual(
            ocr_extract._normalize_list_item_line("• Item", indent_level=0),
            "- Item",
        )
        self.assertEqual(
            ocr_extract._normalize_list_item_line("Item without marker", indent_level=2),
            "    - Item without marker",
        )

    def test_list_item_indent_levels_by_layout_id(self) -> None:
        layouts = [
            {"id": 11, "class_name": "list_item", "bbox": {"x1": 0.10}},
            {"id": 12, "class_name": "list_item", "bbox": {"x1": 0.16}},
            {"id": 13, "class_name": "list_item", "bbox": {"x1": 0.25}},
            {"id": 14, "class_name": "text", "bbox": {"x1": 0.05}},
        ]
        levels = ocr_extract._list_item_indent_levels_by_layout_id(layouts)
        self.assertEqual(levels[11], 0)
        self.assertGreaterEqual(levels[12], 1)
        self.assertGreaterEqual(levels[13], levels[12])

    def test_normalize_text_nfc_collapses_equivalent_unicode_sequences(self) -> None:
        decomposed = "е\u0308"  # cyrillic e + combining diaeresis
        composed = normalize_text_nfc(decomposed)
        self.assertEqual(composed, "ё")

    def test_detect_suspicious_lookalikes_marks_line_and_token(self) -> None:
        text = "Бу сeр\n`код сeр`\n```\nсeр\n```"
        warnings = detect_suspicious_lookalikes(text, markdown_code_aware=True)
        self.assertEqual(len(warnings), 1)
        warning = warnings[0]
        self.assertEqual(warning["line_number"], 1)
        self.assertEqual(warning["token"], "сeр")
        self.assertEqual(warning["normalized_token"], "сер")
        self.assertEqual(warning["replacements"][0]["from"], "e")
        self.assertEqual(warning["replacements"][0]["to"], "е")

    def test_detect_suspicious_lookalikes_marks_standalone_latin_confusable_letter(self) -> None:
        text = "Бу Á"
        warnings = detect_suspicious_lookalikes(text, markdown_code_aware=True)
        self.assertEqual(len(warnings), 1)
        warning = warnings[0]
        self.assertEqual(warning["line_number"], 1)
        self.assertEqual(warning["token"], "Á")
        self.assertEqual(warning["normalized_token"], "А")
        self.assertEqual(warning["replacements"][0]["from"], "Á")
        self.assertEqual(warning["replacements"][0]["to"], "А")

    def test_crop_layout_png_bytes_rotates_vertical_clip_when_requested(self) -> None:
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow is required for crop rotation tests.")

        image_path = self.test_settings.source_dir / "ocr" / "rotate-source.png"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new("RGB", (2, 3))
        image.putdata(
            [
                (255, 0, 0),   # (0,0)
                (0, 255, 0),   # (1,0)
                (0, 0, 255),   # (0,1)
                (255, 255, 0), # (1,1)
                (0, 255, 255), # (0,2)
                (255, 0, 255), # (1,2)
            ]
        )
        image.save(image_path, format="PNG")

        bbox = {"x1": 0.0, "y1": 0.0, "x2": 1.0, "y2": 1.0}
        raw_bytes = ocr_extract._crop_layout_png_bytes(image_path, bbox)
        rotated_bytes = ocr_extract._crop_layout_png_bytes(
            image_path,
            bbox,
            rotate_for_vertical=True,
        )

        with Image.open(BytesIO(raw_bytes)) as raw_image, Image.open(BytesIO(rotated_bytes)) as rotated_image:
            self.assertEqual(raw_image.size, (2, 3))
            self.assertEqual(rotated_image.size, (3, 2))
            self.assertEqual(raw_image.getpixel((0, 0)), (255, 0, 0))
            self.assertEqual(rotated_image.getpixel((0, 0)), (0, 255, 255))
            self.assertEqual(rotated_image.getpixel((2, 0)), (255, 0, 0))

    def test_extract_ocr_for_page_rotates_vertical_markdown_clips_before_gemini(self) -> None:
        self._write_image("ocr/vertical-rotate-flag.png")
        main.scan_images()
        page_id = self._single_page_id()
        main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="text",
                reading_order=1,
                orientation="vertical",
                bbox=main.BBoxPayload(x1=0.1, y1=0.05, x2=0.2, y2=0.9),
            ),
        )
        main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="text",
                reading_order=2,
                orientation="horizontal",
                bbox=main.BBoxPayload(x1=0.3, y1=0.1, x2=0.9, y2=0.25),
            ),
        )

        with patch.object(ocr_extract, "_crop_layout_png_bytes", return_value=b"png-bytes") as crop_mock, patch.object(
            ocr_extract,
            "_gemini_generate_content",
            side_effect=["vertical-text", "horizontal-text"],
        ):
            result = ocr_extract.extract_ocr_for_page(page_id)

        self.assertEqual(result["extracted_count"], 2)
        self.assertEqual(crop_mock.call_count, 2)
        first_kwargs = crop_mock.call_args_list[0].kwargs
        second_kwargs = crop_mock.call_args_list[1].kwargs
        self.assertTrue(bool(first_kwargs.get("rotate_for_vertical")))
        self.assertFalse(bool(second_kwargs.get("rotate_for_vertical")))

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

    def test_extract_ocr_for_page_applies_nfc_normalization_to_saved_content(self) -> None:
        self._write_image("ocr/nfc.png")
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
            ocr_extract, "_gemini_generate_content", return_value="ё and е\u0308"
        ):
            ocr_extract.extract_ocr_for_page(page_id, layout_ids=[int(layout["id"])], max_retries_per_layout=1)

        outputs = main.page_ocr_outputs(page_id)["outputs"]
        self.assertEqual(len(outputs), 1)
        content = outputs[0]["content"]
        self.assertEqual(content, "ё and ё")

    def test_extract_ocr_for_page_formats_section_header_from_geometry(self) -> None:
        self._write_image("ocr/section-header.png")
        main.scan_images()
        page_id = self._single_page_id()
        main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="text",
                reading_order=1,
                bbox=main.BBoxPayload(x1=0.0, y1=0.15, x2=1.0, y2=0.19),
            ),
        )
        section_layout = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="section_header",
                reading_order=2,
                bbox=main.BBoxPayload(x1=0.0, y1=0.01, x2=1.0, y2=0.11),
            ),
        )["layout"]

        with patch.object(ocr_extract, "_crop_layout_png_bytes", return_value=b"png-bytes"), patch.object(
            ocr_extract, "_gemini_generate_content", side_effect=["Body text", "Header text"]
        ):
            ocr_extract.extract_ocr_for_page(page_id)

        outputs = main.page_ocr_outputs(page_id)["outputs"]
        by_layout = {int(output["layout_id"]): output for output in outputs}
        section_output = by_layout[int(section_layout["id"])]
        self.assertEqual(section_output["class_name"], "section_header")
        self.assertTrue(str(section_output["content"]).startswith("## "))

    def test_extract_ocr_for_page_formats_list_items_with_markers_and_indent(self) -> None:
        self._write_image("ocr/list-item-formatting.png")
        main.scan_images()
        page_id = self._single_page_id()
        root_item = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="list_item",
                reading_order=1,
                bbox=main.BBoxPayload(x1=0.10, y1=0.10, x2=0.90, y2=0.14),
            ),
        )["layout"]
        nested_item = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="list_item",
                reading_order=2,
                bbox=main.BBoxPayload(x1=0.18, y1=0.15, x2=0.90, y2=0.19),
            ),
        )["layout"]
        ordered_item = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="list_item",
                reading_order=3,
                bbox=main.BBoxPayload(x1=0.10, y1=0.20, x2=0.90, y2=0.24),
            ),
        )["layout"]

        with patch.object(ocr_extract, "_crop_layout_png_bytes", return_value=b"png-bytes"), patch.object(
            ocr_extract, "_gemini_generate_content", side_effect=["Root", "Nested", "3) Ordered"]
        ):
            ocr_extract.extract_ocr_for_page(page_id)

        outputs = main.page_ocr_outputs(page_id)["outputs"]
        by_layout = {int(output["layout_id"]): output for output in outputs}
        self.assertEqual(str(by_layout[int(root_item["id"])]["content"]), "- Root")
        self.assertRegex(str(by_layout[int(nested_item["id"])]["content"]), r"^\s+-\s+Nested$")
        self.assertEqual(str(by_layout[int(ordered_item["id"])]["content"]), "3) Ordered")

    def test_extract_ocr_for_page_normalizes_formula_content(self) -> None:
        self._write_image("ocr/formula-normalize.png")
        main.scan_images()
        page_id = self._single_page_id()
        formula_layout = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="formula",
                reading_order=1,
                bbox=main.BBoxPayload(x1=0.10, y1=0.10, x2=0.90, y2=0.30),
            ),
        )["layout"]

        with patch.object(ocr_extract, "_crop_layout_png_bytes", return_value=b"png-bytes"), patch.object(
            ocr_extract, "_gemini_generate_content", return_value="```latex\n$$x^2+y^2$$\n```"
        ):
            ocr_extract.extract_ocr_for_page(page_id)

        outputs = main.page_ocr_outputs(page_id)["outputs"]
        by_layout = {int(output["layout_id"]): output for output in outputs}
        self.assertEqual(by_layout[int(formula_layout["id"])]["output_format"], "latex")
        self.assertEqual(str(by_layout[int(formula_layout["id"])]["content"]), "x^2+y^2")

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
                raise RuntimeError("HTTP 429 RESOURCE_EXHAUSTED GenerateRequestsPerDayPerProjectPerModel-FreeTier")
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

    def test_extract_ocr_rate_limit_rotates_without_persisting_exhausted_key(self) -> None:
        self._write_image("ocr/rate-limit.png")
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
                raise RuntimeError("HTTP 429 rate limit reached")
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
        if usage_path.exists():
            self.assertEqual(json.loads(usage_path.read_text(encoding="utf-8")), [])

    def test_extract_ocr_quota_rotation_is_not_limited_by_non_quota_retries(self) -> None:
        self.test_settings = Settings(
            project_root=self.project_root,
            source_dir=self.project_root / "input",
            db_path=self.project_root / "data" / "test.db",
            result_dir=self.project_root / "result",
            allowed_extensions=DEFAULT_EXTENSIONS,
            enable_background_jobs=False,
            gemini_keys=("k1", "k2", "k3", "k4"),
            gemini_usage_path=self.project_root / "_artifacts" / "gemini_usage.json",
        )
        self.stack.close()
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(config, "settings", self.test_settings))
        self.stack.enter_context(patch.object(db, "settings", self.test_settings))
        self.stack.enter_context(patch.object(discovery, "settings", self.test_settings))
        self.stack.enter_context(patch.object(layouts, "settings", self.test_settings))
        self.stack.enter_context(patch.object(main, "settings", self.test_settings))
        self.stack.enter_context(patch.object(ocr_extract, "settings", self.test_settings))
        self.stack.enter_context(patch.object(runtime_options, "settings", self.test_settings))
        db.init_db()
        runtime_options.reset_runtime_options_from_settings()

        self._write_image("ocr/quota-rotation-many-keys.png")
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
            if api_key in {"k1", "k2", "k3"}:
                raise RuntimeError(
                    "HTTP 429 RESOURCE_EXHAUSTED "
                    "GenerateRequestsPerDayPerProjectPerModel-FreeTier"
                )
            return "from-k4"

        with patch.object(ocr_extract, "_crop_layout_png_bytes", return_value=b"png-bytes"), patch.object(
            ocr_extract, "_gemini_generate_content", side_effect=fake_call
        ):
            result = ocr_extract.extract_ocr_for_page(
                page_id,
                layout_ids=[int(layout["id"])],
                max_retries_per_layout=1,
            )

        self.assertEqual(result["requests_count"], 1)
        outputs = main.page_ocr_outputs(page_id)["outputs"]
        self.assertEqual(outputs[0]["content"], "from-k4")
        self.assertEqual(outputs[0]["key_alias"], "k4")
        usage_path = Path(self.test_settings.gemini_usage_path or "")
        self.assertEqual(json.loads(usage_path.read_text(encoding="utf-8")), ["k1", "k2", "k3"])

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
            result = ocr_extract.extract_ocr_for_page(
                page_id,
                layout_ids=[int(layout["id"])],
                max_retries_per_layout=2,
            )

        self.assertEqual(result["status"], "ocr_done")
        self.assertEqual(result["extracted_count"], 0)
        self.assertEqual(result["failed_count"], 1)
        self.assertEqual(result["failed_layout_ids"], [int(layout["id"])])
        outputs = main.page_ocr_outputs(page_id)["outputs"]
        self.assertEqual(len(outputs), 1)
        self.assertEqual(outputs[0]["extraction_status"], "failed")
        self.assertIn("HTTP 500 transient", str(outputs[0]["error_message"]))
        self.assertEqual(main.page_details(page_id)["page"]["status"], "ocr_done")

        usage_path = Path(self.test_settings.gemini_usage_path or "")
        if usage_path.exists():
            self.assertEqual(json.loads(usage_path.read_text(encoding="utf-8")), [])

    def test_extract_ocr_continues_on_server_error_when_enabled(self) -> None:
        self._write_image("ocr/continue-on-timeout.png")
        main.scan_images()
        page_id = self._single_page_id()
        first = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="text",
                reading_order=1,
                bbox=main.BBoxPayload(x1=0.0, y1=0.0, x2=0.45, y2=1.0),
            ),
        )["layout"]
        second = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="text",
                reading_order=2,
                bbox=main.BBoxPayload(x1=0.55, y1=0.0, x2=1.0, y2=1.0),
            ),
        )["layout"]

        with patch.object(ocr_extract, "_crop_layout_png_bytes", return_value=b"png-bytes"), patch.object(
            ocr_extract,
            "_gemini_generate_content",
            side_effect=[RuntimeError("The read operation timed out"), "second-ok"],
        ):
            result = ocr_extract.extract_ocr_for_page(
                page_id,
                continue_on_server_error=True,
                max_retries_per_layout=1,
            )

        self.assertEqual(result["status"], "ocr_done")
        self.assertEqual(result["extracted_count"], 1)
        self.assertEqual(result["failed_count"], 1)
        self.assertEqual(result["failed_layout_ids"], [int(first["id"])])
        self.assertEqual(result["requests_count"], 1)

        page_payload = main.page_details(page_id)
        self.assertEqual(page_payload["page"]["status"], "ocr_done")

        outputs = main.page_ocr_outputs(page_id)["outputs"]
        self.assertEqual(len(outputs), 2)
        by_layout = {int(row["layout_id"]): row for row in outputs}
        self.assertEqual(str(by_layout[int(second["id"])]["content"]), "second-ok")
        self.assertEqual(str(by_layout[int(second["id"])]["extraction_status"]), "ok")
        self.assertEqual(str(by_layout[int(first["id"])]["extraction_status"]), "failed")
        self.assertIn("timed out", str(by_layout[int(first["id"])]["error_message"]).lower())

    def test_extract_ocr_uses_selected_supported_model_for_manual_reextract(self) -> None:
        self._write_image("ocr/model-override.png")
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
            ocr_extract,
            "_gemini_generate_content",
            side_effect=RuntimeError("default model helper should not be called"),
        ) as default_model_mock, patch.object(
            ocr_extract,
            "_gemini_generate_content_with_model",
            return_value="Model override text",
        ) as override_model_mock:
            result = ocr_extract.extract_ocr_for_page(
                page_id,
                layout_ids=[int(layout["id"])],
                model_name="gemini-2.5-flash",
            )

        self.assertEqual(result["model"], "gemini-2.5-flash")
        default_model_mock.assert_not_called()
        override_model_mock.assert_called_once()
        outputs = main.page_ocr_outputs(page_id)["outputs"]
        self.assertEqual(len(outputs), 1)
        self.assertEqual(str(outputs[0]["model_name"]), "gemini-2.5-flash")

    def test_extract_ocr_rejects_unsupported_model_name(self) -> None:
        self._write_image("ocr/unsupported-model.png")
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

        with self.assertRaisesRegex(ValueError, "Unsupported OCR model"):
            ocr_extract.extract_ocr_for_page(
                page_id,
                layout_ids=[int(layout["id"])],
                model_name="gemini-unknown",
            )


if __name__ == "__main__":
    unittest.main()
