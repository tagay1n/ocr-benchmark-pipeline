from __future__ import annotations

import json
from pathlib import Path
import unittest

from app import ocr_prompts
from app.layout_classes import KNOWN_LAYOUT_CLASSES


class OcrPromptsTests(unittest.TestCase):
    def test_default_prompt_template_is_built_from_parts(self) -> None:
        self.assertEqual(
            ocr_prompts.DEFAULT_PROMPT_TEMPLATE,
            "\n".join(ocr_prompts.DEFAULT_PROMPT_PARTS),
        )

    def test_default_prompt_template_uses_explicit_priority_sections(self) -> None:
        template = ocr_prompts.DEFAULT_PROMPT_TEMPLATE
        hard_idx = template.find("HARD REQUIREMENTS:")
        fidelity_idx = template.find("SOURCE FIDELITY:")
        class_idx = template.find("CLASS-SPECIFIC REQUIREMENTS:")
        format_idx = template.find("OUTPUT FORMAT REQUIREMENTS:")
        unsure_idx = template.find("IF UNSURE:")
        self.assertGreaterEqual(hard_idx, 0)
        self.assertGreaterEqual(fidelity_idx, 0)
        self.assertGreaterEqual(class_idx, 0)
        self.assertGreaterEqual(format_idx, 0)
        self.assertGreaterEqual(unsure_idx, 0)
        self.assertLess(hard_idx, fidelity_idx)
        self.assertLess(fidelity_idx, class_idx)
        self.assertLess(class_idx, format_idx)
        self.assertLess(format_idx, unsure_idx)
        self.assertIn(
            "preserve visible content semantics first, then source fidelity, then formatting",
            template,
        )
        self.assertNotIn("Preserve line breaks exactly as shown in the crop.", ocr_prompts.PROMPT_BLOCK_SOURCE_FIDELITY)

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
        self.assertIn("Preserve line breaks exactly as shown in the crop.", ocr_prompts.FORMAT_RULE_MARKDOWN)
        self.assertIn("using <br> only when clearly visible", ocr_prompts.FORMAT_RULE_HTML)
        self.assertIn("visible formula layout", ocr_prompts.FORMAT_RULE_LATEX)

    def test_resolve_prompt_spec_matrix(self) -> None:
        expected_formats = {
            "text": "markdown",
            "section_header": "markdown",
            "list_item": "markdown",
            "picture_text": "markdown",
            "page_header": "markdown",
            "page_footer": "markdown",
            "footnote": "markdown",
            "caption": "markdown",
            "table": "html",
            "formula": "latex",
            "picture": "skip",
            "unknown_custom": "markdown",
        }
        for class_name, output_format in expected_formats.items():
            spec = ocr_prompts.resolve_prompt_spec(class_name)
            self.assertEqual(spec.class_name, class_name if class_name != "unknown_custom" else "unknown_custom")
            self.assertEqual(spec.output_format, output_format)
            self.assertEqual(spec.format_rule, ocr_prompts.format_rule_for_output_format(output_format))

    def test_class_rule_mapping(self) -> None:
        self.assertEqual(
            ocr_prompts.class_rule_for_layout_class("text"),
            ocr_prompts.CLASS_RULE_TEXT,
        )
        self.assertEqual(
            ocr_prompts.class_rule_for_layout_class("section_header"),
            ocr_prompts.CLASS_RULES_BY_LAYOUT_CLASS["section_header"],
        )
        self.assertEqual(
            ocr_prompts.class_rule_for_layout_class("list_item"),
            ocr_prompts.CLASS_RULE_LIST_ITEM,
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
        self.assertIn("in nuce (яралгы хәлендә)", ocr_prompts.CLASS_RULE_TEXT)
        self.assertIn("EXAMPLE INPUT START", ocr_prompts.CLASS_RULE_TEXT)
        self.assertIn("EXAMPLE INPUT END", ocr_prompts.CLASS_RULE_TEXT)
        self.assertIn("EXAMPLE OUTPUT START", ocr_prompts.CLASS_RULE_TEXT)
        self.assertIn("EXAMPLE OUTPUT END", ocr_prompts.CLASS_RULE_TEXT)
        self.assertIn("Visual style in crop:", ocr_prompts.CLASS_RULE_TEXT)
        self.assertIn("apply Markdown markers per line", ocr_prompts.CLASS_RULE_TEXT)
        self.assertIn("Do not keep one emphasis marker pair open across a newline", ocr_prompts.CLASS_RULE_TEXT)
        self.assertIn('{"content":"Без съезддагы фикер алышуларның һәм тавыш бирүләрнең', ocr_prompts.CLASS_RULE_TEXT)
        self.assertIn("**съезддан соң булган хәл-**\\n**ләрнең бөтенесен**", ocr_prompts.CLASS_RULE_TEXT)
        self.assertIn("*in nuce*", ocr_prompts.CLASS_RULE_TEXT)
        self.assertIn("Do not convert output to Markdown footnote syntax", ocr_prompts.CLASS_RULE_FOOTNOTE)

    def test_list_item_rule_constrains_single_item_and_marker_behavior(self) -> None:
        rule = ocr_prompts.CLASS_RULE_LIST_ITEM
        self.assertIn("exactly one list item", rule)
        self.assertIn("Preserve the visible list marker exactly", rule)
        self.assertIn("do not invent marker symbols or numbering", rule)
        self.assertIn("downstream normalization may apply marker formatting", rule)

    def test_render_prompt_template_replaces_known_placeholders(self) -> None:
        rendered = ocr_prompts.render_prompt_template(
            "class_rule={class_rule}; rule={format_rule}",
            class_rule="CLASS-RULE",
            format_rule="RULE",
        )
        self.assertIn("class_rule=CLASS-RULE", rendered)
        self.assertIn("rule=RULE", rendered)

    def test_render_prompt_template_allows_braces_inside_replacement_values(self) -> None:
        rendered = ocr_prompts.render_prompt_template(
            "class_rule={class_rule}; rule={format_rule}",
            class_rule=r"Use LaTeX like \\frac{a}{b}",
            format_rule="RULE",
        )
        self.assertIn(r"\\frac{a}{b}", rendered)

    def test_render_prompt_template_raises_for_unknown_placeholders(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "unresolved placeholders"):
            ocr_prompts.render_prompt_template(
                "unknown={unknown_placeholder}\nclass_rule={class_rule}\nrule={format_rule}",
                class_rule="CLASS-RULE",
                format_rule="RULE",
            )

    def test_render_prompt_for_layout_class(self) -> None:
        rendered_text = ocr_prompts.render_prompt_for_layout_class("text")
        self.assertEqual(rendered_text.output_format, "markdown")
        self.assertIn("HARD REQUIREMENTS:", rendered_text.prompt)
        self.assertIn("OUTPUT FORMAT REQUIREMENTS:", rendered_text.prompt)

        rendered_picture = ocr_prompts.render_prompt_for_layout_class("picture")
        self.assertEqual(rendered_picture.output_format, "skip")
        self.assertEqual(rendered_picture.prompt, "")


class OcrPromptSnapshotsTests(unittest.TestCase):
    def test_prompt_snapshots_match_expected_reference(self) -> None:
        snapshot_path = Path("tests/fixtures/ocr_prompt_snapshots.json")
        expected = json.loads(snapshot_path.read_text(encoding="utf-8"))
        actual: dict[str, dict[str, str]] = {}
        for class_name in KNOWN_LAYOUT_CLASSES:
            rendered = ocr_prompts.render_prompt_for_layout_class(class_name)
            actual[class_name] = {
                "output_format": rendered.output_format,
                "prompt": rendered.prompt,
            }
        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
