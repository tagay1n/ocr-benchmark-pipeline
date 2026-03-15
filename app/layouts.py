from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
import json
import math
from pathlib import Path
from statistics import median
from threading import Lock
from typing import Any

from sqlalchemy import delete, func, select

from .config import settings
from .db import get_session
from .layout_detection_defaults import get_layout_detection_defaults
from .layout_classes import (
    CAPTION_CLASS_NAME,
    CAPTION_TARGET_CLASS_NAMES,
    normalize_class_name,
    normalize_detected_class_name,
    normalize_persisted_class_name,
)
from .models import CaptionBinding, Layout, Page

DOC_LAYOUTNET_REPO_ID = "hantian/yolo-doclaynet"
DOC_LAYOUTNET_CHECKPOINT = "yolo26m-doclaynet.pt"
DOC_LAYOUTNET_DEFAULT_IMGSZ = 1024
DOC_LAYOUTNET_DEFAULT_CONF = 0.25
DOC_LAYOUTNET_DEFAULT_IOU = 0.45
DOC_LAYOUTNET_DEFAULT_MAX_DET = 300
DOC_LAYOUTNET_DEFAULT_AGNOSTIC_NMS = False
DOC_LAYOUTNET_DUPLICATE_OVERLAP_THRESHOLD = 0.85

LAYOUT_ORDER_MODE_AUTO = "auto"
LAYOUT_ORDER_MODE_SINGLE = "single"
LAYOUT_ORDER_MODE_MULTI_COLUMN = "multi-column"
LAYOUT_ORDER_MODE_TWO_PAGE = "two-page"

LAYOUT_ORDER_MODES = (
    LAYOUT_ORDER_MODE_AUTO,
    LAYOUT_ORDER_MODE_SINGLE,
    LAYOUT_ORDER_MODE_MULTI_COLUMN,
    LAYOUT_ORDER_MODE_TWO_PAGE,
)

DOC_LAYOUTNET_AVAILABLE_CHECKPOINTS = (
    "yolov10m-doclaynet.pt",
    "yolov10l-doclaynet.pt",
    "yolov11m-doclaynet.pt",
    "yolov11l-doclaynet.pt",
    "yolov12m-doclaynet.pt",
    "yolov12l-doclaynet.pt",
    "yolo26m-doclaynet.pt",
    "yolo26l-doclaynet.pt",
)

DOC_LAYOUTNET_LEGACY_CHECKPOINT_ALIASES = {
    "yolo11m-doclaynet.pt": "yolov11m-doclaynet.pt",
    "yolo11l-doclaynet.pt": "yolov11l-doclaynet.pt",
    "yolo12m-doclaynet.pt": "yolov12m-doclaynet.pt",
    "yolo12l-doclaynet.pt": "yolov12l-doclaynet.pt",
}

_DOC_LAYOUTNET_MODELS: dict[str, object] = {}
_DOC_LAYOUTNET_MODEL_LOCK = Lock()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def normalize_layout_order_mode(value: str | None) -> str:
    mode = str(value or "").strip().lower().replace("_", "-")
    if mode == "manual":
        return LAYOUT_ORDER_MODE_AUTO
    if mode in {"single-column", "single"}:
        return LAYOUT_ORDER_MODE_SINGLE
    if mode in LAYOUT_ORDER_MODES:
        return mode
    return LAYOUT_ORDER_MODE_AUTO


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


def _layout_item_from_bbox(*, bbox: dict[str, Any], pseudo_id: int) -> dict[str, float | int]:
    x1 = _clamp01(float(bbox["x1"]))
    y1 = _clamp01(float(bbox["y1"]))
    x2 = _clamp01(float(bbox["x2"]))
    y2 = _clamp01(float(bbox["y2"]))
    width = max(0.0, x2 - x1)
    height = max(0.0, y2 - y1)
    return {
        "id": int(pseudo_id),
        "x1": x1,
        "y1": y1,
        "x2": x2,
        "y2": y2,
        "width": width,
        "height": height,
        "center_x": x1 + (width / 2.0),
        "center_y": y1 + (height / 2.0),
        "reading_order": int(pseudo_id),
    }


