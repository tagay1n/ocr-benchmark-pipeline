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

_CLASS_COLORS: dict[str, tuple[int, int, int]] = {
    "section_header": (53, 95, 168),
    "text": (79, 93, 105),
    "list_item": (47, 111, 95),
    "table": (111, 125, 47),
    "picture": (138, 104, 49),
    "picture_text": (154, 111, 86),
    "caption": (73, 111, 152),
    "footnote": (122, 96, 48),
    "formula": (123, 90, 149),
    "page_header": (63, 110, 105),
    "page_footer": (139, 89, 73),
}
_FALLBACK_COLORS: tuple[tuple[int, int, int], ...] = (
    (78, 111, 143),
    (124, 95, 144),
    (63, 123, 105),
    (141, 106, 59),
    (130, 96, 91),
    (83, 121, 135),
    (110, 107, 63),
)


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


def _normalize_class_name(value: str) -> str:
    return "_".join(str(value or "").strip().lower().replace("-", " ").replace("/", " ").split())


def _color_for_class(class_name: str) -> tuple[int, int, int]:
    normalized = _normalize_class_name(class_name)
    if normalized in _CLASS_COLORS:
        return _CLASS_COLORS[normalized]
    if not normalized:
        return _FALLBACK_COLORS[0]
    rolling = 0
    for char in normalized:
        rolling = ((rolling << 5) - rolling) + ord(char)
    return _FALLBACK_COLORS[abs(rolling) % len(_FALLBACK_COLORS)]


def _bbox_pixels(bbox: dict[str, Any], *, width: int, height: int) -> tuple[int, int, int, int]:
    x1 = max(0, min(width - 1, int(round(float(bbox["x1"]) * width))))
    y1 = max(0, min(height - 1, int(round(float(bbox["y1"]) * height))))
    x2 = max(x1 + 1, min(width, int(round(float(bbox["x2"]) * width))))
    y2 = max(y1 + 1, min(height, int(round(float(bbox["y2"]) * height))))
    return x1, y1, x2, y2


def _load_font(size: int) -> Any:
    try:
        from PIL import ImageFont
    except ImportError as error:
        raise ValueError("Pillow is required for final export.") from error

    requested_size = max(6, int(size))
    for family in ("DejaVuSans.ttf", "Arial.ttf", "LiberationSans-Regular.ttf"):
        try:
            return ImageFont.truetype(family, requested_size)
        except OSError:
            continue
    return ImageFont.load_default()


def _text_size(draw: Any, text: str, font: Any, *, spacing: int = 0) -> tuple[int, int]:
    if "\n" in text:
        left, top, right, bottom = draw.multiline_textbbox((0, 0), text, font=font, spacing=spacing)
    else:
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    return int(max(0, right - left)), int(max(0, bottom - top))


def _split_chunk_to_width(draw: Any, chunk: str, font: Any, max_width: int) -> list[str]:
    if not chunk:
        return [""]
    width, _ = _text_size(draw, chunk, font)
    if width <= max_width:
        return [chunk]
    lines: list[str] = []
    current = ""
    for char in chunk:
        candidate = char if not current else f"{current}{char}"
        candidate_width, _ = _text_size(draw, candidate, font)
        if candidate_width <= max_width or not current:
            current = candidate
            continue
        lines.append(current)
        current = char
    if current:
        lines.append(current)
    return lines or [chunk]


def _wrap_text_to_width(draw: Any, text: str, font: Any, max_width: int) -> list[str]:
    raw_lines = str(text or "").splitlines() or [""]
    wrapped: list[str] = []
    for raw in raw_lines:
        if not raw:
            wrapped.append("")
            continue
        words = raw.split(" ")
        current = ""
        for word in words:
            candidate = word if not current else f"{current} {word}"
            width, _ = _text_size(draw, candidate, font)
            if width <= max_width:
                current = candidate
                continue
            if current:
                wrapped.append(current)
            for split_chunk in _split_chunk_to_width(draw, word, font, max_width):
                wrapped.append(split_chunk)
            current = ""
        if current:
            wrapped.append(current)
    return wrapped or [""]


def _line_height_ratio_for_output_format(output_format: str | None) -> float:
    normalized = str(output_format or "").strip().lower()
    if normalized == "latex":
        return 1.02
    if normalized == "html":
        return 1.08
    return 1.1


def _fit_wrapped_lines(
    draw: Any,
    text: str,
    *,
    output_format: str | None,
    max_width: int,
    max_height: int,
) -> tuple[Any, list[str], int]:
    min_font_size = 6
    max_font_size = max(min_font_size, min(72, max_width, max_height))
    ratio = _line_height_ratio_for_output_format(output_format)
    best_font = _load_font(min_font_size)
    best_lines = _wrap_text_to_width(draw, text, best_font, max_width)
    best_line_height = max(1, int(round(min_font_size * ratio)))

    low = min_font_size
    high = max_font_size
    while low <= high:
        mid = (low + high) // 2
        font = _load_font(mid)
        lines = _wrap_text_to_width(draw, text, font, max_width)
        line_height = max(1, int(round(mid * ratio)))
        total_height = line_height * max(1, len(lines))
        fits_height = total_height <= max_height
        fits_width = True
        for line in lines:
            line_width, _ = _text_size(draw, line, font)
            if line_width > max_width:
                fits_width = False
                break
        if fits_height and fits_width:
            best_font = font
            best_lines = lines
            best_line_height = line_height
            low = mid + 1
        else:
            high = mid - 1
    return best_font, best_lines, best_line_height


