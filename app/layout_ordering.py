from __future__ import annotations

import math
from statistics import median
from typing import Any

LAYOUT_ORDER_MODE_AUTO = "auto"
LAYOUT_ORDER_MODE_SINGLE = "single"
LAYOUT_ORDER_MODE_MULTI_COLUMN = "multi-column"
LAYOUT_ORDER_MODE_TWO_PAGE = "two-page"

LAYOUT_ORDER_MODES = (
    LAYOUT_ORDER_MODE_AUTO,
    LAYOUT_ORDER_MODE_SINGLE,
    LAYOUT_ORDER_MODE_MULTI_COLUMN,
    LAYOUT_ORDER_MODE_TWO_PAGE,
)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def normalize_layout_order_mode(value: str | None) -> str:
    mode = str(value or "").strip().lower().replace("_", "-")
    if mode == "manual":
        return LAYOUT_ORDER_MODE_AUTO
    if mode in {"single-column", "single"}:
        return LAYOUT_ORDER_MODE_SINGLE
    if mode in LAYOUT_ORDER_MODES:
        return mode
    return LAYOUT_ORDER_MODE_AUTO


def _layout_item_from_bbox(*, bbox: dict[str, Any], pseudo_id: int) -> dict[str, float | int]:
    x1 = _clamp01(float(bbox["x1"]))
    y1 = _clamp01(float(bbox["y1"]))
    x2 = _clamp01(float(bbox["x2"]))
    y2 = _clamp01(float(bbox["y2"]))
    width = max(0.0, x2 - x1)
    height = max(0.0, y2 - y1)
    return {
        "id": int(pseudo_id),
        "x1": x1,
        "y1": y1,
        "x2": x2,
        "y2": y2,
        "width": width,
        "height": height,
        "center_x": x1 + (width / 2.0),
        "center_y": y1 + (height / 2.0),
        "reading_order": int(pseudo_id),
    }


def _cluster_column_centers(items: list[dict[str, float | int]]) -> list[dict[str, float | int]]:
    if len(items) <= 1:
        return [{"center": float(items[0]["center_x"]), "count": 1}] if items else []
    widths = [float(item["width"]) for item in items if float(item["width"]) > 0]
    median_width = float(median(widths)) if widths else 0.2
    threshold = max(0.04, min(0.2, median_width * 0.45))
    clusters: list[dict[str, float | int]] = []
    for item in sorted(items, key=lambda row: (float(row["center_x"]), float(row["center_y"]), int(row["id"]))):
        center_x = float(item["center_x"])
        nearest_idx = -1
        nearest_distance = 1e9
        for idx, cluster in enumerate(clusters):
            distance = abs(float(cluster["center"]) - center_x)
            if distance < nearest_distance:
                nearest_distance = distance
                nearest_idx = idx
        if nearest_idx >= 0 and nearest_distance <= threshold:
            cluster = clusters[nearest_idx]
            count = int(cluster["count"])
            next_count = count + 1
            cluster["center"] = ((float(cluster["center"]) * count) + center_x) / next_count
            cluster["count"] = next_count
        else:
            clusters.append({"center": center_x, "count": 1})
    clusters.sort(key=lambda cluster: float(cluster["center"]))
    return clusters


def _estimate_two_page_gutter(items: list[dict[str, float | int]]) -> float | None:
    if len(items) < 4:
        return None
    centers = [float(item["center_x"]) for item in items]
    left = [value for value in centers if value < 0.5]
    right = [value for value in centers if value >= 0.5]
    if len(left) < 2 or len(right) < 2:
        return None
    left_median = float(median(left))
    right_median = float(median(right))
    if right_median - left_median < 0.28:
        return None
    middle_count = sum(1 for value in centers if 0.45 <= value <= 0.55)
    if middle_count > max(1, int(math.floor(len(items) * 0.2))):
        return None
    return max(0.35, min(0.65, (left_median + right_median) / 2.0))


def _looks_like_multi_column(items: list[dict[str, float | int]]) -> bool:
    if len(items) < 4:
        return False
    clusters = _cluster_column_centers(items)
    if len(clusters) < 2:
        return False
    counts = sorted(int(cluster["count"]) for cluster in clusters)
    if not counts:
        return False
    return sum(counts[:-1]) >= 2


def _looks_like_multi_column_slice(items: list[dict[str, float | int]]) -> bool:
    if len(items) < 2:
        return False
    clusters = _cluster_column_centers(items)
    if len(clusters) < 2:
        return False
    centers = sorted(float(cluster["center"]) for cluster in clusters)
    if len(centers) >= 2 and (centers[-1] - centers[0]) < 0.18:
        return False
    counts = sorted(int(cluster["count"]) for cluster in clusters)
    if not counts:
        return False
    return sum(counts[:-1]) >= 1


