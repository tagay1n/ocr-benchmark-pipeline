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
        self.assertEqual(ocr_prompts.class_rule_for_layout_class("table"), "")

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
