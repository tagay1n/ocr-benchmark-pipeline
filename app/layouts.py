from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
import json
from typing import Any

from sqlalchemy import delete, func, select

from .config import settings
from .db import get_session
from .layout_detection import (
    DOC_LAYOUTNET_AVAILABLE_CHECKPOINTS,
    DOC_LAYOUTNET_CHECKPOINT,
    DOC_LAYOUTNET_DEFAULT_AGNOSTIC_NMS,
    DOC_LAYOUTNET_DEFAULT_CONF,
    DOC_LAYOUTNET_DEFAULT_IMGSZ,
    DOC_LAYOUTNET_DEFAULT_IOU,
    DOC_LAYOUTNET_DEFAULT_MAX_DET,
    DOC_LAYOUTNET_REPO_ID,
    _detect_doclaynet_layouts,
    _dedupe_overlapping_layout_rows,
)
from .layout_detection_defaults import get_layout_detection_defaults
from .layout_ordering import (
    LAYOUT_ORDER_MODE_AUTO,
    LAYOUT_ORDER_MODE_MULTI_COLUMN,
    LAYOUT_ORDER_MODE_SINGLE,
    LAYOUT_ORDER_MODE_TWO_PAGE,
    infer_layout_order_mode,
    insertion_reading_order_by_mode,
    normalize_layout_order_mode,
    order_layout_items_by_mode,
)
from .layout_classes import (
    CAPTION_CLASS_NAME,
    CAPTION_TARGET_CLASS_NAMES,
    normalize_class_name,
    normalize_detected_class_name,
    normalize_persisted_class_name,
)
from .layout_orientation import (
    infer_layout_orientation_from_bbox,
    is_effective_vertical,
    normalize_layout_orientation,
)
from .models import CaptionBinding, Layout, OcrOutput, Page
from .ocr_output_rules import (
    can_preserve_output_for_class_transition,
    expected_output_format_for_layout_class,
    layout_class_requires_ocr,
    output_matches_layout_class,
)

QA_REVIEW_PHASES = ("bbox", "class", "order", "ocr")
QA_REVIEW_STATUSES = ("pending", "reviewed")
_QA_REVIEW_PHASE_TO_COLUMN = {
    "bbox": "qa_bbox_status",
    "class": "qa_class_status",
    "order": "qa_order_status",
    "ocr": "qa_ocr_status",
}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_iso_timestamp(value: str | None) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        return datetime.min.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _status_key(value: str | None) -> str:
    return str(value or "").strip().replace("-", "_").replace(" ", "_").lower()


def _normalize_extraction_status(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"ok", "manual", "failed", "skip"}:
        return normalized
    return "ok"


def normalize_qa_review_phase(value: str | None) -> str:
    normalized = _status_key(value)
    if normalized in QA_REVIEW_PHASES:
        return normalized
    raise ValueError("Invalid QA review phase.")


def normalize_qa_review_status(value: str | None) -> str:
    normalized = _status_key(value)
    if normalized == "reviewed":
        return "reviewed"
    return "pending"


def qa_statuses_from_page_row(page_row: Page) -> dict[str, str]:
    return {
        phase: normalize_qa_review_status(getattr(page_row, column_name, None))
        for phase, column_name in _QA_REVIEW_PHASE_TO_COLUMN.items()
    }


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _layout_rows_for_page(session, page_id: int) -> list[Layout]:
    return session.execute(
        select(Layout)
        .where(Layout.page_id == page_id)
        .order_by(Layout.reading_order.asc(), Layout.id.asc())
    ).scalars().all()


def _layout_item_from_row(layout: Layout) -> dict[str, float | int]:
    x1 = _clamp01(float(layout.x1))
    y1 = _clamp01(float(layout.y1))
    x2 = _clamp01(float(layout.x2))
    y2 = _clamp01(float(layout.y2))
    width = max(0.0, x2 - x1)
    height = max(0.0, y2 - y1)
    return {
        "id": int(layout.id),
        "x1": x1,
        "y1": y1,
        "x2": x2,
        "y2": y2,
        "width": width,
        "height": height,
        "center_x": x1 + (width / 2.0),
        "center_y": y1 + (height / 2.0),
        "reading_order": int(layout.reading_order),
    }