def _cluster_column_centers(items: list[dict[str, float | int]]) -> list[dict[str, float | int]]:
    if len(items) <= 1:
        return [{"center": float(items[0]["center_x"]), "count": 1}] if items else []
    widths = [float(item["width"]) for item in items if float(item["width"]) > 0]
    median_width = float(median(widths)) if widths else 0.2
    threshold = max(0.04, min(0.2, median_width * 0.45))
    clusters: list[dict[str, float | int]] = []
    for item in sorted(items, key=lambda row: (float(row["center_x"]), float(row["center_y"]), int(row["id"]))):
        center_x = float(item["center_x"])
        nearest_idx = -1
        nearest_distance = 1e9
        for idx, cluster in enumerate(clusters):
            distance = abs(float(cluster["center"]) - center_x)
            if distance < nearest_distance:
                nearest_distance = distance
                nearest_idx = idx
        if nearest_idx >= 0 and nearest_distance <= threshold:
            cluster = clusters[nearest_idx]
            count = int(cluster["count"])
            next_count = count + 1
            cluster["center"] = ((float(cluster["center"]) * count) + center_x) / next_count
            cluster["count"] = next_count
        else:
            clusters.append({"center": center_x, "count": 1})
    clusters.sort(key=lambda cluster: float(cluster["center"]))
    return clusters


def _estimate_two_page_gutter(items: list[dict[str, float | int]]) -> float | None:
    if len(items) < 4:
        return None
    centers = [float(item["center_x"]) for item in items]
    left = [value for value in centers if value < 0.5]
    right = [value for value in centers if value >= 0.5]
    if len(left) < 2 or len(right) < 2:
        return None
    left_median = float(median(left))
    right_median = float(median(right))
    if right_median - left_median < 0.28:
        return None
    middle_count = sum(1 for value in centers if 0.45 <= value <= 0.55)
    if middle_count > max(1, int(math.floor(len(items) * 0.2))):
        return None
    return max(0.35, min(0.65, (left_median + right_median) / 2.0))


def _looks_like_multi_column(items: list[dict[str, float | int]]) -> bool:
    if len(items) < 4:
        return False
    clusters = _cluster_column_centers(items)
    if len(clusters) < 2:
        return False
    counts = sorted(int(cluster["count"]) for cluster in clusters)
    if not counts:
        return False
    # Consider two-plus columns when at least two boxes are in non-primary columns.
    return sum(counts[:-1]) >= 2


def _looks_like_multi_column_slice(items: list[dict[str, float | int]]) -> bool:
    if len(items) < 2:
        return False
    clusters = _cluster_column_centers(items)
    if len(clusters) < 2:
        return False
    centers = sorted(float(cluster["center"]) for cluster in clusters)
    if len(centers) >= 2 and (centers[-1] - centers[0]) < 0.18:
        return False
    counts = sorted(int(cluster["count"]) for cluster in clusters)
    if not counts:
        return False
    # For a thin horizontal slice, a single box in the secondary column is enough
    # to classify the slice as multi-column.
    return sum(counts[:-1]) >= 1


def _order_items_single(items: list[dict[str, float | int]]) -> list[int]:
    return [
        int(item["id"])
        for item in sorted(
            items,
            key=lambda row: (
                float(row["center_y"]),
                float(row["center_x"]),
                int(row["id"]),
            ),
        )
    ]


def _order_items_multi_column(items: list[dict[str, float | int]]) -> list[int]:
    if len(items) <= 1:
        return [int(items[0]["id"])] if items else []
    widths = [float(item["width"]) for item in items if float(item["width"]) > 0]
    typical_width = float(median(widths)) if widths else 0.35
    spanning_threshold = max(0.58, min(0.92, typical_width * 1.45))
    spanning_items = [item for item in items if float(item["width"]) >= spanning_threshold]
    regular_items = [item for item in items if float(item["width"]) < spanning_threshold]
    if not regular_items:
        return _order_items_single(items)

    columns = _cluster_column_centers(regular_items)
    if len(columns) < 2:
        return _order_items_single(items)

    def column_index(center_x: float) -> int:
        nearest = 0
        nearest_distance = 1e9
        for idx, cluster in enumerate(columns):
            distance = abs(float(cluster["center"]) - center_x)
            if distance < nearest_distance:
                nearest_distance = distance
                nearest = idx
        return nearest

    regular_sorted = sorted(
        regular_items,
        key=lambda row: (
            column_index(float(row["center_x"])),
            float(row["center_y"]),
            float(row["center_x"]),
            int(row["id"]),
        ),
    )
    if not spanning_items:
        return [int(item["id"]) for item in regular_sorted]

    regular_centers_y = [float(item["center_y"]) for item in regular_items]
    regular_heights = [float(item["height"]) for item in regular_items if float(item["height"]) > 0]
    min_regular_y = min(regular_centers_y) if regular_centers_y else 0.0
    height_hint = float(median(regular_heights)) if regular_heights else 0.04
    top_prefix_tolerance = max(0.01, min(0.06, height_hint * 0.5))

    top_spanning: list[dict[str, float | int]] = []
    trailing_spanning: list[dict[str, float | int]] = []
    for item in spanning_items:
        if float(item["center_y"]) <= min_regular_y + top_prefix_tolerance:
            top_spanning.append(item)
        else:
            trailing_spanning.append(item)

    top_spanning.sort(
        key=lambda row: (
            float(row["center_y"]),
            float(row["center_x"]),
            int(row["id"]),
        )
    )
    trailing_spanning.sort(
        key=lambda row: (
            float(row["center_y"]),
            float(row["center_x"]),
            int(row["id"]),
        )
    )
    return [int(item["id"]) for item in top_spanning + regular_sorted + trailing_spanning]


