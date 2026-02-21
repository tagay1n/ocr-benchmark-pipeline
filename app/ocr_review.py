from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from .db import get_session
from .layouts import get_page
from .models import OcrOutput, Page, Layout


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _output_row_to_dict(output: OcrOutput, layout: Layout) -> dict[str, Any]:
    return {
        "layout_id": int(output.layout_id),
        "page_id": int(output.page_id),
        "class_name": str(output.class_name),
        "output_format": str(output.output_format),
        "content": str(output.content),
        "model_name": str(output.model_name),
        "key_alias": output.key_alias,
        "created_at": str(output.created_at),
        "updated_at": str(output.updated_at),
        "reading_order": int(layout.reading_order),
        "bbox": {
            "x1": float(layout.x1),
            "y1": float(layout.y1),
            "x2": float(layout.x2),
            "y2": float(layout.y2),
        },
    }


def list_ocr_outputs(page_id: int) -> list[dict[str, Any]]:
    page = get_page(page_id)
    if page is None:
        raise ValueError("Page not found.")
    if bool(page.get("is_missing")):
        raise ValueError("Page is marked as missing and cannot be reviewed.")

    with get_session() as session:
        rows = session.execute(
            select(OcrOutput, Layout)
            .join(Layout, Layout.id == OcrOutput.layout_id)
            .where(OcrOutput.page_id == page_id)
            .order_by(Layout.reading_order.asc(), OcrOutput.layout_id.asc())
        ).all()

    return [_output_row_to_dict(output, layout) for output, layout in rows]


def update_ocr_output(layout_id: int, *, content: str) -> dict[str, Any]:
    now = _utc_now()
    with get_session() as session:
        row = session.execute(
            select(OcrOutput, Layout)
            .join(Layout, Layout.id == OcrOutput.layout_id)
            .where(OcrOutput.layout_id == layout_id)
        ).first()
        if row is None:
            raise ValueError("OCR output not found.")

        output, layout = row
        output.content = content
        output.updated_at = now
        session.flush()
        return _output_row_to_dict(output, layout)


def mark_ocr_reviewed(page_id: int) -> dict[str, Any]:
    page = get_page(page_id)
    if page is None:
        raise ValueError("Page not found.")
    if bool(page.get("is_missing")):
        raise ValueError("Page is marked as missing and cannot be reviewed.")

    status = str(page.get("status") or "")
    if status not in {"ocr_done", "ocr_reviewed"}:
        raise ValueError(f"Page status must be ocr_done for OCR review (got {status}).")

    with get_session() as session:
        outputs_count = int(
            session.query(OcrOutput).filter(OcrOutput.page_id == page_id).count()
        )
        if outputs_count == 0:
            raise ValueError("No OCR outputs found for this page.")

        page_row = session.get(Page, page_id)
        if page_row is None:
            raise ValueError("Page not found.")
        page_row.status = "ocr_reviewed"
        page_row.updated_at = _utc_now()

    return {"page_id": page_id, "status": "ocr_reviewed", "output_count": outputs_count}
