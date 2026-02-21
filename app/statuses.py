from __future__ import annotations

STATUS_NEW = "NEW"
STATUS_LAYOUT_DETECTING = "LAYOUT_DETECTING"
STATUS_LAYOUT_DETECTED = "LAYOUT_DETECTED"
STATUS_LAYOUT_REVIEWED = "LAYOUT_REVIEWED"
STATUS_OCR_EXTRACTING = "OCR_EXTRACTING"
STATUS_OCR_DONE = "OCR_DONE"
STATUS_OCR_REVIEWED = "OCR_REVIEWED"
STATUS_OCR_FAILED = "OCR_FAILED"


def normalize_db_status(value: str | None) -> str:
    return str(value or "").strip().replace("-", "_").replace(" ", "_").upper()


def to_api_status(value: str | None) -> str:
    return normalize_db_status(value).lower()

