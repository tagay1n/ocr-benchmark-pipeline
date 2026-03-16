from __future__ import annotations

import re
import statistics
from typing import Any

from .layout_classes import MARKDOWN_LAYOUT_CLASSES as MARKDOWN_CLASSES
from .layout_classes import normalize_class_name

SECTION_HEADER_LEVEL_H2 = 2
SECTION_HEADER_LEVEL_H3 = 3
SECTION_HEADER_LEVEL_H4 = 4
LIST_INDENT_EPSILON = 0.03
ORDERED_LIST_PREFIX_RE = re.compile(r"^\s*((?:\d+|[A-Za-zА-Яа-яЁё])[.)])\s+")
UNORDERED_LIST_PREFIX_RE = re.compile(r"^\s*([-*•‣▪◦])\s+")


def _layout_height_ratio(layout: dict[str, Any]) -> float:
    bbox = layout.get("bbox")
    if not isinstance(bbox, dict):
        return 0.0
    try:
        y1 = float(bbox.get("y1", 0.0))
        y2 = float(bbox.get("y2", 0.0))
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, y2 - y1)


def _median(values: list[float]) -> float:
    cleaned = [float(value) for value in values if float(value) > 0.0]
    if not cleaned:
        return 0.0
    return float(statistics.median(cleaned))


def section_header_baseline_text_height(layouts: list[dict[str, Any]]) -> float:
    text_heights = [
        _layout_height_ratio(layout)
        for layout in layouts
        if normalize_class_name(str(layout.get("class_name", ""))) == "text"
    ]
    baseline = _median(text_heights)
    if baseline > 0:
        return baseline

    fallback_heights = [
        _layout_height_ratio(layout)
        for layout in layouts
        if normalize_class_name(str(layout.get("class_name", ""))) in {"list_item", "footnote", "picture_text"}
    ]
    baseline = _median(fallback_heights)
    if baseline > 0:
        return baseline

    any_markdown_heights = [
        _layout_height_ratio(layout)
        for layout in layouts
        if normalize_class_name(str(layout.get("class_name", ""))) in MARKDOWN_CLASSES
        and normalize_class_name(str(layout.get("class_name", ""))) != "section_header"
    ]
    return _median(any_markdown_heights)


def section_header_level_from_ratio(height_ratio: float, baseline_text_height: float) -> int:
    if baseline_text_height <= 0:
        return SECTION_HEADER_LEVEL_H3
    ratio = float(height_ratio) / float(baseline_text_height)
    if ratio >= 2.2:
        return SECTION_HEADER_LEVEL_H2
    if ratio >= 1.6:
        return SECTION_HEADER_LEVEL_H3
    return SECTION_HEADER_LEVEL_H4


def section_header_levels_by_layout_id(layouts: list[dict[str, Any]]) -> dict[int, int]:
    baseline_text_height = section_header_baseline_text_height(layouts)
    levels: dict[int, int] = {}
    for layout in layouts:
        class_name = normalize_class_name(str(layout.get("class_name", "")))
        if class_name != "section_header":
            continue
        layout_id_raw = layout.get("id")
        try:
            layout_id = int(layout_id_raw)
        except (TypeError, ValueError):
            continue
        levels[layout_id] = section_header_level_from_ratio(
            _layout_height_ratio(layout),
            baseline_text_height,
        )
    return levels


def strip_markdown_heading_prefix(line: str) -> str:
    return re.sub(r"^\s{0,3}#{1,6}\s*", "", str(line)).strip()


def apply_section_header_heading_level(content: str, level: int) -> str:
    text = str(content).strip()
    if not text:
        return text
    safe_level = max(1, min(6, int(level)))
    lines = text.splitlines()
    first_content_idx = -1
    for idx, line in enumerate(lines):
        if line.strip():
            first_content_idx = idx
            break
    if first_content_idx < 0:
        return text
    heading_text = strip_markdown_heading_prefix(lines[first_content_idx])
    if not heading_text:
        heading_text = lines[first_content_idx].strip()
    lines[first_content_idx] = f"{'#' * safe_level} {heading_text}".strip()
    return "\n".join(lines).strip()


def normalize_formula_latex_content(content: str) -> str:
    text = str(content).strip()
    if not text:
        return text

    lines = text.splitlines()
    if len(lines) >= 2:
        opening = lines[0].strip()
        closing = lines[-1].strip()
        if (
            (opening.startswith("```") and closing == "```")
            or (opening.startswith("~~~") and closing == "~~~")
        ):
            text = "\n".join(lines[1:-1]).strip()

    if text.startswith("\\[") and text.endswith("\\]") and len(text) > 4:
        text = text[2:-2].strip()
    if text.startswith("$$") and text.endswith("$$") and len(text) > 4:
        text = text[2:-2].strip()
    if text.startswith("$") and text.endswith("$") and len(text) > 2:
        text = text[1:-1].strip()
    return text


def list_item_indent_level_from_x1(x1: float, baseline_x1: float) -> int:
    delta = max(0.0, float(x1) - float(baseline_x1))
    return int(delta / LIST_INDENT_EPSILON)


def normalize_list_item_line(
    content: str,
    *,
    indent_level: int,
    fallback_marker: str = "-",
) -> str:
    text = str(content).strip()
    if not text:
        return text
    ordered_match = ORDERED_LIST_PREFIX_RE.match(text)
    unordered_match = UNORDERED_LIST_PREFIX_RE.match(text)
    marker = ""
    body = text
    if ordered_match is not None:
        marker = ordered_match.group(1).strip()
        body = text[ordered_match.end() :].strip()
    elif unordered_match is not None:
        marker = fallback_marker
        body = text[unordered_match.end() :].strip()
    else:
        marker = fallback_marker
        body = text
    if not body:
        body = text
    indent = "  " * max(0, int(indent_level))
    return f"{indent}{marker} {body}".rstrip()


def list_item_indent_levels_by_layout_id(layouts: list[dict[str, Any]]) -> dict[int, int]:
    list_items: list[tuple[int, float]] = []
    for layout in layouts:
        if normalize_class_name(str(layout.get("class_name", ""))) != "list_item":
            continue
        try:
            layout_id = int(layout.get("id"))
            x1 = float(layout.get("bbox", {}).get("x1", 0.0))
        except (TypeError, ValueError, AttributeError):
            continue
        list_items.append((layout_id, x1))
    if not list_items:
        return {}
    baseline_x1 = min(x1 for _, x1 in list_items)
    return {
        layout_id: list_item_indent_level_from_x1(x1, baseline_x1)
        for layout_id, x1 in list_items
    }