def _infer_layout_order_mode(items: list[dict[str, float | int]]) -> str:
    return infer_layout_order_mode(items)


def _order_layout_items_by_mode(items: list[dict[str, float | int]], mode: str) -> list[int]:
    return order_layout_items_by_mode(items, mode)


def _apply_layout_order_by_ids(session, rows: list[Layout], ordered_ids: list[int]) -> bool:
    if not rows:
        return False
    unique_ids: list[int] = []
    seen: set[int] = set()
    for raw_id in ordered_ids:
        row_id = int(raw_id)
        if row_id in seen:
            continue
        seen.add(row_id)
        unique_ids.append(row_id)
    row_ids = [int(row.id) for row in rows]
    if set(unique_ids) != set(row_ids):
        raise ValueError("Ordered layout ids must match page layouts.")

    current_order_by_id = {int(row.id): int(row.reading_order) for row in rows}
    desired_order_by_id = {row_id: index + 1 for index, row_id in enumerate(unique_ids)}
    if all(current_order_by_id[row_id] == desired_order_by_id[row_id] for row_id in row_ids):
        return False

    current_max = max(current_order_by_id.values()) if current_order_by_id else len(rows)
    offset = max(current_max, len(rows)) + 1
    for row in rows:
        row.reading_order = int(desired_order_by_id[int(row.id)]) + offset
    session.flush()
    for row in rows:
        row.reading_order = int(desired_order_by_id[int(row.id)])
    session.flush()
    return True


def _insertion_reading_order_by_mode(
    rows: list[Layout],
    *,
    bbox: dict[str, Any],
    mode: str,
) -> int:
    items = [_layout_item_from_row(row) for row in rows]
    return insertion_reading_order_by_mode(items, bbox=bbox, mode=mode)


def validate_bbox(x1: float, y1: float, x2: float, y2: float) -> None:
    values = (x1, y1, x2, y2)
    if any(value < 0 or value > 1 for value in values):
        raise ValueError("BBox values must be between 0 and 1.")
    if x2 <= x1 or y2 <= y1:
        raise ValueError("BBox must satisfy x2 > x1 and y2 > y1.")


def _page_to_dict(page_row: Page) -> dict[str, Any]:
    layout_order_mode = normalize_layout_order_mode(getattr(page_row, "layout_order_mode", None))
    return {
        "id": int(page_row.id),
        "rel_path": page_row.rel_path,
        "status": page_row.status,
        "is_missing": bool(page_row.is_missing),
        "layout_order_mode": layout_order_mode,
        "qa_statuses": qa_statuses_from_page_row(page_row),
    }


def _layout_to_dict(layout: Layout, *, bound_target_ids: list[int] | None = None) -> dict[str, Any]:
    bbox = {
        "x1": float(layout.x1),
        "y1": float(layout.y1),
        "x2": float(layout.x2),
        "y2": float(layout.y2),
    }
    orientation = normalize_layout_orientation(getattr(layout, "orientation", None))
    effective_orientation = "vertical" if is_effective_vertical(orientation=orientation, bbox=bbox) else "horizontal"
    return {
        "id": int(layout.id),
        "page_id": int(layout.page_id),
        "class_name": layout.class_name,
        "bbox": bbox,
        "reading_order": int(layout.reading_order),
        "orientation": orientation,
        "effective_orientation": effective_orientation,
        "confidence": layout.confidence,
        "source": layout.source,
        "created_at": layout.created_at,
        "updated_at": layout.updated_at,
        "bound_target_ids": [] if bound_target_ids is None else bound_target_ids,
    }


def _normalize_page_reading_orders(session, page_id: int) -> None:
    rows = session.execute(
        select(Layout)
        .where(Layout.page_id == page_id)
        .order_by(Layout.reading_order.asc(), Layout.id.asc())
    ).scalars().all()
    if not rows:
        return
    desired = [index + 1 for index in range(len(rows))]
    current = [int(row.reading_order) for row in rows]
    if current == desired:
        return

    # Use a disjoint temporary range to avoid UNIQUE(page_id, reading_order)
    # collisions while reshuffling sparse/non-contiguous orders.
    current_max = max(current)
    final_max = len(rows)
    offset = max(current_max, final_max) + 1
    for index, row in enumerate(rows, start=1):
        row.reading_order = offset + index
    session.flush()
    for index, row in enumerate(rows, start=1):
        row.reading_order = index
    session.flush()


