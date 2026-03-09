from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
import json
from pathlib import Path
from threading import Lock
from typing import Any

from sqlalchemy import delete, func, select

from .config import settings
from .db import get_session
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

_DOC_LAYOUTNET_MODEL = None
_DOC_LAYOUTNET_MODEL_LOCK = Lock()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _load_doclaynet_model():
    global _DOC_LAYOUTNET_MODEL
    if _DOC_LAYOUTNET_MODEL is not None:
        return _DOC_LAYOUTNET_MODEL

    with _DOC_LAYOUTNET_MODEL_LOCK:
        if _DOC_LAYOUTNET_MODEL is not None:
            return _DOC_LAYOUTNET_MODEL
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
                filename=DOC_LAYOUTNET_CHECKPOINT,
            )
        except Exception as error:
            raise ValueError(f"Failed to download detector checkpoint: {error}") from error

        try:
            _DOC_LAYOUTNET_MODEL = YOLO(checkpoint_path)
        except Exception as error:
            raise ValueError(f"Failed to initialize layout detector: {error}") from error

    return _DOC_LAYOUTNET_MODEL


def _detect_doclaynet_layouts(
    image_path: Path,
    *,
    confidence_threshold: float | None,
    iou_threshold: float | None,
    image_size: int | None,
    max_detections: int | None,
    agnostic_nms: bool | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    model = _load_doclaynet_model()

    conf = DOC_LAYOUTNET_DEFAULT_CONF if confidence_threshold is None else confidence_threshold
    iou = DOC_LAYOUTNET_DEFAULT_IOU if iou_threshold is None else iou_threshold
    imgsz = DOC_LAYOUTNET_DEFAULT_IMGSZ if image_size is None else int(image_size)
    max_det = DOC_LAYOUTNET_DEFAULT_MAX_DET if max_detections is None else int(max_detections)
    agnostic = DOC_LAYOUTNET_DEFAULT_AGNOSTIC_NMS if agnostic_nms is None else bool(agnostic_nms)
    inference_params = {
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

    rows.sort(key=lambda row: (row["y1"], row["x1"]))
    return rows, inference_params


def validate_bbox(x1: float, y1: float, x2: float, y2: float) -> None:
    values = (x1, y1, x2, y2)
    if any(value < 0 or value > 1 for value in values):
        raise ValueError("BBox values must be between 0 and 1.")
    if x2 <= x1 or y2 <= y1:
        raise ValueError("BBox must satisfy x2 > x1 and y2 > y1.")


def _page_to_dict(page_row: Page) -> dict[str, Any]:
    return {
        "id": int(page_row.id),
        "rel_path": page_row.rel_path,
        "status": page_row.status,
        "is_missing": bool(page_row.is_missing),
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


def get_page(page_id: int) -> dict[str, Any] | None:
    with get_session() as session:
        page_row = session.get(Page, page_id)
        if page_row is None:
            return None
        return _page_to_dict(page_row)


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
    replace_existing: bool,
    confidence_threshold: float | None,
    iou_threshold: float | None,
    image_size: int | None = None,
    max_detections: int | None = None,
    agnostic_nms: bool | None = None,
) -> dict[str, Any]:
    now = _utc_now()
    with get_session() as session:
        page_row = session.get(Page, page_id)
        if page_row is None:
            raise ValueError("Page not found.")
        if bool(page_row.is_missing):
            raise ValueError("Page is marked as missing and cannot be detected.")
        rel_path = str(page_row.rel_path)

    image_path = (settings.source_dir / rel_path).resolve()
    source_root = settings.source_dir.resolve()
    if source_root not in image_path.parents:
        raise ValueError("Invalid page image path for detection.")
    if not image_path.exists() or not image_path.is_file():
        raise ValueError("Image file not found on disk.")

    detected_rows, thresholds = _detect_doclaynet_layouts(
        image_path,
        confidence_threshold=confidence_threshold,
        iou_threshold=iou_threshold,
        image_size=image_size,
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
    detector_params = {
        "confidence_threshold": thresholds["confidence_threshold"],
        "iou_threshold": thresholds["iou_threshold"],
        "image_size": thresholds["image_size"],
        "max_detections": thresholds["max_detections"],
        "agnostic_nms": thresholds["agnostic_nms"],
        "device": "cpu",
        "model": DOC_LAYOUTNET_CHECKPOINT,
    }
    detector_source = f"detector:{DOC_LAYOUTNET_REPO_ID}:{json.dumps(detector_params, separators=(',', ':'))}"

    created_count = 0
    with get_session() as session:
        if replace_existing:
            session.execute(delete(Layout).where(Layout.page_id == page_id))

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
        "detector": f"{DOC_LAYOUTNET_REPO_ID}:{DOC_LAYOUTNET_CHECKPOINT}",
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

        if reading_order is None:
            current_max = session.execute(
                select(func.coalesce(func.max(Layout.reading_order), 0)).where(Layout.page_id == page_id)
            ).scalar_one()
            reading_order = int(current_max or 0) + 1

        layout = Layout(
            page_id=page_id,
            class_name=class_name,
            x1=x1,
            y1=y1,
            x2=x2,
            y2=y2,
            reading_order=reading_order,
            confidence=None,
            source="manual",
            created_at=now,
            updated_at=now,
        )
        session.add(layout)
        session.flush()

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
        next_reading_order = int(layout.reading_order) if reading_order is None else reading_order
        next_x1 = float(layout.x1) if x1 is None else x1
        next_y1 = float(layout.y1) if y1 is None else y1
        next_x2 = float(layout.x2) if x2 is None else x2
        next_y2 = float(layout.y2) if y2 is None else y2

        validate_bbox(next_x1, next_y1, next_x2, next_y2)

        layout.class_name = next_class_name
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