def _order_items_two_page(items: list[dict[str, float | int]]) -> list[int]:
    if len(items) <= 1:
        return [int(items[0]["id"])] if items else []
    gutter = _estimate_two_page_gutter(items)
    if gutter is None:
        return _order_items_multi_column(items)

    crossing_items = [
        item for item in items if float(item["x1"]) < gutter < float(item["x2"])
    ]
    left_items = [
        item
        for item in items
        if item not in crossing_items and float(item["center_x"]) <= gutter
    ]
    right_items = [
        item
        for item in items
        if item not in crossing_items and float(item["center_x"]) > gutter
    ]

    ordered_ids: list[int] = []
    ordered_ids.extend(
        int(item["id"])
        for item in sorted(
            crossing_items,
            key=lambda row: (
                float(row["center_y"]),
                float(row["center_x"]),
                int(row["id"]),
            ),
        )
    )
    ordered_ids.extend(_order_items_multi_column(left_items))
    ordered_ids.extend(_order_items_multi_column(right_items))
    return ordered_ids


def _order_items_auto_adaptive(items: list[dict[str, float | int]]) -> list[int]:
    if len(items) <= 1:
        return [int(items[0]["id"])] if items else []

    # If the page looks like a two-page spread, keep spread-first ordering.
    if _estimate_two_page_gutter(items) is not None:
        return _order_items_two_page(items)

    # If the page does not look multi-column overall, keep single-column ordering.
    if not _looks_like_multi_column(items):
        return _order_items_single(items)

    widths = [float(item["width"]) for item in items if float(item["width"]) > 0]
    typical_width = float(median(widths)) if widths else 0.35
    spanning_threshold = max(0.58, min(0.92, typical_width * 1.45))
    regular_items = [item for item in items if float(item["width"]) < spanning_threshold]
    regular_heights = [float(item["height"]) for item in regular_items if float(item["height"]) > 0]
    height_hint = float(median(regular_heights)) if regular_heights else 0.06

    def mode_for_y(mid_y: float) -> str:
        active_regular = [
            item
            for item in regular_items
            if float(item["y1"]) <= mid_y < float(item["y2"])
        ]
        if len(active_regular) < 2:
            return LAYOUT_ORDER_MODE_SINGLE
        return (
            LAYOUT_ORDER_MODE_MULTI_COLUMN
            if _looks_like_multi_column_slice(active_regular)
            else LAYOUT_ORDER_MODE_SINGLE
        )

    boundaries: list[float] = [0.0, 1.0]
    boundaries.extend(float(item["y1"]) for item in items)
    boundaries.extend(float(item["y2"]) for item in items)
    boundaries = sorted(set(max(0.0, min(1.0, value)) for value in boundaries))

    raw_bands: list[dict[str, float | str]] = []
    min_band_height = 1e-5
    for index in range(len(boundaries) - 1):
        start = float(boundaries[index])
        end = float(boundaries[index + 1])
        if end - start <= min_band_height:
            continue
        mid = (start + end) / 2.0
        raw_bands.append(
            {
                "start": start,
                "end": end,
                "mode": mode_for_y(mid),
            }
        )

    bridge_gap_threshold = max(0.01, min(0.06, height_hint * 0.55))
    index = 0
    while index < len(raw_bands):
        if str(raw_bands[index]["mode"]) != LAYOUT_ORDER_MODE_SINGLE:
            index += 1
            continue
        run_start = index
        run_end = index
        run_height = 0.0
        while run_end < len(raw_bands) and str(raw_bands[run_end]["mode"]) == LAYOUT_ORDER_MODE_SINGLE:
            run_height += float(raw_bands[run_end]["end"]) - float(raw_bands[run_end]["start"])
            run_end += 1
        left_mode = str(raw_bands[run_start - 1]["mode"]) if run_start > 0 else ""
        right_mode = str(raw_bands[run_end]["mode"]) if run_end < len(raw_bands) else ""
        if (
            left_mode == LAYOUT_ORDER_MODE_MULTI_COLUMN
            and right_mode == LAYOUT_ORDER_MODE_MULTI_COLUMN
            and run_height <= bridge_gap_threshold
        ):
            for bridge_index in range(run_start, run_end):
                raw_bands[bridge_index]["mode"] = LAYOUT_ORDER_MODE_MULTI_COLUMN
        index = run_end

    if not raw_bands:
        return _order_items_single(items)

    merged_bands: list[dict[str, float | str]] = []
    for band in raw_bands:
        if not merged_bands:
            merged_bands.append(dict(band))
            continue
        previous = merged_bands[-1]
        same_mode = str(previous["mode"]) == str(band["mode"])
        touching = abs(float(previous["end"]) - float(band["start"])) <= min_band_height
        if same_mode and touching:
            previous["end"] = float(band["end"])
        else:
            merged_bands.append(dict(band))

    bands_with_items: list[dict[str, Any]] = []
    for band in merged_bands:
        start = float(band["start"])
        end = float(band["end"])
        assigned = [
            item
            for item in items
            if (
                (start <= float(item["center_y"]) < end)
                or (abs(float(item["center_y"]) - end) <= min_band_height and abs(end - 1.0) <= min_band_height)
            )
        ]
        if not assigned:
            continue
        mode = str(band["mode"])
        if mode == LAYOUT_ORDER_MODE_MULTI_COLUMN and not _looks_like_multi_column(assigned):
            mode = LAYOUT_ORDER_MODE_SINGLE
        bands_with_items.append(
            {
                "start": start,
                "end": end,
                "mode": mode,
                "items": assigned,
            }
        )

    if not bands_with_items:
        return _order_items_single(items)

    ordered_ids: list[int] = []
    seen_ids: set[int] = set()
    for band in sorted(bands_with_items, key=lambda row: float(row["start"])):
        band_items = [item for item in band["items"] if int(item["id"]) not in seen_ids]
        if not band_items:
            continue
        mode = str(band["mode"])
        band_order = (
            _order_items_multi_column(band_items)
            if mode == LAYOUT_ORDER_MODE_MULTI_COLUMN
            else _order_items_single(band_items)
        )
        for row_id in band_order:
            if int(row_id) in seen_ids:
                continue
            seen_ids.add(int(row_id))
            ordered_ids.append(int(row_id))

    if len(seen_ids) != len(items):
        missing_items = [item for item in _order_items_single(items) if int(item) not in seen_ids]
        ordered_ids.extend(int(row_id) for row_id in missing_items)

    return ordered_ids