def _move_layout_to_reading_order(session, layout: Layout, requested_order: int) -> int:
    page_id = int(layout.page_id)
    _normalize_page_reading_orders(session, page_id)

    rows = session.execute(
        select(Layout)
        .where(Layout.page_id == page_id)
        .order_by(Layout.reading_order.asc(), Layout.id.asc())
    ).scalars().all()
    if not rows:
        return 1

    if requested_order < 1:
        raise ValueError("reading_order must be >= 1.")

    total = len(rows)
    target_order = min(int(requested_order), total)
    current_order = int(layout.reading_order)
    if target_order == current_order:
        return current_order

    ordered_ids = [int(row.id) for row in rows]
    layout_id = int(layout.id)
    ordered_ids = [row_id for row_id in ordered_ids if row_id != layout_id]
    ordered_ids.insert(target_order - 1, layout_id)

    final_order_by_id = {row_id: index + 1 for index, row_id in enumerate(ordered_ids)}
    current_max = max(int(row.reading_order) for row in rows)
    final_max = total
    offset = max(current_max, final_max) + 1
    for row in rows:
        row.reading_order = int(final_order_by_id[int(row.id)]) + offset
    session.flush()
    for row in rows:
        row.reading_order = int(final_order_by_id[int(row.id)])
    session.flush()
    return target_order


def get_page(page_id: int) -> dict[str, Any] | None:
    with get_session() as session:
        page_row = session.get(Page, page_id)
        if page_row is None:
            return None
        return _page_to_dict(page_row)


def update_page_qa_status(page_id: int, *, phase: str, status: str) -> dict[str, Any]:
    now = _utc_now()
    normalized_phase = normalize_qa_review_phase(phase)
    normalized_status = _status_key(status)
    if normalized_status not in QA_REVIEW_STATUSES:
        raise ValueError("Invalid QA review status.")
    column_name = _QA_REVIEW_PHASE_TO_COLUMN[normalized_phase]

    with get_session() as session:
        page_row = session.get(Page, page_id)
        if page_row is None:
            raise ValueError("Page not found.")
        setattr(page_row, column_name, normalized_status)
        page_row.updated_at = now
        return {
            "page_id": int(page_row.id),
            "phase": normalized_phase,
            "status": normalized_status,
            "qa_statuses": qa_statuses_from_page_row(page_row),
        }


def _next_page_response_from_row(row: tuple[object, ...] | None) -> dict[str, Any]:
    if row is None:
        return {
            "has_next": False,
            "next_page_id": None,
            "next_page_rel_path": None,
        }
    return {
        "has_next": True,
        "next_page_id": int(row[0]),
        "next_page_rel_path": str(row[1]),
    }


def next_page_for_qa_phase(*, phase: str, current_page_id: int | None = None) -> dict[str, Any]:
    normalized_phase = normalize_qa_review_phase(phase)
    column_name = _QA_REVIEW_PHASE_TO_COLUMN[normalized_phase]
    status_column = getattr(Page, column_name)

    with get_session() as session:
        base_query = (
            select(Page.id, Page.rel_path)
            .where(Page.is_missing.is_(False))
            .where(status_column == "pending")
        )
        if current_page_id is None:
            row = session.execute(base_query.order_by(Page.id.asc()).limit(1)).first()
            return {"phase": normalized_phase, **_next_page_response_from_row(row)}

        row = session.execute(
            base_query.where(Page.id > current_page_id).order_by(Page.id.asc()).limit(1)
        ).first()
    return {"phase": normalized_phase, **_next_page_response_from_row(row)}


def update_page_layout_order_mode(page_id: int, *, mode: str) -> dict[str, Any]:
    now = _utc_now()
    normalized_mode = normalize_layout_order_mode(mode)
    with get_session() as session:
        page_row = session.get(Page, page_id)
        if page_row is None:
            raise ValueError("Page not found.")
        page_row.layout_order_mode = normalized_mode
        page_row.updated_at = now
        return {
            "page_id": int(page_row.id),
            "layout_order_mode": normalized_mode,
        }


