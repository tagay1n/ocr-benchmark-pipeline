from __future__ import annotations

from datetime import UTC, datetime
import json
import sqlite3
from typing import Any

from .db import get_connection

PLACEHOLDER_DETECTOR = "placeholder-doclaynet"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


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
        }
        for row in rows
    ]


def detect_layouts_for_page(
    page_id: int,
    *,
    replace_existing: bool,
    confidence_threshold: float | None,
    iou_threshold: float | None,
) -> dict[str, Any]:
    now = _utc_now()
    detector_params = {
        "confidence_threshold": confidence_threshold,
        "iou_threshold": iou_threshold,
    }

    with get_connection() as conn:
        page_row = _get_page_row(conn, page_id)
        if page_row is None:
            raise ValueError("Page not found.")
        if int(page_row["is_missing"]) == 1:
            raise ValueError("Page is marked as missing and cannot be detected.")

        if replace_existing:
            conn.execute("DELETE FROM layouts WHERE page_id = ?", (page_id,))

        existing_count = conn.execute(
            "SELECT COUNT(*) FROM layouts WHERE page_id = ?",
            (page_id,),
        ).fetchone()[0]
        next_order = int(existing_count) + 1

        conn.execute(
            """
            INSERT INTO layouts(
                page_id, class_name, x1, y1, x2, y2, reading_order, confidence, source, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                page_id,
                "text_block",
                0.0,
                0.0,
                1.0,
                1.0,
                next_order,
                None,
                f"detector:{PLACEHOLDER_DETECTOR}:{json.dumps(detector_params, separators=(',', ':'))}",
                now,
                now,
            ),
        )
        conn.execute(
            "UPDATE pages SET status = 'layout_detected', updated_at = ? WHERE id = ?",
            (now, page_id),
        )

    return {
        "created": 1,
        "detector": PLACEHOLDER_DETECTOR,
        "note": "Placeholder detector created one full-page text block. Replace with yolo-doclaynet integration next.",
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

        next_class_name = row["class_name"] if class_name is None else class_name
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

        conn.execute(
            "UPDATE pages SET status = 'layout_reviewed', updated_at = ? WHERE id = ?",
            (now, page_id),
        )

    return {"page_id": page_id, "status": "layout_reviewed", "layout_count": layout_count}