def _infer_layout_order_mode(items: list[dict[str, float | int]]) -> str:
    if _estimate_two_page_gutter(items) is not None:
        return LAYOUT_ORDER_MODE_TWO_PAGE
    if _looks_like_multi_column(items):
        return LAYOUT_ORDER_MODE_MULTI_COLUMN
    return LAYOUT_ORDER_MODE_SINGLE


def _order_layout_items_by_mode(items: list[dict[str, float | int]], mode: str) -> list[int]:
    normalized_mode = normalize_layout_order_mode(mode)
    if len(items) <= 1:
        return [int(items[0]["id"])] if items else []
    if normalized_mode == LAYOUT_ORDER_MODE_AUTO:
        return _order_items_auto_adaptive(items)
    if normalized_mode == LAYOUT_ORDER_MODE_SINGLE:
        return _order_items_single(items)
    if normalized_mode == LAYOUT_ORDER_MODE_MULTI_COLUMN:
        return _order_items_multi_column(items)
    if normalized_mode == LAYOUT_ORDER_MODE_TWO_PAGE:
        return _order_items_two_page(items)
    return _order_items_single(items)


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
    if not rows:
        return 1
    normalized_mode = normalize_layout_order_mode(mode)

    items = [_layout_item_from_row(row) for row in rows]
    pseudo_id = -1
    items.append(_layout_item_from_bbox(bbox=bbox, pseudo_id=pseudo_id))
    ordered_ids = _order_layout_items_by_mode(items, normalized_mode)
    if pseudo_id not in ordered_ids:
        return len(rows) + 1
    return ordered_ids.index(pseudo_id) + 1