def reorder_page_layouts(page_id: int, *, mode: str | None = None) -> dict[str, Any]:
    now = _utc_now()
    with get_session() as session:
        page_row = session.get(Page, page_id)
        if page_row is None:
            raise ValueError("Page not found.")
        if bool(page_row.is_missing):
            raise ValueError("Page is marked as missing and cannot be reordered.")

        normalized_mode = normalize_layout_order_mode(
            mode if mode is not None else getattr(page_row, "layout_order_mode", None)
        )
        page_row.layout_order_mode = normalized_mode
        rows = _layout_rows_for_page(session, page_id)
        if not rows:
            page_row.updated_at = now
            return {
                "page_id": page_id,
                "layout_order_mode": normalized_mode,
                "layout_count": 0,
                "changed": False,
            }

        _normalize_page_reading_orders(session, page_id)
        rows = _layout_rows_for_page(session, page_id)
        items = [_layout_item_from_row(row) for row in rows]
        ordered_ids = _order_layout_items_by_mode(items, normalized_mode)
        changed = _apply_layout_order_by_ids(session, rows, ordered_ids)
        page_row.updated_at = now
        return {
            "page_id": page_id,
            "layout_order_mode": normalized_mode,
            "layout_count": len(rows),
            "changed": bool(changed),
        }


def list_layouts(page_id: int) -> list[dict[str, Any]]:
    with get_session() as session:
        layouts = session.execute(
            select(Layout)
            .where(Layout.page_id == page_id)
            .order_by(Layout.reading_order.asc(), Layout.id.asc())
        ).scalars().all()

        layout_ids = [int(layout.id) for layout in layouts]
        bindings_by_caption_id: dict[int, list[int]] = {}
        if layout_ids:
            binding_rows = session.execute(
                select(CaptionBinding.caption_layout_id, CaptionBinding.target_layout_id, Layout.page_id)
                .join(Layout, Layout.id == CaptionBinding.target_layout_id)
                .where(CaptionBinding.caption_layout_id.in_(layout_ids))
                .where(Layout.page_id == page_id)
                .order_by(CaptionBinding.caption_layout_id.asc(), CaptionBinding.target_layout_id.asc())
            ).all()
            for caption_layout_id, target_layout_id, _target_page_id in binding_rows:
                caption_id = int(caption_layout_id)
                bindings_by_caption_id.setdefault(caption_id, []).append(int(target_layout_id))

    return [
        _layout_to_dict(layout, bound_target_ids=bindings_by_caption_id.get(int(layout.id), []))
        for layout in layouts
    ]


