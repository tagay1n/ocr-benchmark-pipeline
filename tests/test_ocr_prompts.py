from __future__ import annotations

import unittest

from app import ocr_prompts


class OcrPromptsTests(unittest.TestCase):
    def test_default_prompt_template_is_built_from_parts(self) -> None:
        self.assertEqual(
            ocr_prompts.DEFAULT_PROMPT_TEMPLATE,
            "\n".join(ocr_prompts.DEFAULT_PROMPT_PARTS),
        )

    def test_caption_line_for_layout_only_applies_to_caption(self) -> None:
        self.assertEqual(
            ocr_prompts.caption_line_for_layout("caption", ["table [id:1]"]),
            " Caption targets: table [id:1].",
        )
        self.assertEqual(
            ocr_prompts.caption_line_for_layout("text", ["table [id:1]"]),
            "",
        )
        self.assertEqual(ocr_prompts.caption_line_for_layout("caption", []), "")

    def test_format_rule_mapping(self) -> None:
        self.assertEqual(
            ocr_prompts.format_rule_for_output_format("markdown"),
            ocr_prompts.FORMAT_RULE_MARKDOWN,
        )
        self.assertEqual(
            ocr_prompts.format_rule_for_output_format("html"),
            ocr_prompts.FORMAT_RULE_HTML,
        )
        self.assertEqual(
            ocr_prompts.format_rule_for_output_format("latex"),
            ocr_prompts.FORMAT_RULE_LATEX,
        )
        self.assertEqual(ocr_prompts.format_rule_for_output_format("skip"), "")

    def test_class_rule_mapping(self) -> None:
        self.assertEqual(
            ocr_prompts.class_rule_for_layout_class("text"),
            ocr_prompts.CLASS_RULE_TEXT,
        )
        self.assertEqual(
            ocr_prompts.class_rule_for_layout_class("section_header"),
            ocr_prompts.CLASS_RULE_TEXT,
        )
        self.assertEqual(
            ocr_prompts.class_rule_for_layout_class("picture_text"),
            ocr_prompts.CLASS_RULE_TEXT,
        )
        self.assertEqual(
            ocr_prompts.class_rule_for_layout_class("page_header"),
            ocr_prompts.CLASS_RULE_TEXT,
        )
        self.assertEqual(
            ocr_prompts.class_rule_for_layout_class("page_footer"),
            ocr_prompts.CLASS_RULE_TEXT,
        )
        self.assertEqual(
            ocr_prompts.class_rule_for_layout_class("caption"),
            ocr_prompts.CLASS_RULE_CAPTION,
        )
        self.assertEqual(
            ocr_prompts.class_rule_for_layout_class("footnote"),
            ocr_prompts.CLASS_RULE_FOOTNOTE,
        )
        self.assertEqual(
            ocr_prompts.class_rule_for_layout_class("formula"),
            ocr_prompts.CLASS_RULE_FORMULA,
        )
        self.assertEqual(
            ocr_prompts.class_rule_for_layout_class("table"),
            ocr_prompts.CLASS_RULE_TABLE,
        )

    def test_table_class_rule_contains_core_constraints(self) -> None:
        rule = ocr_prompts.CLASS_RULE_TABLE
        self.assertIn("table extraction task", rule)
        self.assertIn("<thead>", rule)
        self.assertIn("rowspan/colspan", rule)
        self.assertIn("line breaks inside a cell using <br>", rule)
        self.assertIn("outside crop boundaries", rule)

    def test_text_and_footnote_rules_cover_sup_sub_and_no_markdown_footnote_syntax(self) -> None:
        self.assertIn("<sup>...</sup>", ocr_prompts.CLASS_RULE_TEXT)
        self.assertIn("<sub>...</sub>", ocr_prompts.CLASS_RULE_TEXT)
        self.assertIn(
            "Do not invent superscript/subscript where it is not clearly visible.",
            ocr_prompts.CLASS_RULE_TEXT,
        )
        self.assertIn("Do not convert output to Markdown footnote syntax", ocr_prompts.CLASS_RULE_FOOTNOTE)

    def test_render_prompt_template_replaces_known_placeholders(self) -> None:
        rendered = ocr_prompts.render_prompt_template(
            "class={class_name}; cap={caption_line}; targets={caption_targets}; class_rule={class_rule}; rule={format_rule}",
            class_name="caption",
            caption_targets=["table [id:1]", "formula [id:2]"],
            class_rule="CLASS-RULE",
            format_rule="RULE",
        )
        self.assertIn("class=caption", rendered)
        self.assertIn("cap= Caption targets: table [id:1], formula [id:2].", rendered)
        self.assertIn("targets=table [id:1], formula [id:2]", rendered)
        self.assertIn("class_rule=CLASS-RULE", rendered)
        self.assertIn("rule=RULE", rendered)


if __name__ == "__main__":
    unittest.main()
