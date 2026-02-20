from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
from threading import Lock
from typing import Any

from .config import settings
from .db import get_connection

DOC_LAYOUTNET_REPO_ID = "hantian/yolo-doclaynet"
DOC_LAYOUTNET_CHECKPOINT = "yolov10b-doclaynet.pt"
DOC_LAYOUTNET_DEFAULT_IMGSZ = 1024
DOC_LAYOUTNET_DEFAULT_CONF = 0.25
DOC_LAYOUTNET_DEFAULT_IOU = 0.45
DOC_LAYOUTNET_DEFAULT_MAX_DET = 300
DOC_LAYOUTNET_DEFAULT_AGNOSTIC_NMS = False
CAPTION_CLASS_NAME = "caption"
CAPTION_TARGET_CLASS_NAMES = {"table", "picture", "formula"}

_DOC_LAYOUTNET_MODEL = None
_DOC_LAYOUTNET_MODEL_LOCK = Lock()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _normalize_class_name(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_").replace("/", "_")
    return "_".join(normalized.split())


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
                "class_name": _normalize_class_name(raw_name),
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


def _get_page_row(conn: sqlite3.Connection, page_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, rel_path, status, is_missing FROM pages WHERE id = ?",
        (page_id,),
    ).fetchone()


def get_page(page_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = _get_page_row(conn, page_id)
        if row is None:
            return None
        return {
            "id": int(row["id"]),
            "rel_path": row["rel_path"],
            "status": row["status"],
            "is_missing": bool(row["is_missing"]),
        }


def list_layouts(page_id: int) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, page_id, class_name, x1, y1, x2, y2, reading_order, confidence, source, created_at, updated_at
            FROM layouts
            WHERE page_id = ?
            ORDER BY reading_order ASC, id ASC
            """,
            (page_id,),
        ).fetchall()
        binding_rows = conn.execute(
            """
            SELECT cb.caption_layout_id, cb.target_layout_id
            FROM caption_bindings cb
            JOIN layouts caption_layout ON caption_layout.id = cb.caption_layout_id
            JOIN layouts target_layout ON target_layout.id = cb.target_layout_id
            WHERE caption_layout.page_id = ?
              AND target_layout.page_id = ?
            ORDER BY cb.caption_layout_id ASC, cb.target_layout_id ASC
            """,
            (page_id, page_id),
        ).fetchall()

    bindings_by_caption_id: dict[int, list[int]] = {}
    for row in binding_rows:
        caption_layout_id = int(row["caption_layout_id"])
        target_layout_id = int(row["target_layout_id"])
        bindings_by_caption_id.setdefault(caption_layout_id, []).append(target_layout_id)

    return [
        {
            "id": int(row["id"]),
            "page_id": int(row["page_id"]),
            "class_name": row["class_name"],
            "bbox": {
                "x1": float(row["x1"]),
                "y1": float(row["y1"]),
                "x2": float(row["x2"]),
                "y2": float(row["y2"]),
            },
            "reading_order": int(row["reading_order"]),
            "confidence": row["confidence"],
            "source": row["source"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "bound_target_ids": bindings_by_caption_id.get(int(row["id"]), []),
        }
        for row in rows
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
    with get_connection() as conn:
        page_row = _get_page_row(conn, page_id)
        if page_row is None:
            raise ValueError("Page not found.")
        if int(page_row["is_missing"]) == 1:
            raise ValueError("Page is marked as missing and cannot be detected.")

    image_path = (settings.source_dir / str(page_row["rel_path"])).resolve()
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
    with get_connection() as conn:
        if replace_existing:
            conn.execute("DELETE FROM layouts WHERE page_id = ?", (page_id,))

        existing_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM layouts WHERE page_id = ?",
                (page_id,),
            ).fetchone()[0]
        )
        for idx, row in enumerate(detected_rows, start=1):
            conn.execute(
                """
                INSERT INTO layouts(
                    page_id, class_name, x1, y1, x2, y2, reading_order, confidence, source, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    page_id,
                    row["class_name"],
                    row["x1"],
                    row["y1"],
                    row["x2"],
                    row["y2"],
                    existing_count + idx,
                    row["confidence"],
                    detector_source,
                    now,
                    now,
                ),
            )
            created_count += 1
        conn.execute(
            "UPDATE pages SET status = 'layout_detected', updated_at = ? WHERE id = ?",
            (now, page_id),
        )

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
    class_name = _normalize_class_name(class_name)
    now = _utc_now()

    with get_connection() as conn:
        page_row = _get_page_row(conn, page_id)
        if page_row is None:
            raise ValueError("Page not found.")
        if int(page_row["is_missing"]) == 1:
            raise ValueError("Page is marked as missing and cannot be edited.")

        if reading_order is None:
            current_max = conn.execute(
                "SELECT COALESCE(MAX(reading_order), 0) FROM layouts WHERE page_id = ?",
                (page_id,),
            ).fetchone()[0]
            reading_order = int(current_max) + 1

        cursor = conn.execute(
            """
            INSERT INTO layouts(
                page_id, class_name, x1, y1, x2, y2, reading_order, confidence, source, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'manual', ?, ?)
            """,
            (
                page_id,
                class_name,
                x1,
                y1,
                x2,
                y2,
                reading_order,
                None,
                now,
                now,
            ),
        )
        layout_id = int(cursor.lastrowid)

        conn.execute(
            "UPDATE pages SET status = 'layout_detected', updated_at = ? WHERE id = ?",
            (now, page_id),
        )

        row = conn.execute(
            """
            SELECT id, page_id, class_name, x1, y1, x2, y2, reading_order, confidence, source, created_at, updated_at
            FROM layouts
            WHERE id = ?
            """,
            (layout_id,),
        ).fetchone()

    if row is None:
        raise ValueError("Layout was not created.")

    return {
        "id": int(row["id"]),
        "page_id": int(row["page_id"]),
        "class_name": row["class_name"],
        "bbox": {
            "x1": float(row["x1"]),
            "y1": float(row["y1"]),
            "x2": float(row["x2"]),
            "y2": float(row["y2"]),
        },
        "reading_order": int(row["reading_order"]),
        "confidence": row["confidence"],
        "source": row["source"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


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
    next_class_name_input = None if class_name is None else _normalize_class_name(class_name)
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, page_id, class_name, x1, y1, x2, y2, reading_order, confidence, source, created_at, updated_at
            FROM layouts
            WHERE id = ?
            """,
            (layout_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Layout not found.")

        next_class_name = row["class_name"] if next_class_name_input is None else next_class_name_input
        next_reading_order = int(row["reading_order"]) if reading_order is None else reading_order
        next_x1 = float(row["x1"]) if x1 is None else x1
        next_y1 = float(row["y1"]) if y1 is None else y1
        next_x2 = float(row["x2"]) if x2 is None else x2
        next_y2 = float(row["y2"]) if y2 is None else y2

        validate_bbox(next_x1, next_y1, next_x2, next_y2)

        conn.execute(
            """
            UPDATE layouts
            SET class_name = ?, reading_order = ?, x1 = ?, y1 = ?, x2 = ?, y2 = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                next_class_name,
                next_reading_order,
                next_x1,
                next_y1,
                next_x2,
                next_y2,
                now,
                layout_id,
            ),
        )

        conn.execute(
            "UPDATE pages SET updated_at = ? WHERE id = ?",
            (now, int(row["page_id"])),
        )

        updated = conn.execute(
            """
            SELECT id, page_id, class_name, x1, y1, x2, y2, reading_order, confidence, source, created_at, updated_at
            FROM layouts
            WHERE id = ?
            """,
            (layout_id,),
        ).fetchone()

    if updated is None:
        raise ValueError("Layout not found after update.")

    return {
        "id": int(updated["id"]),
        "page_id": int(updated["page_id"]),
        "class_name": updated["class_name"],
        "bbox": {
            "x1": float(updated["x1"]),
            "y1": float(updated["y1"]),
            "x2": float(updated["x2"]),
            "y2": float(updated["y2"]),
        },
        "reading_order": int(updated["reading_order"]),
        "confidence": updated["confidence"],
        "source": updated["source"],
        "created_at": updated["created_at"],
        "updated_at": updated["updated_at"],
    }


def delete_layout(layout_id: int) -> None:
    now = _utc_now()
    with get_connection() as conn:
        row = conn.execute("SELECT page_id FROM layouts WHERE id = ?", (layout_id,)).fetchone()
        if row is None:
            raise ValueError("Layout not found.")
        conn.execute("DELETE FROM layouts WHERE id = ?", (layout_id,))
        conn.execute(
            "UPDATE pages SET updated_at = ? WHERE id = ?",
            (now, int(row["page_id"])),
        )


def replace_caption_bindings(page_id: int, bindings_by_caption_id: dict[int, list[int]]) -> dict[str, Any]:
    now = _utc_now()
    with get_connection() as conn:
        page_row = _get_page_row(conn, page_id)
        if page_row is None:
            raise ValueError("Page not found.")
        if int(page_row["is_missing"]) == 1:
            raise ValueError("Page is marked as missing and cannot be edited.")

        layout_rows = conn.execute(
            """
            SELECT id, class_name
            FROM layouts
            WHERE page_id = ?
            """,
            (page_id,),
        ).fetchall()

        layout_class_by_id = {int(row["id"]): _normalize_class_name(str(row["class_name"])) for row in layout_rows}
        caption_ids = {
            layout_id
            for layout_id, class_name in layout_class_by_id.items()
            if class_name == CAPTION_CLASS_NAME
        }
        target_ids = {
            layout_id
            for layout_id, class_name in layout_class_by_id.items()
            if class_name in CAPTION_TARGET_CLASS_NAMES
        }

        normalized_bindings: dict[int, list[int]] = {}
        for raw_caption_id, raw_target_ids in bindings_by_caption_id.items():
            caption_id = int(raw_caption_id)
            if caption_id not in caption_ids:
                raise ValueError(
                    "Caption bindings can be assigned only for caption layouts on the same page."
                )

            target_ids_normalized: list[int] = []
            seen_target_ids: set[int] = set()
            for raw_target_id in raw_target_ids:
                target_id = int(raw_target_id)
                if target_id in seen_target_ids:
                    continue
                seen_target_ids.add(target_id)
                if target_id not in target_ids:
                    raise ValueError(
                        "Caption targets must be table, picture, or formula layouts on the same page."
                    )
                target_ids_normalized.append(target_id)
            target_ids_normalized.sort()
            normalized_bindings[caption_id] = target_ids_normalized

        unbound_caption_ids = [caption_id for caption_id in sorted(caption_ids) if not normalized_bindings.get(caption_id)]
        if unbound_caption_ids:
            raise ValueError(
                "All caption layouts must be bound to at least one table, picture, or formula before review."
            )

        conn.execute(
            """
            DELETE FROM caption_bindings
            WHERE caption_layout_id IN (
                SELECT id
                FROM layouts
                WHERE page_id = ?
            )
            """,
            (page_id,),
        )

        binding_count = 0
        for caption_id, target_id_list in normalized_bindings.items():
            for target_id in target_id_list:
                conn.execute(
                    """
                    INSERT INTO caption_bindings(caption_layout_id, target_layout_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (caption_id, target_id, now, now),
                )
                binding_count += 1

        conn.execute(
            "UPDATE pages SET updated_at = ? WHERE id = ?",
            (now, page_id),
        )

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
    with get_connection() as conn:
        page_row = _get_page_row(conn, page_id)
        if page_row is None:
            raise ValueError("Page not found.")
        if int(page_row["is_missing"]) == 1:
            raise ValueError("Page is marked as missing and cannot be reviewed.")

        layout_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM layouts WHERE page_id = ?",
                (page_id,),
            ).fetchone()[0]
        )
        if layout_count == 0:
            raise ValueError("No layouts found for this page.")

        caption_needing_bindings = conn.execute(
            f"""
            SELECT caption_layout.id
            FROM layouts caption_layout
            WHERE caption_layout.page_id = ?
              AND caption_layout.class_name = ?
              AND NOT EXISTS (
                SELECT 1
                FROM caption_bindings cb
                JOIN layouts target_layout ON target_layout.id = cb.target_layout_id
                WHERE cb.caption_layout_id = caption_layout.id
                  AND target_layout.page_id = caption_layout.page_id
                  AND target_layout.class_name IN ({",".join("?" for _ in CAPTION_TARGET_CLASS_NAMES)})
              )
            LIMIT 1
            """,
            (page_id, CAPTION_CLASS_NAME, *sorted(CAPTION_TARGET_CLASS_NAMES)),
        ).fetchone()
        if caption_needing_bindings is not None:
            raise ValueError(
                "All caption layouts must be bound to at least one table, picture, or formula before review."
            )

        conn.execute(
            "UPDATE pages SET status = 'layout_reviewed', updated_at = ? WHERE id = ?",
            (now, page_id),
        )

    return {"page_id": page_id, "status": "layout_reviewed", "layout_count": layout_count}
