from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from .db import get_session
from .layouts import get_page
from .lookalikes import detect_suspicious_lookalikes, normalize_text_nfc
from .models import CaptionBinding, OcrOutput, Page, Layout
from .ocr_output_rules import layout_class_requires_ocr, output_matches_layout_class


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _output_row_to_dict(output: OcrOutput, layout: Layout, *, bound_target_ids: list[int] | None = None) -> dict[str, Any]:
    output_format = str(output.output_format)
    normalized_content = normalize_text_nfc(str(output.content))
    lookalike_warnings = (
        detect_suspicious_lookalikes(normalized_content, markdown_code_aware=True)
        if output_format.lower() == "markdown"
        else []
    )
    lookalike_line_indexes = sorted({int(item["line_index"]) for item in lookalike_warnings})
    return {
        "layout_id": int(output.layout_id),
        "page_id": int(output.page_id),
        "class_name": str(output.class_name),
        "output_format": output_format,
        "content": normalized_content,
        "model_name": str(output.model_name),
        "key_alias": output.key_alias,
        "created_at": str(output.created_at),
        "updated_at": str(output.updated_at),
        "lookalike_warning_count": len(lookalike_warnings),
        "lookalike_warning_line_indexes": lookalike_line_indexes,
        "lookalike_warnings": lookalike_warnings,
        "reading_order": int(layout.reading_order),
        "bbox": {
            "x1": float(layout.x1),
            "y1": float(layout.y1),
            "x2": float(layout.x2),
            "y2": float(layout.y2),
        },
        "bound_target_ids": [] if bound_target_ids is None else [int(value) for value in bound_target_ids],
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

        layout_ids = [int(layout.id) for _output, layout in rows]
        bindings_by_caption_id: dict[int, list[int]] = {}
        if layout_ids:
            binding_rows = session.execute(
                select(CaptionBinding.caption_layout_id, CaptionBinding.target_layout_id)
                .join(Layout, Layout.id == CaptionBinding.target_layout_id)
                .where(
                    CaptionBinding.caption_layout_id.in_(layout_ids),
                    Layout.page_id == page_id,
                )
                .order_by(CaptionBinding.caption_layout_id.asc(), CaptionBinding.target_layout_id.asc())
            ).all()
            for caption_layout_id_raw, target_layout_id_raw in binding_rows:
                caption_layout_id = int(caption_layout_id_raw)
                target_layout_id = int(target_layout_id_raw)
                bindings_by_caption_id.setdefault(caption_layout_id, []).append(target_layout_id)

    return [
        _output_row_to_dict(
            output,
            layout,
            bound_target_ids=bindings_by_caption_id.get(int(layout.id), []),
        )
        for output, layout in rows
    ]


def update_ocr_output(layout_id: int, *, content: str) -> dict[str, Any]:
    now = _utc_now()
    normalized_content = normalize_text_nfc(content)
    with get_session() as session:
        row = session.execute(
            select(OcrOutput, Layout)
            .join(Layout, Layout.id == OcrOutput.layout_id)
            .where(OcrOutput.layout_id == layout_id)
        ).first()
        if row is None:
            raise ValueError("OCR output not found.")

        output, layout = row
        output.content = normalized_content
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
    if status not in {"layout_reviewed", "ocr_done", "ocr_reviewed", "ocr_failed"}:
        raise ValueError(
            f"Page status must allow OCR review (expected layout_reviewed/ocr_done/ocr_reviewed/ocr_failed, got {status})."
        )

    with get_session() as session:
        layout_rows = session.execute(
            select(Layout).where(Layout.page_id == page_id)
        ).scalars().all()
        if not layout_rows:
            raise ValueError("No layouts found for this page.")

        outputs = session.execute(
            select(OcrOutput).where(OcrOutput.page_id == page_id)
        ).scalars().all()
        outputs_count = len(outputs)
        if outputs_count == 0:
            raise ValueError("No OCR outputs found for this page.")

        layout_by_id = {int(layout.id): layout for layout in layout_rows}
        required_layout_ids = {
            int(layout.id)
            for layout in layout_rows
            if layout_class_requires_ocr(str(layout.class_name))
        }

        matched_layout_ids: set[int] = set()
        for output in outputs:
            layout_id = int(output.layout_id)
            layout = layout_by_id.get(layout_id)
            if layout is None:
                continue
            if output_matches_layout_class(
                output_class_name=str(output.class_name),
                output_format=str(output.output_format),
                layout_class_name=str(layout.class_name),
            ):
                matched_layout_ids.add(layout_id)
        missing_layout_ids = sorted(required_layout_ids.difference(matched_layout_ids))
        if missing_layout_ids:
            raise ValueError(
                "Missing OCR outputs for one or more layouts; run OCR extraction before marking reviewed."
            )

        page_row = session.get(Page, page_id)
        if page_row is None:
            raise ValueError("Page not found.")
        page_row.status = "ocr_reviewed"
        page_row.updated_at = _utc_now()

    return {"page_id": page_id, "status": "ocr_reviewed", "output_count": outputs_count}
