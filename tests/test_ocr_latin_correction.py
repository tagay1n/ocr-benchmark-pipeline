from __future__ import annotations

import unittest

from app.lookalikes import correct_ocr_latin_lookalikes
from app.ocr_content_postprocess import normalize_ocr_content


class OcrLatinCorrectionTests(unittest.TestCase):
    def test_corrects_ascii_lookalikes_only_in_mixed_cyrillic_words(self):
        self.assertEqual(
            correct_ocr_latin_lookalikes("Бу сeр, шәhәр һәм Aлма.\nanda NASA A."),
            "Бу сер, шәһәр һәм Алма.\nanda NASA A.",
        )

    def test_preserves_real_cyrillic_errors_and_latin_accents(self):
        text = "Жаек, унай, тәгәлләнмәсен, сéр, Әни һәм anda."
        self.assertEqual(correct_ocr_latin_lookalikes(text), text)

    def test_preserves_markdown_code_links_html_attributes_and_math(self):
        text = ('Бу сeр `сeр` [сeр](https://example.org/сeр) '
                '<span title="сeр">сeр</span> $сeр$ \\(сeр\\)\n'
                '```text\nсeр\n```\n~~~\nсeр\n~~~\nсeр\r\n')
        expected = text.replace('Бу сeр', 'Бу сер').replace('>сeр</span>', '>сер</span>')
        expected = expected[:-len('сeр\r\n')] + 'сер\r\n'
        self.assertEqual(correct_ocr_latin_lookalikes(text), expected)

    def test_manual_review_normalization_keeps_latin_choice(self):
        text = "Бу сeр, шәhәр һәм anda."
        self.assertEqual(normalize_ocr_content(text, output_format="markdown"), text)

    def test_multiline_math_and_html_attributes_remain_literal(self):
        text = '$$\nсeр\n$$\n\\[\nсeр\n\\]\n<span\ntitle="сeр">сeр</span>\n[сeр][id]\n[id]: https://example.org/сeр'
        expected = text.replace('>сeр</span>', '>сер</span>')
        self.assertEqual(correct_ocr_latin_lookalikes(text), expected)

    def test_does_not_truncate_corrections_on_long_output(self):
        self.assertEqual(correct_ocr_latin_lookalikes('сeр ' * 205), 'сер ' * 205)


if __name__ == '__main__':
    unittest.main()