def detect_layouts_for_page(
    page_id: int,
    *,
    model_checkpoint: str | None = None,
    replace_existing: bool,
    confidence_threshold: float | None,
    iou_threshold: float | None,
    image_size: int | None = None,
    max_detections: int | None = None,
    agnostic_nms: bool | None = None,
) -> dict[str, Any]:
    now = _utc_now()
    page_layout_order_mode = LAYOUT_ORDER_MODE_AUTO
    with get_session() as session:
        page_row = session.get(Page, page_id)
        if page_row is None:
            raise ValueError("Page not found.")
        if bool(page_row.is_missing):
            raise ValueError("Page is marked as missing and cannot be detected.")
        rel_path = str(page_row.rel_path)
        page_layout_order_mode = normalize_layout_order_mode(getattr(page_row, "layout_order_mode", None))

    image_path = (settings.source_dir / rel_path).resolve()
    source_root = settings.source_dir.resolve()
    if source_root not in image_path.parents:
        raise ValueError("Invalid page image path for detection.")
    if not image_path.exists() or not image_path.is_file():
        raise ValueError("Image file not found on disk.")

    defaults = get_layout_detection_defaults()
    resolved_model_checkpoint = model_checkpoint or str(defaults["model_checkpoint"])
    resolved_confidence_threshold = (
        float(defaults["confidence_threshold"])
        if confidence_threshold is None
        else confidence_threshold
    )
    resolved_iou_threshold = float(defaults["iou_threshold"]) if iou_threshold is None else iou_threshold
    resolved_image_size = int(defaults["image_size"]) if image_size is None else image_size

    detected_rows, thresholds = _detect_doclaynet_layouts(
        image_path,
        model_checkpoint=resolved_model_checkpoint,
        confidence_threshold=resolved_confidence_threshold,
        iou_threshold=resolved_iou_threshold,
        image_size=resolved_image_size,
        max_detections=max_detections,
        agnostic_nms=agnostic_nms,
    )
    detected_rows = [
        {
            **row,
            "class_name": normalize_detected_class_name(str(row.get("class_name", ""))),
        }
        for row in detected_rows
    ]
    detected_rows = _dedupe_overlapping_layout_rows(detected_rows)
    detected_rows.sort(key=lambda row: (float(row["y1"]), float(row["x1"])))
    if detected_rows:
        detected_items: list[dict[str, float | int]] = []
        for idx, row in enumerate(detected_rows, start=1):
            x1 = float(row["x1"])
            y1 = float(row["y1"])
            x2 = float(row["x2"])
            y2 = float(row["y2"])
            width = max(0.0, x2 - x1)
            height = max(0.0, y2 - y1)
            detected_items.append(
                {
                    "id": idx,
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                    "width": width,
                    "height": height,
                    "center_x": x1 + (width / 2.0),
                    "center_y": y1 + (height / 2.0),
                    "reading_order": idx,
                }
            )
        ordered_detected_ids = _order_layout_items_by_mode(detected_items, page_layout_order_mode)
        ordered_index_by_id = {row_id: index for index, row_id in enumerate(ordered_detected_ids)}
        detected_rows = [
            row
            for _, row in sorted(
                zip([item["id"] for item in detected_items], detected_rows, strict=False),
                key=lambda pair: ordered_index_by_id.get(int(pair[0]), 10**9),
            )
        ]
    detector_params = {
        "confidence_threshold": float(
            thresholds.get("confidence_threshold", resolved_confidence_threshold)
        ),
        "iou_threshold": float(thresholds.get("iou_threshold", resolved_iou_threshold)),
        "image_size": int(thresholds.get("image_size", resolved_image_size)),
        "max_detections": int(
            thresholds.get("max_detections", DOC_LAYOUTNET_DEFAULT_MAX_DET)
        ),
        "agnostic_nms": bool(
            thresholds.get("agnostic_nms", DOC_LAYOUTNET_DEFAULT_AGNOSTIC_NMS)
        ),
        "device": "cpu",
        "model": str(thresholds.get("model_checkpoint", resolved_model_checkpoint)),
    }
    detector_source = f"detector:{DOC_LAYOUTNET_REPO_ID}:{json.dumps(detector_params, separators=(',', ':'))}"

    created_count = 0
    with get_session() as session:
        if replace_existing:
            session.execute(delete(Layout).where(Layout.page_id == page_id))
        else:
            _normalize_page_reading_orders(session, page_id)

        existing_count = int(
            session.execute(
                select(func.coalesce(func.max(Layout.reading_order), 0)).where(Layout.page_id == page_id)
            ).scalar_one()
            or 0
        )

        for idx, row in enumerate(detected_rows, start=1):
            session.add(
                Layout(
                    page_id=page_id,
                    class_name=row["class_name"],
                    x1=row["x1"],
                    y1=row["y1"],
                    x2=row["x2"],
                    y2=row["y2"],
                    reading_order=existing_count + idx,
                    orientation=infer_layout_orientation_from_bbox(
                        bbox={"x1": row["x1"], "y1": row["y1"], "x2": row["x2"], "y2": row["y2"]}
                    ),
                    confidence=row["confidence"],
                    source=detector_source,
                    created_at=now,
                    updated_at=now,
                )
            )
            created_count += 1

        page_row = session.get(Page, page_id)
        if page_row is None:
            raise ValueError("Page not found.")
        page_row.status = "layout_detected"
        page_row.updated_at = now

    class_counts = dict(Counter(row["class_name"] for row in detected_rows))
    return {
        "created": created_count,
        "detector": f"{DOC_LAYOUTNET_REPO_ID}:{detector_params['model']}",
        "thresholds": {
            "confidence_threshold": detector_params["confidence_threshold"],
            "iou_threshold": detector_params["iou_threshold"],
        },
        "inference_params": {
            "confidence_threshold": detector_params["confidence_threshold"],
            "iou_threshold": detector_params["iou_threshold"],
            "image_size": detector_params["image_size"],
            "max_detections": detector_params["max_detections"],
            "agnostic_nms": detector_params["agnostic_nms"],
        },
        "class_counts": class_counts,
        "note": "DocLayNet detection completed.",
    }


