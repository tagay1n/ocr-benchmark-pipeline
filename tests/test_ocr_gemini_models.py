from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from app import ocr_gemini_client


class GeminiModelRequestTests(unittest.TestCase):
    def test_gemini_four_omits_unsupported_sampling_but_older_models_keep_temperature(self) -> None:
        for model in ("gemini-4-hydrogen", "gemini-4-carbon", "gemini-3.6-flash"):
            with self.subTest(model=model):
                response = MagicMock()
                response.read.return_value = json.dumps({
                    "candidates": [{"content": {"parts": [{"text": '{"content":"Text"}'}]}}]
                }).encode()
                with patch.object(ocr_gemini_client.urllib_request, "urlopen") as opener:
                    opener.return_value.__enter__.return_value = response
                    result = ocr_gemini_client.gemini_generate_content(
                        "test-key", "Transcribe", b"image", model_name=model, temperature=0.2,
                    )
                self.assertEqual(result, "Text")
                request = opener.call_args.args[0]
                self.assertIn(f"/{model}:generateContent", request.full_url)
                generation = json.loads(request.data)["generationConfig"]
                self.assertEqual(generation["responseMimeType"], "application/json")
                self.assertEqual(generation["responseSchema"], ocr_gemini_client.OCR_RESPONSE_SCHEMA)
                if model.startswith("gemini-4-"):
                    self.assertNotIn("temperature", generation)
                else:
                    self.assertEqual(generation["temperature"], 0.2)