def _order_items_single(items: list[dict[str, float | int]]) -> list[int]:
    return [
        int(item["id"])
        for item in sorted(
            items,
            key=lambda row: (
                float(row["center_y"]),
                float(row["center_x"]),
                int(row["id"]),
            ),
        )
    ]


def _order_items_multi_column(items: list[dict[str, float | int]]) -> list[int]:
    if len(items) <= 1:
        return [int(items[0]["id"])] if items else []
    widths = [float(item["width"]) for item in items if float(item["width"]) > 0]
    typical_width = float(median(widths)) if widths else 0.35
    spanning_threshold = max(0.58, min(0.92, typical_width * 1.45))
    spanning_items = [item for item in items if float(item["width"]) >= spanning_threshold]
    regular_items = [item for item in items if float(item["width"]) < spanning_threshold]
    if not regular_items:
        return _order_items_single(items)

    columns = _cluster_column_centers(regular_items)
    if len(columns) < 2:
        return _order_items_single(items)

    def column_index(center_x: float) -> int:
        nearest = 0
        nearest_distance = 1e9
        for idx, cluster in enumerate(columns):
            distance = abs(float(cluster["center"]) - center_x)
            if distance < nearest_distance:
                nearest_distance = distance
                nearest = idx
        return nearest

    regular_sorted = sorted(
        regular_items,
        key=lambda row: (
            column_index(float(row["center_x"])),
            float(row["center_y"]),
            float(row["center_x"]),
            int(row["id"]),
        ),
    )
    if not spanning_items:
        return [int(item["id"]) for item in regular_sorted]

    regular_centers_y = [float(item["center_y"]) for item in regular_items]
    regular_heights = [float(item["height"]) for item in regular_items if float(item["height"]) > 0]
    min_regular_y = min(regular_centers_y) if regular_centers_y else 0.0
    height_hint = float(median(regular_heights)) if regular_heights else 0.04
    top_prefix_tolerance = max(0.01, min(0.06, height_hint * 0.5))

    top_spanning: list[dict[str, float | int]] = []
    trailing_spanning: list[dict[str, float | int]] = []
    for item in spanning_items:
        if float(item["center_y"]) <= min_regular_y + top_prefix_tolerance:
            top_spanning.append(item)
        else:
            trailing_spanning.append(item)

    top_spanning.sort(
        key=lambda row: (
            float(row["center_y"]),
            float(row["center_x"]),
            int(row["id"]),
        )
    )
    trailing_spanning.sort(
        key=lambda row: (
            float(row["center_y"]),
            float(row["center_x"]),
            int(row["id"]),
        )
    )
    return [int(item["id"]) for item in top_spanning + regular_sorted + trailing_spanning]


def _order_items_two_page(items: list[dict[str, float | int]]) -> list[int]:
    if len(items) <= 1:
        return [int(items[0]["id"])] if items else []
    gutter = _estimate_two_page_gutter(items)
    if gutter is None:
        return _order_items_multi_column(items)

    crossing_items = [item for item in items if float(item["x1"]) < gutter < float(item["x2"])]
    left_items = [item for item in items if item not in crossing_items and float(item["center_x"]) <= gutter]
    right_items = [item for item in items if item not in crossing_items and float(item["center_x"]) > gutter]

    ordered_ids: list[int] = []
    ordered_ids.extend(
        int(item["id"])
        for item in sorted(
            crossing_items,
            key=lambda row: (
                float(row["center_y"]),
                float(row["center_x"]),
                int(row["id"]),
            ),
        )
    )
    ordered_ids.extend(_order_items_multi_column(left_items))
    ordered_ids.extend(_order_items_multi_column(right_items))
    return ordered_ids


