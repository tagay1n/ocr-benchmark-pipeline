from __future__ import annotations

import unittest
from unittest.mock import patch

from app.api import event_lifecycle_utils


class ApiEventLifecycleUtilsTests(unittest.TestCase):
    def test_emit_lifecycle_started_passes_event_payload(self) -> None:
        with patch.object(event_lifecycle_utils, "emit_event") as emit_mock:
            event_lifecycle_utils.emit_lifecycle_started(
                stage="layout_detect",
                event_type="manual_started",
                page_id=7,
                message="started",
                data={"a": 1},
            )
        emit_mock.assert_called_once_with(
            stage="layout_detect",
            event_type="manual_started",
            page_id=7,
            message="started",
            data={"a": 1},
        )

    def test_emit_lifecycle_failed_formats_error_message(self) -> None:
        with patch.object(event_lifecycle_utils, "emit_event") as emit_mock:
            event_lifecycle_utils.emit_lifecycle_failed(
                stage="ocr_extract",
                event_type="manual_failed",
                page_id=9,
                message_prefix="Manual OCR failed",
                error=ValueError("quota"),
                data={"trigger": "manual"},
            )
        emit_mock.assert_called_once_with(
            stage="ocr_extract",
            event_type="manual_failed",
            page_id=9,
            message="Manual OCR failed: quota",
            data={"trigger": "manual"},
        )

    def test_emit_lifecycle_completed_passes_completion_payload(self) -> None:
        with patch.object(event_lifecycle_utils, "emit_event") as emit_mock:
            event_lifecycle_utils.emit_lifecycle_completed(
                stage="finalization",
                event_type="completed",
                message="done",
                data={"count": 3},
            )
        emit_mock.assert_called_once_with(
            stage="finalization",
            event_type="completed",
            page_id=None,
            message="done",
            data={"count": 3},
        )


if __name__ == "__main__":
    unittest.main()