def _draw_reconstructed_canvas(
    *,
    width: int,
    height: int,
    items: list[dict[str, Any]],
) -> Any:
    try:
        from PIL import Image, ImageDraw
    except ImportError as error:
        raise ValueError("Pillow is required for final export.") from error

    canvas = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    for item in items:
        bbox = item.get("bbox") or {}
        x1, y1, x2, y2 = _bbox_pixels(bbox, width=width, height=height)
        class_name = str(item.get("class_name") or "")
        color = _color_for_class(class_name)
        draw.rectangle([(x1, y1), (x2, y2)], outline=color, width=1)

        coords_label = ",".join(
            [
                f"x1={json.dumps(float(bbox.get('x1', 0.0)), ensure_ascii=False)}",
                f"y1={json.dumps(float(bbox.get('y1', 0.0)), ensure_ascii=False)}",
                f"x2={json.dumps(float(bbox.get('x2', 0.0)), ensure_ascii=False)}",
                f"y2={json.dumps(float(bbox.get('y2', 0.0)), ensure_ascii=False)}",
            ]
        )
        order_label = json.dumps(int(item.get("order", 0)), ensure_ascii=False)
        label_text = f"{order_label}. {class_name} ({coords_label})"
        label_font = _load_font(10)
        label_width, label_height = _text_size(draw, label_text, label_font)
        label_box_x2 = min(width - 1, x1 + label_width + 4)
        label_box_y2 = min(height - 1, y1 + label_height + 4)
        draw.rectangle([(x1, y1), (label_box_x2, label_box_y2)], fill=(255, 255, 255), outline=color, width=1)
        draw.text((x1 + 2, y1 + 2), label_text, fill=color, font=label_font)

        content = item.get("content")
        if content is None:
            continue

        text = str(content)
        if len(text) > 4000:
            text = text[:4000]
        if not text:
            continue

        content_box_x1 = min(width - 1, max(0, x1 + 2))
        content_box_y1 = min(height - 1, max(0, y1 + 2))
        content_box_x2 = max(content_box_x1 + 1, min(width, x2 - 2))
        content_box_y2 = max(content_box_y1 + 1, min(height, y2 - 2))
        available_width = max(1, content_box_x2 - content_box_x1)
        available_height = max(1, content_box_y2 - content_box_y1)
        output_format = None if item.get("content_format") is None else str(item["content_format"])
        font, wrapped_lines, line_height = _fit_wrapped_lines(
            draw,
            text,
            output_format=output_format,
            max_width=available_width,
            max_height=available_height,
        )
        max_visible_lines = max(1, available_height // max(1, line_height))
        visible_lines = wrapped_lines[:max_visible_lines]
        for line_index, line in enumerate(visible_lines):
            y = content_box_y1 + (line_index * line_height)
            if y >= content_box_y2:
                break
            draw.text((content_box_x1, y), line, fill=(45, 50, 48), font=font)

    return canvas


def _draw_control_image(
    *,
    source_image_path: Path,
    width: int,
    height: int,
    items: list[dict[str, Any]],
    destination_path: Path,
) -> None:
    try:
        from PIL import Image, ImageDraw
    except ImportError as error:
        raise ValueError("Pillow is required for final export.") from error

    with Image.open(source_image_path) as source_image:
        source = source_image.convert("RGB")
        if source.size != (width, height):
            source = source.resize((width, height))
    reconstructed = _draw_reconstructed_canvas(width=width, height=height, items=items)
    control = Image.new("RGB", (width * 2, height), (248, 248, 248))
    control.paste(source, (0, 0))
    control.paste(reconstructed, (width, 0))
    divider = ImageDraw.Draw(control)
    divider.line([(width, 0), (width, height)], fill=(170, 170, 170), width=1)

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    control.save(destination_path)


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
    control_root = root / "control"
    images_root.mkdir(parents=True, exist_ok=True)
    control_root.mkdir(parents=True, exist_ok=True)

    metadata_rows: list[dict[str, Any]] = []
    for row in export_rows:
        rel_path = str(row["rel_path"])
        copied_image_path, width, height = _copy_source_image(rel_path, root)
        rel = _safe_relative_path(rel_path)
        control_path = control_root / rel.with_suffix(".png")

        metadata_row = {
            "page_id": int(row["page_id"]),
            "image": str(copied_image_path.relative_to(root).as_posix()),
            "control": str(control_path.relative_to(root).as_posix()),
            "width": width,
            "height": height,
            "items": row["items"],
        }
        _draw_control_image(
            source_image_path=copied_image_path,
            width=width,
            height=height,
            items=metadata_row["items"],
            destination_path=control_path,
        )
        metadata_rows.append(metadata_row)

    dataset_path = root / "dataset.jsonl"
    with dataset_path.open("w", encoding="utf-8") as handle:
        for row in metadata_rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    return {
        "export_dir": str(root),
        "dataset_file": str(dataset_path),
        "metadata_file": str(dataset_path),
        "page_count": len(metadata_rows),
        "image_count": len(metadata_rows),
        "reconstructed_count": len(metadata_rows),
        "control_count": len(metadata_rows),
    }
