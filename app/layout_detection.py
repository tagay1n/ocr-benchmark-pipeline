from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Any

from .layout_classes import normalize_detected_class_name

DOC_LAYOUTNET_REPO_ID = "hantian/yolo-doclaynet"
DOC_LAYOUTNET_CHECKPOINT = "yolo26m-doclaynet.pt"
DOC_LAYOUTNET_DEFAULT_IMGSZ = 1024
DOC_LAYOUTNET_DEFAULT_CONF = 0.25
DOC_LAYOUTNET_DEFAULT_IOU = 0.45
DOC_LAYOUTNET_DEFAULT_MAX_DET = 300
DOC_LAYOUTNET_DEFAULT_AGNOSTIC_NMS = False
DOC_LAYOUTNET_DUPLICATE_OVERLAP_THRESHOLD = 0.85

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


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


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
