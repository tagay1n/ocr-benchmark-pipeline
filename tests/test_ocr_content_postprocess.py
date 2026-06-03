from __future__ import annotations

import unittest

from app import ocr_content_postprocess


class OcrContentPostprocessModuleTests(unittest.TestCase):
    def test_apply_section_header_heading_level_strips_existing_heading(self) -> None:
        text = "\n  ## Existing heading"
        normalized = ocr_content_postprocess.apply_section_header_heading_level(text, 3)
        self.assertEqual(normalized, "### Existing heading")

    def test_apply_section_header_heading_level_strips_full_line_emphasis(self) -> None:
        self.assertEqual(
            ocr_content_postprocess.apply_section_header_heading_level("***Header***", 4),
            "#### Header",
        )
        self.assertEqual(
            ocr_content_postprocess.apply_section_header_heading_level("***Header***.", 4),
            "#### Header.",
        )

    def test_apply_section_header_heading_level_keeps_partial_emphasis(self) -> None:
        self.assertEqual(
            ocr_content_postprocess.apply_section_header_heading_level("Header with *term*", 3),
            "### Header with *term*",
        )

    def test_normalize_formula_latex_content_strips_wrappers(self) -> None:
        raw = "```latex\n$$x^2+y^2$$\n```"
        normalized = ocr_content_postprocess.normalize_formula_latex_content(raw)
        self.assertEqual(normalized, "x^2+y^2")

    def test_normalize_ocr_content_maps_quote_glyph_variants(self) -> None:
        raw = "«Китап» “сүз” „исем“ ‘апостроф’ ʼтамгаʼ"
        normalized = ocr_content_postprocess.normalize_ocr_content(raw, output_format="markdown")
        self.assertEqual(normalized, '"Китап" "сүз" "исем" \'апостроф\' \'тамга\'')

    def test_normalize_ocr_content_preserves_markdown_math_primes(self) -> None:
        raw = "Текстта ′ билгесе, формулада $f′(x)$ һәм «сүз»."
        normalized = ocr_content_postprocess.normalize_ocr_content(raw, output_format="markdown")
        self.assertEqual(normalized, "Текстта ' билгесе, формулада $f′(x)$ һәм \"сүз\".")

    def test_normalize_ocr_content_preserves_latex_formula_quotes_and_primes(self) -> None:
        raw = "f′(x)+\\text{“a”}"
        normalized = ocr_content_postprocess.normalize_ocr_content(raw, output_format="latex")
        self.assertEqual(normalized, raw)

    def test_list_item_indent_levels_by_layout_id_uses_leftmost_baseline(self) -> None:
        layouts = [
            {"id": 1, "class_name": "list_item", "bbox": {"x1": 0.20, "y1": 0.1, "x2": 0.8, "y2": 0.2}},
            {"id": 2, "class_name": "list_item", "bbox": {"x1": 0.26, "y1": 0.2, "x2": 0.8, "y2": 0.3}},
            {"id": 3, "class_name": "text", "bbox": {"x1": 0.10, "y1": 0.3, "x2": 0.8, "y2": 0.4}},
        ]
        levels = ocr_content_postprocess.list_item_indent_levels_by_layout_id(layouts)
        self.assertEqual(levels[1], 0)
        self.assertEqual(levels[2], 2)


if __name__ == "__main__":
    unittest.main()