def _bbox_intersection_over_min_area(box_a: dict[str, Any], box_b: dict[str, Any]) -> float:
    ax1 = float(box_a["x1"])
    ay1 = float(box_a["y1"])
    ax2 = float(box_a["x2"])
    ay2 = float(box_a["y2"])
    bx1 = float(box_b["x1"])
    by1 = float(box_b["y1"])
    bx2 = float(box_b["x2"])
    by2 = float(box_b["y2"])

    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    if inter_x2 <= inter_x1 or inter_y2 <= inter_y1:
        return 0.0

    inter_area = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
    area_a = max(0.0, (ax2 - ax1) * (ay2 - ay1))
    area_b = max(0.0, (bx2 - bx1) * (by2 - by1))
    min_area = min(area_a, area_b)
    if min_area <= 0.0:
        return 0.0
    return inter_area / min_area


def _dedupe_overlapping_layout_rows(
    rows: list[dict[str, Any]],
    *,
    overlap_threshold: float = DOC_LAYOUTNET_DUPLICATE_OVERLAP_THRESHOLD,
) -> list[dict[str, Any]]:
    if len(rows) <= 1:
        return rows

    def row_confidence(row: dict[str, Any]) -> float:
        try:
            return float(row.get("confidence", 0.0))
        except (TypeError, ValueError):
            return 0.0

    def row_area(row: dict[str, Any]) -> float:
        try:
            width = max(0.0, float(row["x2"]) - float(row["x1"]))
            height = max(0.0, float(row["y2"]) - float(row["y1"]))
        except (TypeError, ValueError, KeyError):
            return 0.0
        return width * height

    candidates = sorted(
        rows,
        key=lambda row: (
            -row_confidence(row),
            -row_area(row),
        ),
    )

    deduped: list[dict[str, Any]] = []
    for candidate in candidates:
        is_duplicate = False
        for kept in deduped:
            overlap = _bbox_intersection_over_min_area(candidate, kept)
            if overlap >= overlap_threshold:
                is_duplicate = True
                break
        if not is_duplicate:
            deduped.append(candidate)
    return deduped


def _load_doclaynet_model(checkpoint: str):
    cached = _DOC_LAYOUTNET_MODELS.get(checkpoint)
    if cached is not None:
        return cached

    with _DOC_LAYOUTNET_MODEL_LOCK:
        cached_locked = _DOC_LAYOUTNET_MODELS.get(checkpoint)
        if cached_locked is not None:
            return cached_locked
        try:
            from huggingface_hub import hf_hub_download
            from ultralytics import YOLO
        except ImportError as error:
            raise ValueError(
                "Layout detector dependencies are missing. Install `ultralytics` and `huggingface_hub`."
            ) from error

        try:
            checkpoint_path = hf_hub_download(
                repo_id=DOC_LAYOUTNET_REPO_ID,
                filename=checkpoint,
            )
        except Exception as error:
            raise ValueError(f"Failed to download detector checkpoint: {error}") from error

        try:
            _DOC_LAYOUTNET_MODELS[checkpoint] = YOLO(checkpoint_path)
        except Exception as error:
            raise ValueError(f"Failed to initialize layout detector: {error}") from error

    return _DOC_LAYOUTNET_MODELS[checkpoint]