def create_layout(
    page_id: int,
    *,
    class_name: str,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    reading_order: int | None,
    orientation: str | None = None,
) -> dict[str, Any]:
    validate_bbox(x1, y1, x2, y2)
    class_name = normalize_persisted_class_name(class_name)
    orientation = (
        infer_layout_orientation_from_bbox(bbox={"x1": x1, "y1": y1, "x2": x2, "y2": y2})
        if orientation is None
        else normalize_layout_orientation(orientation)
    )
    now = _utc_now()

    with get_session() as session:
        page_row = session.get(Page, page_id)
        if page_row is None:
            raise ValueError("Page not found.")
        if bool(page_row.is_missing):
            raise ValueError("Page is marked as missing and cannot be edited.")
        page_order_mode = normalize_layout_order_mode(getattr(page_row, "layout_order_mode", None))

        # Heal legacy sparse orders before appending/positioning a new layout.
        _normalize_page_reading_orders(session, page_id)
        rows = _layout_rows_for_page(session, page_id)

        current_max = session.execute(
            select(func.coalesce(func.max(Layout.reading_order), 0)).where(Layout.page_id == page_id)
        ).scalar_one()
        append_order = int(current_max or 0) + 1
        if reading_order is None:
            resolved_order = _insertion_reading_order_by_mode(
                rows,
                bbox={"x1": x1, "y1": y1, "x2": x2, "y2": y2},
                mode=page_order_mode,
            )
        else:
            resolved_order = int(reading_order)
        if resolved_order < 1:
            raise ValueError("reading_order must be >= 1.")

        layout = Layout(
            page_id=page_id,
            class_name=class_name,
            x1=x1,
            y1=y1,
            x2=x2,
            y2=y2,
            reading_order=append_order,
            orientation=orientation,
            confidence=None,
            source="manual",
            created_at=now,
            updated_at=now,
        )
        session.add(layout)
        session.flush()
        if resolved_order != append_order:
            _move_layout_to_reading_order(session, layout, resolved_order)

        page_row.status = "layout_detected"
        page_row.updated_at = now
        return _layout_to_dict(layout)


def update_layout(
    layout_id: int,
    *,
    class_name: str | None,
    reading_order: int | None,
    x1: float | None,
    y1: float | None,
    x2: float | None,
    y2: float | None,
    orientation: str | None = None,
) -> dict[str, Any]:
    now = _utc_now()
    next_class_name_input = None if class_name is None else normalize_persisted_class_name(class_name)
    next_orientation_input = None if orientation is None else normalize_layout_orientation(orientation)
    with get_session() as session:
        layout = session.get(Layout, layout_id)
        if layout is None:
            raise ValueError("Layout not found.")

        next_class_name = layout.class_name if next_class_name_input is None else next_class_name_input
        next_reading_order = int(layout.reading_order) if reading_order is None else int(reading_order)
        next_orientation = (
            normalize_layout_orientation(getattr(layout, "orientation", None))
            if next_orientation_input is None
            else next_orientation_input
        )
        next_x1 = float(layout.x1) if x1 is None else x1
        next_y1 = float(layout.y1) if y1 is None else y1
        next_x2 = float(layout.x2) if x2 is None else x2
        next_y2 = float(layout.y2) if y2 is None else y2

        validate_bbox(next_x1, next_y1, next_x2, next_y2)
        if next_reading_order < 1:
            raise ValueError("reading_order must be >= 1.")

        previous_class_name = normalize_class_name(str(layout.class_name))
        class_changed = next_class_name != str(layout.class_name)
        orientation_changed = next_orientation != normalize_layout_orientation(getattr(layout, "orientation", None))
        bbox_changed = (
            abs(next_x1 - float(layout.x1)) > 1e-12
            or abs(next_y1 - float(layout.y1)) > 1e-12
            or abs(next_x2 - float(layout.x2)) > 1e-12
            or abs(next_y2 - float(layout.y2)) > 1e-12
        )

        layout.class_name = next_class_name
        if next_reading_order != int(layout.reading_order):
            next_reading_order = _move_layout_to_reading_order(session, layout, next_reading_order)
        layout.reading_order = next_reading_order
        layout.orientation = next_orientation
        layout.x1 = next_x1
        layout.y1 = next_y1
        layout.x2 = next_x2
        layout.y2 = next_y2
        if class_changed or orientation_changed or bbox_changed:
            layout.updated_at = now

        if class_changed and not bbox_changed:
            output = session.get(OcrOutput, int(layout.id))
            if output is not None and can_preserve_output_for_class_transition(
                previous_class_name=previous_class_name,
                next_class_name=next_class_name,
                output_format=str(output.output_format),
            ):
                output.class_name = next_class_name
                output.updated_at = now

        page_row = session.get(Page, int(layout.page_id))
        if page_row is not None:
            page_row.updated_at = now

        return _layout_to_dict(layout)


