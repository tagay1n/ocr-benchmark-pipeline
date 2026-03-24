from __future__ import annotations

from typing import Any

LAYOUT_ORIENTATION_HORIZONTAL = "horizontal"
LAYOUT_ORIENTATION_VERTICAL = "vertical"

LAYOUT_ORIENTATIONS = (
    LAYOUT_ORIENTATION_HORIZONTAL,
    LAYOUT_ORIENTATION_VERTICAL,
)

DEFAULT_VERTICAL_RATIO_THRESHOLD = 2.0


def normalize_layout_orientation(value: str | None) -> str:
    normalized = str(value or "").strip().lower().replace("_", "-")
    if normalized in {"h", "hor", "horizontal"}:
        return LAYOUT_ORIENTATION_HORIZONTAL
    if normalized in {"v", "ver", "vertical"}:
        return LAYOUT_ORIENTATION_VERTICAL
    return LAYOUT_ORIENTATION_HORIZONTAL


def infer_layout_orientation_from_bbox(
    *,
    bbox: dict[str, Any] | None,
    ratio_threshold: float = DEFAULT_VERTICAL_RATIO_THRESHOLD,
) -> str:
    x1 = float((bbox or {}).get("x1", 0.0))
    y1 = float((bbox or {}).get("y1", 0.0))
    x2 = float((bbox or {}).get("x2", 0.0))
    y2 = float((bbox or {}).get("y2", 0.0))
    width = max(0.0, x2 - x1)
    height = max(0.0, y2 - y1)
    if width <= 0 or height <= 0:
        return LAYOUT_ORIENTATION_HORIZONTAL
    threshold = max(1.0, float(ratio_threshold))
    return (
        LAYOUT_ORIENTATION_VERTICAL
        if (height / width) >= threshold
        else LAYOUT_ORIENTATION_HORIZONTAL
    )


def is_effective_vertical(
    *,
    orientation: str | None,
    bbox: dict[str, Any] | None,
    ratio_threshold: float = DEFAULT_VERTICAL_RATIO_THRESHOLD,
) -> bool:
    mode = str(orientation or "").strip().lower().replace("_", "-")
    if mode in {"vertical", "v"}:
        return True
    if mode in {"horizontal", "h"}:
        return False
    return infer_layout_orientation_from_bbox(
        bbox=bbox,
        ratio_threshold=ratio_threshold,
    ) == LAYOUT_ORIENTATION_VERTICAL
