from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
from typing import Any

from sqlalchemy import select

from .config import settings
from .db import get_session
from .models import CaptionBinding, Layout, OcrOutput, Page
from .statuses import STATUS_OCR_REVIEWED, to_api_status


def _timestamp_folder_name() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d_%H-%M-%S")


def _safe_relative_path(rel_path: str) -> Path:
    normalized = Path(rel_path)
    if normalized.is_absolute() or ".." in normalized.parts:
        raise ValueError("Invalid relative path for export.")
    return normalized


def _copy_source_image(page_rel_path: str, destination_root: Path) -> tuple[Path, int, int]:
    try:
        from PIL import Image
    except ImportError as error:
        raise ValueError("Pillow is required for final export.") from error

    rel_path = _safe_relative_path(page_rel_path)
    src = (settings.source_dir / rel_path).resolve()
    if settings.source_dir.resolve() not in src.parents:
        raise ValueError("Invalid source image path during export.")
    if not src.exists() or not src.is_file():
        raise ValueError(f"Source image missing for export: {page_rel_path}")

    dst = destination_root / "images" / rel_path
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)

    with Image.open(src) as image:
        width, height = image.size
    return dst, int(width), int(height)


def _draw_reconstructed_image(
    *,
    width: int,
    height: int,
    items: list[dict[str, Any]],
    destination_path: Path,
) -> None:
    try:
        from PIL import Image, ImageDraw
    except ImportError as error:
        raise ValueError("Pillow is required for final export.") from error

    canvas = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    for item in items:
        bbox = item["bbox"]
        x1 = max(0, min(width - 1, int(round(float(bbox["x1"]) * width))))
        y1 = max(0, min(height - 1, int(round(float(bbox["y1"]) * height))))
        x2 = max(x1 + 1, min(width, int(round(float(bbox["x2"]) * width))))
        y2 = max(y1 + 1, min(height, int(round(float(bbox["y2"]) * height))))
        draw.rectangle([(x1, y1), (x2, y2)], outline=(140, 150, 145), width=1)

        content = item.get("content")
        if content is None:
            continue

        text = str(content)
        if len(text) > 2000:
            text = text[:2000]
        if not text:
            continue

        # Keep rendering simple and deterministic: preview-only reconstruction for QA.
        draw.multiline_text((x1 + 1, y1 + 1), text, fill=(45, 50, 48), spacing=2)

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination_path)


def _load_export_rows() -> list[dict[str, Any]]:
    reviewed_status_values = (STATUS_OCR_REVIEWED, to_api_status(STATUS_OCR_REVIEWED))
    with get_session() as session:
        rows = session.execute(
            select(
                Page.id,
                Page.rel_path,
                Layout.id,
                Layout.reading_order,
                Layout.class_name,
                Layout.x1,
                Layout.y1,
                Layout.x2,
                Layout.y2,
                OcrOutput.output_format,
                OcrOutput.content,
            )
            .join(Layout, Layout.page_id == Page.id)
            .outerjoin(OcrOutput, OcrOutput.layout_id == Layout.id)
            .where(Page.is_missing.is_(False))
            .where(Page.status.in_(reviewed_status_values))
            .order_by(Page.id.asc(), Layout.reading_order.asc(), Layout.id.asc())
        ).all()

        caption_binding_rows = session.execute(
            select(Layout.page_id, CaptionBinding.caption_layout_id, CaptionBinding.target_layout_id)
            .join(Layout, Layout.id == CaptionBinding.caption_layout_id)
            .join(Page, Page.id == Layout.page_id)
            .where(Page.is_missing.is_(False))
            .where(Page.status.in_(reviewed_status_values))
            .order_by(Layout.page_id.asc(), CaptionBinding.caption_layout_id.asc(), CaptionBinding.target_layout_id.asc())
        ).all()

    caption_targets_by_page_and_layout: dict[tuple[int, int], list[int]] = {}
    for page_id_raw, caption_layout_id_raw, target_layout_id_raw in caption_binding_rows:
        key = (int(page_id_raw), int(caption_layout_id_raw))
        caption_targets_by_page_and_layout.setdefault(key, []).append(int(target_layout_id_raw))

    by_page: dict[int, dict[str, Any]] = {}
    for (
        page_id_raw,
        rel_path_raw,
        layout_id_raw,
        reading_order_raw,
        class_name_raw,
        x1_raw,
        y1_raw,
        x2_raw,
        y2_raw,
        output_format_raw,
        content_raw,
    ) in rows:
        page_id = int(page_id_raw)
        page = by_page.setdefault(
            page_id,
            {
                "page_id": page_id,
                "rel_path": str(rel_path_raw),
                "items": [],
            },
        )
        class_name = str(class_name_raw)
        output_format = None if output_format_raw is None else str(output_format_raw)
        content = None if content_raw is None else str(content_raw)

        item: dict[str, Any] = {
            "order": int(reading_order_raw),
            "layout_id": int(layout_id_raw),
            "bbox": {
                "x1": float(x1_raw),
                "y1": float(y1_raw),
                "x2": float(x2_raw),
                "y2": float(y2_raw),
            },
            "class_name": class_name,
        }

        if class_name != "picture":
            if output_format is not None:
                item["content_format"] = output_format
            if content is not None:
                item["content"] = content

        if class_name == "caption":
            targets = caption_targets_by_page_and_layout.get((page_id, int(layout_id_raw)), [])
            item["caption_targets"] = sorted(set(targets))

        page["items"].append(item)

    return [by_page[key] for key in sorted(by_page.keys())]


def export_final_dataset() -> dict[str, Any]:
    export_rows = _load_export_rows()
    if not export_rows:
        raise ValueError("No OCR reviewed pages available for export.")

    root = settings.result_dir / _timestamp_folder_name()
    images_root = root / "images"
    reconstructed_root = root / "reconstructed"
    images_root.mkdir(parents=True, exist_ok=True)
    reconstructed_root.mkdir(parents=True, exist_ok=True)

    metadata_rows: list[dict[str, Any]] = []
    for row in export_rows:
        rel_path = str(row["rel_path"])
        copied_image_path, width, height = _copy_source_image(rel_path, root)
        rel = _safe_relative_path(rel_path)
        reconstructed_path = reconstructed_root / rel.with_suffix(".png")
        _draw_reconstructed_image(
            width=width,
            height=height,
            items=row["items"],
            destination_path=reconstructed_path,
        )

        metadata_rows.append(
            {
                "page_id": int(row["page_id"]),
                "file_name": str(copied_image_path.relative_to(root).as_posix()),
                "reconstructed_file_name": str(reconstructed_path.relative_to(root).as_posix()),
                "width": width,
                "height": height,
                "items": row["items"],
            }
        )

    metadata_path = root / "metadata.jsonl"
    with metadata_path.open("w", encoding="utf-8") as handle:
        for row in metadata_rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    return {
        "export_dir": str(root),
        "metadata_file": str(metadata_path),
        "page_count": len(metadata_rows),
        "image_count": len(metadata_rows),
        "reconstructed_count": len(metadata_rows),
    }