def delete_layout(layout_id: int) -> None:
    now = _utc_now()
    with get_session() as session:
        layout = session.get(Layout, layout_id)
        if layout is None:
            raise ValueError("Layout not found.")
        page_id = int(layout.page_id)
        session.delete(layout)
        session.flush()
        _normalize_page_reading_orders(session, page_id)
        page_row = session.get(Page, page_id)
        if page_row is not None:
            page_row.updated_at = now


def replace_caption_bindings(page_id: int, bindings_by_caption_id: dict[int, list[int]]) -> dict[str, Any]:
    now = _utc_now()
    with get_session() as session:
        page_row = session.get(Page, page_id)
        if page_row is None:
            raise ValueError("Page not found.")
        if bool(page_row.is_missing):
            raise ValueError("Page is marked as missing and cannot be edited.")

        layouts = session.execute(select(Layout).where(Layout.page_id == page_id)).scalars().all()
        layout_class_by_id = {int(layout.id): normalize_class_name(str(layout.class_name)) for layout in layouts}
        caption_ids = {
            layout_id for layout_id, class_name in layout_class_by_id.items() if class_name == CAPTION_CLASS_NAME
        }
        target_ids = {
            layout_id for layout_id, class_name in layout_class_by_id.items() if class_name in CAPTION_TARGET_CLASS_NAMES
        }

        normalized_bindings: dict[int, list[int]] = {}
        for raw_caption_id, raw_target_ids in bindings_by_caption_id.items():
            caption_id = int(raw_caption_id)
            if caption_id not in caption_ids:
                raise ValueError("Caption bindings can be assigned only for caption layouts on the same page.")

            target_ids_normalized: list[int] = []
            seen_target_ids: set[int] = set()
            for raw_target_id in raw_target_ids:
                target_id = int(raw_target_id)
                if target_id in seen_target_ids:
                    continue
                seen_target_ids.add(target_id)
                if target_id not in target_ids:
                    raise ValueError("Caption targets must be table, picture, or formula layouts on the same page.")
                target_ids_normalized.append(target_id)
            target_ids_normalized.sort()
            normalized_bindings[caption_id] = target_ids_normalized

        unbound_caption_ids = [caption_id for caption_id in sorted(caption_ids) if not normalized_bindings.get(caption_id)]
        if unbound_caption_ids:
            raise ValueError(
                "All caption layouts must be bound to at least one table, picture, or formula before review."
            )

        if caption_ids:
            session.execute(delete(CaptionBinding).where(CaptionBinding.caption_layout_id.in_(caption_ids)))

        binding_count = 0
        for caption_id, target_id_list in normalized_bindings.items():
            for target_id in target_id_list:
                session.add(
                    CaptionBinding(
                        caption_layout_id=caption_id,
                        target_layout_id=target_id,
                        created_at=now,
                        updated_at=now,
                    )
                )
                binding_count += 1

        page_row.updated_at = now

    return {
        "page_id": page_id,
        "binding_count": binding_count,
        "bindings": [
            {"caption_layout_id": caption_id, "target_layout_ids": target_ids}
            for caption_id, target_ids in sorted(normalized_bindings.items())
        ],
    }


