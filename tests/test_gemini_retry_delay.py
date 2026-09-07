import unittest
from datetime import UTC, datetime
from app.ocr_gemini_client import gemini_retry_delay_seconds


class RetryDelayTests(unittest.TestCase):
    def test_body_and_header_delays(self):
        self.assertEqual(gemini_retry_delay_seconds('HTTP 429 {"retryDelay":"12.5s"}'), 12.5)
        self.assertEqual(gemini_retry_delay_seconds('HTTP 429 {"retryDelay":"12s"}', "60"), 60)
        self.assertEqual(gemini_retry_delay_seconds("HTTP 429", "Mon, 07 Sep 2026 10:01:00 GMT", now=datetime(2026, 9, 7, 10, tzinfo=UTC)), 60)
        self.assertIsNone(gemini_retry_delay_seconds('HTTP 429 {"retryDelay":"invalid"}', "NaN"))
