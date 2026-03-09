from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .db import get_session
from .models import LayoutDetectionDefaults

DEFAULT_MODEL_CHECKPOINT = "yolo26m-doclaynet.pt"
DEFAULT_CONFIDENCE_THRESHOLD = 0.25
DEFAULT_IOU_THRESHOLD = 0.45
DEFAULT_IMAGE_SIZE = 1024


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _defaults_to_dict(row: LayoutDetectionDefaults) -> dict[str, Any]:
    return {
        "model_checkpoint": str(row.model_checkpoint),
        "confidence_threshold": float(row.confidence_threshold),
        "iou_threshold": float(row.iou_threshold),
        "image_size": int(row.image_size),
        "updated_at": str(row.updated_at),
        "updated_by": str(row.updated_by),
    }


def _ensure_defaults_row() -> LayoutDetectionDefaults:
    with get_session() as session:
        row = session.get(LayoutDetectionDefaults, 1)
        if row is None:
            row = LayoutDetectionDefaults(
                id=1,
                model_checkpoint=DEFAULT_MODEL_CHECKPOINT,
                confidence_threshold=DEFAULT_CONFIDENCE_THRESHOLD,
                iou_threshold=DEFAULT_IOU_THRESHOLD,
                image_size=DEFAULT_IMAGE_SIZE,
                updated_at=_utc_now(),
                updated_by="system",
            )
            session.add(row)
            session.flush()
        return row


def get_layout_detection_defaults() -> dict[str, Any]:
    row = _ensure_defaults_row()
    return _defaults_to_dict(row)


def update_layout_detection_defaults(
    *,
    model_checkpoint: str,
    confidence_threshold: float,
    iou_threshold: float,
    image_size: int,
    updated_by: str,
) -> dict[str, Any]:
    with get_session() as session:
        row = session.get(LayoutDetectionDefaults, 1)
        if row is None:
            row = LayoutDetectionDefaults(
                id=1,
                model_checkpoint=model_checkpoint,
                confidence_threshold=confidence_threshold,
                iou_threshold=iou_threshold,
                image_size=image_size,
                updated_at=_utc_now(),
                updated_by=updated_by,
            )
            session.add(row)
        else:
            row.model_checkpoint = model_checkpoint
            row.confidence_threshold = confidence_threshold
            row.iou_threshold = iou_threshold
            row.image_size = image_size
            row.updated_at = _utc_now()
            row.updated_by = updated_by
        session.flush()
        return _defaults_to_dict(row)