def _detect_doclaynet_layouts(
    image_path: Path,
    *,
    model_checkpoint: str | None,
    confidence_threshold: float | None,
    iou_threshold: float | None,
    image_size: int | None,
    max_detections: int | None,
    agnostic_nms: bool | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    checkpoint = str(model_checkpoint or DOC_LAYOUTNET_CHECKPOINT).strip()
    if not checkpoint:
        checkpoint = DOC_LAYOUTNET_CHECKPOINT
    checkpoint = DOC_LAYOUTNET_LEGACY_CHECKPOINT_ALIASES.get(checkpoint, checkpoint)
    model = _load_doclaynet_model(checkpoint)

    conf = DOC_LAYOUTNET_DEFAULT_CONF if confidence_threshold is None else confidence_threshold
    iou = DOC_LAYOUTNET_DEFAULT_IOU if iou_threshold is None else iou_threshold
    imgsz = DOC_LAYOUTNET_DEFAULT_IMGSZ if image_size is None else int(image_size)
    max_det = DOC_LAYOUTNET_DEFAULT_MAX_DET if max_detections is None else int(max_detections)
    agnostic = DOC_LAYOUTNET_DEFAULT_AGNOSTIC_NMS if agnostic_nms is None else bool(agnostic_nms)
    inference_params = {
        "model_checkpoint": checkpoint,
        "confidence_threshold": conf,
        "iou_threshold": iou,
        "image_size": imgsz,
        "max_detections": max_det,
        "agnostic_nms": agnostic,
    }

    try:
        prediction = model.predict(
            str(image_path),
            verbose=False,
            imgsz=imgsz,
            device="cpu",
            conf=conf,
            iou=iou,
            max_det=max_det,
            agnostic_nms=agnostic,
        )
    except Exception as error:
        raise ValueError(f"Layout detection failed: {error}") from error

    if not prediction:
        return [], inference_params

    result = prediction[0].cpu()
    height, width = result.orig_shape
    if width <= 0 or height <= 0:
        raise ValueError("Invalid image size detected for layout inference.")

    rows: list[dict[str, Any]] = []
    boxes = result.boxes
    if boxes is None or len(boxes) == 0:
        return rows, inference_params

    names = result.names
    for xyxy, confidence, cls_idx in zip(boxes.xyxy, boxes.conf, boxes.cls):
        x1_abs, y1_abs, x2_abs, y2_abs = [float(v) for v in xyxy.tolist()]
        x1 = _clamp01(x1_abs / width)
        y1 = _clamp01(y1_abs / height)
        x2 = _clamp01(x2_abs / width)
        y2 = _clamp01(y2_abs / height)
        if x2 <= x1 or y2 <= y1:
            continue

        class_id = int(cls_idx.item())
        if isinstance(names, dict):
            raw_name = str(names.get(class_id, f"class_{class_id}"))
        else:
            raw_name = str(names[class_id]) if class_id < len(names) else f"class_{class_id}"

        rows.append(
            {
                "class_name": normalize_detected_class_name(raw_name),
                "confidence": float(confidence.item()),
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
            }
        )

    deduped_rows = _dedupe_overlapping_layout_rows(rows)
    deduped_rows.sort(key=lambda row: (row["y1"], row["x1"]))
    return deduped_rows, inference_params


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
    }


def _layout_to_dict(layout: Layout, *, bound_target_ids: list[int] | None = None) -> dict[str, Any]:
    return {
        "id": int(layout.id),
        "page_id": int(layout.page_id),
        "class_name": layout.class_name,
        "bbox": {
            "x1": float(layout.x1),
            "y1": float(layout.y1),
            "x2": float(layout.x2),
            "y2": float(layout.y2),
        },
        "reading_order": int(layout.reading_order),
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
) -> dict[str, Any]:
    validate_bbox(x1, y1, x2, y2)
    class_name = normalize_persisted_class_name(class_name)
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
) -> dict[str, Any]:
    now = _utc_now()
    next_class_name_input = None if class_name is None else normalize_persisted_class_name(class_name)
    with get_session() as session:
        layout = session.get(Layout, layout_id)
        if layout is None:
            raise ValueError("Layout not found.")

        next_class_name = layout.class_name if next_class_name_input is None else next_class_name_input
        next_reading_order = int(layout.reading_order) if reading_order is None else int(reading_order)
        next_x1 = float(layout.x1) if x1 is None else x1
        next_y1 = float(layout.y1) if y1 is None else y1
        next_x2 = float(layout.x2) if x2 is None else x2
        next_y2 = float(layout.y2) if y2 is None else y2

        validate_bbox(next_x1, next_y1, next_x2, next_y2)
        if next_reading_order < 1:
            raise ValueError("reading_order must be >= 1.")

        layout.class_name = next_class_name
        if next_reading_order != int(layout.reading_order):
            next_reading_order = _move_layout_to_reading_order(session, layout, next_reading_order)
        layout.reading_order = next_reading_order
        layout.x1 = next_x1
        layout.y1 = next_y1
        layout.x2 = next_x2
        layout.y2 = next_y2
        layout.updated_at = now

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

        page_row.status = "layout_reviewed"
        page_row.updated_at = now

    return {"page_id": page_id, "status": "layout_reviewed", "layout_count": layout_count}