def mark_layout_reviewed(page_id: int) -> dict[str, Any]:
    now = _utc_now()
    with get_session() as session:
        page_row = session.get(Page, page_id)
        if page_row is None:
            raise ValueError("Page not found.")
        if bool(page_row.is_missing):
            raise ValueError("Page is marked as missing and cannot be reviewed.")

        layouts = session.execute(select(Layout).where(Layout.page_id == page_id)).scalars().all()
        layout_count = len(layouts)
        if layout_count == 0:
            raise ValueError("No layouts found for this page.")

        class_by_id = {int(layout.id): normalize_class_name(str(layout.class_name)) for layout in layouts}
        caption_ids = {layout_id for layout_id, class_name in class_by_id.items() if class_name == CAPTION_CLASS_NAME}
        target_ids = {
            layout_id
            for layout_id, class_name in class_by_id.items()
            if class_name in CAPTION_TARGET_CLASS_NAMES
        }
        if caption_ids:
            bound_rows = session.execute(
                select(CaptionBinding.caption_layout_id, CaptionBinding.target_layout_id)
                .where(CaptionBinding.caption_layout_id.in_(caption_ids))
            ).all()
            bound_caption_ids: set[int] = set()
            for caption_layout_id, target_layout_id in bound_rows:
                if int(target_layout_id) in target_ids:
                    bound_caption_ids.add(int(caption_layout_id))
            if any(caption_id not in bound_caption_ids for caption_id in sorted(caption_ids)):
                raise ValueError(
                    "All caption layouts must be bound to at least one table, picture, or formula before review."
                )

        outputs = session.execute(select(OcrOutput).where(OcrOutput.page_id == page_id)).scalars().all()
        output_by_layout_id = {int(output.layout_id): output for output in outputs}

        invalidated_layout_ids: set[int] = set()
        extractable_layout_ids: set[int] = set()
        valid_output_layout_ids: set[int] = set()
        for layout in layouts:
            layout_id = int(layout.id)
            layout_class_name = normalize_class_name(str(layout.class_name))
            if layout_class_requires_ocr(layout_class_name):
                extractable_layout_ids.add(layout_id)

            output = output_by_layout_id.get(layout_id)
            if output is None:
                continue

            output_class_name = normalize_class_name(str(output.class_name))
            output_format = str(output.output_format)
            output_extraction_status = _normalize_extraction_status(getattr(output, "extraction_status", None))
            if output_extraction_status == "failed":
                invalidated_layout_ids.add(layout_id)
                continue
            if output_extraction_status not in {"ok", "manual", "skip"}:
                invalidated_layout_ids.add(layout_id)
                continue
            if not output_matches_layout_class(
                output_class_name=output_class_name,
                output_format=output_format,
                layout_class_name=layout_class_name,
            ):
                if can_preserve_output_for_class_transition(
                    previous_class_name=output_class_name,
                    next_class_name=layout_class_name,
                    output_format=output_format,
                ):
                    output.class_name = layout_class_name
                    output.updated_at = now
                    valid_output_layout_ids.add(layout_id)
                    continue
                invalidated_layout_ids.add(layout_id)
                continue

            if _parse_iso_timestamp(str(layout.updated_at)) > _parse_iso_timestamp(str(output.updated_at)):
                invalidated_layout_ids.add(layout_id)
                continue

            valid_output_layout_ids.add(layout_id)

        if invalidated_layout_ids:
            session.execute(
                delete(OcrOutput).where(
                    OcrOutput.page_id == page_id,
                    OcrOutput.layout_id.in_(sorted(invalidated_layout_ids)),
                )
            )
            valid_output_layout_ids.difference_update(invalidated_layout_ids)

        missing_extractable_layout_ids = sorted(extractable_layout_ids.difference(valid_output_layout_ids))
        current_status = _status_key(str(page_row.status))
        if missing_extractable_layout_ids:
            next_status = "layout_reviewed"
        elif current_status == "ocr_reviewed":
            next_status = "ocr_reviewed"
        elif current_status == "ocr_done":
            next_status = "ocr_done"
        else:
            next_status = "ocr_done" if extractable_layout_ids else "layout_reviewed"

        page_row.status = next_status
        page_row.updated_at = now

    return {
        "page_id": page_id,
        "status": next_status,
        "layout_count": layout_count,
        "ocr_invalidated_count": len(invalidated_layout_ids),
        "ocr_invalidated_layout_ids": sorted(invalidated_layout_ids),
        "ocr_missing_layout_count": len(missing_extractable_layout_ids),
    }
