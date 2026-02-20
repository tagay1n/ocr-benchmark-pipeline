from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .db import get_connection
from .layouts import get_page


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def list_ocr_outputs(page_id: int) -> list[dict[str, Any]]:
    page = get_page(page_id)
    if page is None:
        raise ValueError("Page not found.")
    if bool(page.get("is_missing")):
        raise ValueError("Page is marked as missing and cannot be reviewed.")

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                o.layout_id,
                o.page_id,
                o.class_name,
                o.output_format,
                o.content,
                o.model_name,
                o.key_alias,
                o.created_at,
                o.updated_at,
                l.reading_order,
                l.x1,
                l.y1,
                l.x2,
                l.y2
            FROM ocr_outputs o
            JOIN layouts l ON l.id = o.layout_id
            WHERE o.page_id = ?
            ORDER BY l.reading_order ASC, o.layout_id ASC
            """,
            (page_id,),
        ).fetchall()

    return [
        {
            "layout_id": int(row["layout_id"]),
            "page_id": int(row["page_id"]),
            "class_name": str(row["class_name"]),
            "output_format": str(row["output_format"]),
            "content": str(row["content"]),
            "model_name": str(row["model_name"]),
            "key_alias": row["key_alias"],
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "reading_order": int(row["reading_order"]),
            "bbox": {
                "x1": float(row["x1"]),
                "y1": float(row["y1"]),
                "x2": float(row["x2"]),
                "y2": float(row["y2"]),
            },
        }
        for row in rows
    ]


def update_ocr_output(layout_id: int, *, content: str) -> dict[str, Any]:
    now = _utc_now()
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                o.layout_id,
                o.page_id,
                o.class_name,
                o.output_format,
                o.content,
                o.model_name,
                o.key_alias,
                o.created_at,
                o.updated_at,
                l.reading_order,
                l.x1,
                l.y1,
                l.x2,
                l.y2
            FROM ocr_outputs o
            JOIN layouts l ON l.id = o.layout_id
            WHERE o.layout_id = ?
            """,
            (layout_id,),
        ).fetchone()
        if row is None:
            raise ValueError("OCR output not found.")

        conn.execute(
            """
            UPDATE ocr_outputs
            SET content = ?, updated_at = ?
            WHERE layout_id = ?
            """,
            (content, now, layout_id),
        )

        updated = conn.execute(
            """
            SELECT
                o.layout_id,
                o.page_id,
                o.class_name,
                o.output_format,
                o.content,
                o.model_name,
                o.key_alias,
                o.created_at,
                o.updated_at,
                l.reading_order,
                l.x1,
                l.y1,
                l.x2,
                l.y2
            FROM ocr_outputs o
            JOIN layouts l ON l.id = o.layout_id
            WHERE o.layout_id = ?
            """,
            (layout_id,),
        ).fetchone()

    if updated is None:
        raise ValueError("OCR output not found after update.")

    return {
        "layout_id": int(updated["layout_id"]),
        "page_id": int(updated["page_id"]),
        "class_name": str(updated["class_name"]),
        "output_format": str(updated["output_format"]),
        "content": str(updated["content"]),
        "model_name": str(updated["model_name"]),
        "key_alias": updated["key_alias"],
        "created_at": str(updated["created_at"]),
        "updated_at": str(updated["updated_at"]),
        "reading_order": int(updated["reading_order"]),
        "bbox": {
            "x1": float(updated["x1"]),
            "y1": float(updated["y1"]),
            "x2": float(updated["x2"]),
            "y2": float(updated["y2"]),
        },
    }


def mark_ocr_reviewed(page_id: int) -> dict[str, Any]:
    page = get_page(page_id)
    if page is None:
        raise ValueError("Page not found.")
    if bool(page.get("is_missing")):
        raise ValueError("Page is marked as missing and cannot be reviewed.")

    status = str(page.get("status") or "")
    if status not in {"ocr_done", "ocr_reviewed"}:
        raise ValueError(f"Page status must be ocr_done for OCR review (got {status}).")

    with get_connection() as conn:
        outputs_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM ocr_outputs WHERE page_id = ?",
                (page_id,),
            ).fetchone()[0]
        )
        if outputs_count == 0:
            raise ValueError("No OCR outputs found for this page.")

        conn.execute(
            "UPDATE pages SET status = 'ocr_reviewed', updated_at = ? WHERE id = ?",
            (_utc_now(), page_id),
        )

    return {"page_id": page_id, "status": "ocr_reviewed", "output_count": outputs_count}