def _order_items_auto_adaptive(items: list[dict[str, float | int]]) -> list[int]:
    if len(items) <= 1:
        return [int(items[0]["id"])] if items else []

    if _estimate_two_page_gutter(items) is not None:
        return _order_items_two_page(items)
    if not _looks_like_multi_column(items):
        return _order_items_single(items)

    widths = [float(item["width"]) for item in items if float(item["width"]) > 0]
    typical_width = float(median(widths)) if widths else 0.35
    spanning_threshold = max(0.58, min(0.92, typical_width * 1.45))
    regular_items = [item for item in items if float(item["width"]) < spanning_threshold]
    regular_heights = [float(item["height"]) for item in regular_items if float(item["height"]) > 0]
    height_hint = float(median(regular_heights)) if regular_heights else 0.06

    def mode_for_y(mid_y: float) -> str:
        active_regular = [item for item in regular_items if float(item["y1"]) <= mid_y < float(item["y2"])]
        if len(active_regular) < 2:
            return LAYOUT_ORDER_MODE_SINGLE
        return LAYOUT_ORDER_MODE_MULTI_COLUMN if _looks_like_multi_column_slice(active_regular) else LAYOUT_ORDER_MODE_SINGLE

    boundaries: list[float] = [0.0, 1.0]
    boundaries.extend(float(item["y1"]) for item in items)
    boundaries.extend(float(item["y2"]) for item in items)
    boundaries = sorted(set(max(0.0, min(1.0, value)) for value in boundaries))

    raw_bands: list[dict[str, float | str]] = []
    min_band_height = 1e-5
    for index in range(len(boundaries) - 1):
        start = float(boundaries[index])
        end = float(boundaries[index + 1])
        if end - start <= min_band_height:
            continue
        mid = (start + end) / 2.0
        raw_bands.append({"start": start, "end": end, "mode": mode_for_y(mid)})

    bridge_gap_threshold = max(0.01, min(0.06, height_hint * 0.55))
    index = 0
    while index < len(raw_bands):
        if str(raw_bands[index]["mode"]) != LAYOUT_ORDER_MODE_SINGLE:
            index += 1
            continue
        run_start = index
        run_end = index
        run_height = 0.0
        while run_end < len(raw_bands) and str(raw_bands[run_end]["mode"]) == LAYOUT_ORDER_MODE_SINGLE:
            run_height += float(raw_bands[run_end]["end"]) - float(raw_bands[run_end]["start"])
            run_end += 1
        left_mode = str(raw_bands[run_start - 1]["mode"]) if run_start > 0 else ""
        right_mode = str(raw_bands[run_end]["mode"]) if run_end < len(raw_bands) else ""
        if (
            left_mode == LAYOUT_ORDER_MODE_MULTI_COLUMN
            and right_mode == LAYOUT_ORDER_MODE_MULTI_COLUMN
            and run_height <= bridge_gap_threshold
        ):
            for bridge_index in range(run_start, run_end):
                raw_bands[bridge_index]["mode"] = LAYOUT_ORDER_MODE_MULTI_COLUMN
        index = run_end

    if not raw_bands:
        return _order_items_single(items)

    merged_bands: list[dict[str, float | str]] = []
    for band in raw_bands:
        if not merged_bands:
            merged_bands.append(dict(band))
            continue
        previous = merged_bands[-1]
        same_mode = str(previous["mode"]) == str(band["mode"])
        touching = abs(float(previous["end"]) - float(band["start"])) <= min_band_height
        if same_mode and touching:
            previous["end"] = float(band["end"])
        else:
            merged_bands.append(dict(band))

    bands_with_items: list[dict[str, Any]] = []
    for band in merged_bands:
        start = float(band["start"])
        end = float(band["end"])
        assigned = [
            item
            for item in items
            if (
                (start <= float(item["center_y"]) < end)
                or (abs(float(item["center_y"]) - end) <= min_band_height and abs(end - 1.0) <= min_band_height)
            )
        ]
        if not assigned:
            continue
        mode = str(band["mode"])
        if mode == LAYOUT_ORDER_MODE_MULTI_COLUMN and not _looks_like_multi_column(assigned):
            mode = LAYOUT_ORDER_MODE_SINGLE
        bands_with_items.append({"start": start, "end": end, "mode": mode, "items": assigned})

    if not bands_with_items:
        return _order_items_single(items)

    ordered_ids: list[int] = []
    seen_ids: set[int] = set()
    for band in sorted(bands_with_items, key=lambda row: float(row["start"])):
        band_items = [item for item in band["items"] if int(item["id"]) not in seen_ids]
        if not band_items:
            continue
        mode = str(band["mode"])
        band_order = _order_items_multi_column(band_items) if mode == LAYOUT_ORDER_MODE_MULTI_COLUMN else _order_items_single(band_items)
        for row_id in band_order:
            if int(row_id) in seen_ids:
                continue
            seen_ids.add(int(row_id))
            ordered_ids.append(int(row_id))

    if len(seen_ids) != len(items):
        missing_items = [item for item in _order_items_single(items) if int(item) not in seen_ids]
        ordered_ids.extend(int(row_id) for row_id in missing_items)

    return ordered_ids


def infer_layout_order_mode(items: list[dict[str, float | int]]) -> str:
    if _estimate_two_page_gutter(items) is not None:
        return LAYOUT_ORDER_MODE_TWO_PAGE
    if _looks_like_multi_column(items):
        return LAYOUT_ORDER_MODE_MULTI_COLUMN
    return LAYOUT_ORDER_MODE_SINGLE


def order_layout_items_by_mode(items: list[dict[str, float | int]], mode: str) -> list[int]:
    normalized_mode = normalize_layout_order_mode(mode)
    if len(items) <= 1:
        return [int(items[0]["id"])] if items else []
    if normalized_mode == LAYOUT_ORDER_MODE_AUTO:
        return _order_items_auto_adaptive(items)
    if normalized_mode == LAYOUT_ORDER_MODE_SINGLE:
        return _order_items_single(items)
    if normalized_mode == LAYOUT_ORDER_MODE_MULTI_COLUMN:
        return _order_items_multi_column(items)
    if normalized_mode == LAYOUT_ORDER_MODE_TWO_PAGE:
        return _order_items_two_page(items)
    return _order_items_single(items)


def insertion_reading_order_by_mode(
    items: list[dict[str, float | int]],
    *,
    bbox: dict[str, Any],
    mode: str,
) -> int:
    if not items:
        return 1
    normalized_mode = normalize_layout_order_mode(mode)
    candidate = _layout_item_from_bbox(bbox=bbox, pseudo_id=-1)

    def _fallback_with_pseudo() -> int:
        pseudo_id = -1
        items_with_candidate = list(items)
        items_with_candidate.append(candidate)
        ordered_ids = order_layout_items_by_mode(items_with_candidate, normalized_mode)
        if pseudo_id not in ordered_ids:
            return len(items) + 1
        return ordered_ids.index(pseudo_id) + 1

    def _stable_multi_column_insertion() -> int | None:
        widths = [float(item["width"]) for item in items if float(item["width"]) > 0]
        typical_width = float(median(widths)) if widths else 0.35
        spanning_threshold = max(0.58, min(0.92, typical_width * 1.45))
        regular_items = [item for item in items if float(item["width"]) < spanning_threshold]
        base_items = regular_items if len(regular_items) >= 2 else list(items)
        if not base_items:
            return None

        candidate_x1 = float(candidate["x1"])
        candidate_x2 = float(candidate["x2"])
        candidate_width = max(1e-6, float(candidate["width"]))
        candidate_center_x = float(candidate["center_x"])

        def horizontally_related(row: dict[str, float | int]) -> bool:
            row_x1 = float(row["x1"])
            row_x2 = float(row["x2"])
            row_width = max(1e-6, float(row["width"]))
            overlap = max(0.0, min(row_x2, candidate_x2) - max(row_x1, candidate_x1))
            overlap_ratio = overlap / max(1e-6, min(row_width, candidate_width))
            row_center_x = float(row["center_x"])
            center_tolerance = max(0.03, min(0.22, max(row_width, candidate_width) * 0.7))
            center_close = abs(row_center_x - candidate_center_x) <= center_tolerance
            center_in_row = row_x1 <= candidate_center_x <= row_x2
            row_center_in_candidate = candidate_x1 <= row_center_x <= candidate_x2
            return overlap_ratio >= 0.2 or center_close or center_in_row or row_center_in_candidate

        column_items = [item for item in base_items if horizontally_related(item)]
        if not column_items:
            nearest = min(
                base_items,
                key=lambda row: (
                    abs(float(row["center_x"]) - candidate_center_x),
                    float(row["center_y"]),
                    int(row["id"]),
                ),
            )
            column_items = [nearest]

        candidate_center_y = float(candidate["center_y"])
        above_items = [item for item in column_items if float(item["center_y"]) <= candidate_center_y]
        if above_items:
            anchor = max(
                above_items,
                key=lambda row: (
                    float(row["center_y"]),
                    int(row["reading_order"]),
                    int(row["id"]),
                ),
            )
            return min(len(items) + 1, int(anchor["reading_order"]) + 1)

        first_in_column = min(
            column_items,
            key=lambda row: (
                int(row["reading_order"]),
                float(row["center_y"]),
                int(row["id"]),
            ),
        )
        return max(1, int(first_in_column["reading_order"]))

    def _supports_multi_column_insertion_shape() -> bool:
        widths = [float(item["width"]) for item in items if float(item["width"]) > 0]
        typical_width = float(median(widths)) if widths else 0.35
        spanning_threshold = max(0.58, min(0.92, typical_width * 1.45))
        regular_items = [item for item in items if float(item["width"]) < spanning_threshold]
        base_items = regular_items if len(regular_items) >= 2 else list(items)
        if len(base_items) < 2:
            return False
        return len(_cluster_column_centers(base_items)) >= 2

    if normalized_mode == LAYOUT_ORDER_MODE_MULTI_COLUMN:
        stable_order = _stable_multi_column_insertion()
        if stable_order is not None:
            return stable_order
        return _fallback_with_pseudo()

    if normalized_mode == LAYOUT_ORDER_MODE_AUTO:
        if _supports_multi_column_insertion_shape():
            stable_order = _stable_multi_column_insertion()
            if stable_order is not None:
                return stable_order
        return _fallback_with_pseudo()

    return _fallback_with_pseudo()
