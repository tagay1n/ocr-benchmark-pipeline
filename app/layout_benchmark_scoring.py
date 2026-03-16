from __future__ import annotations

import math
from typing import Any

from .layout_classes import normalize_class_name


def normalize_layout_class_for_benchmark(class_name: str, class_remap: dict[str, str]) -> str:
    normalized = normalize_class_name(class_name)
    return class_remap.get(normalized, normalized)


def bbox_iou(box_a: dict[str, float], box_b: dict[str, float]) -> float:
    source_a = box_a["bbox"] if isinstance(box_a.get("bbox"), dict) else box_a
    source_b = box_b["bbox"] if isinstance(box_b.get("bbox"), dict) else box_b
    ax1, ay1, ax2, ay2 = (
        float(source_a["x1"]),
        float(source_a["y1"]),
        float(source_a["x2"]),
        float(source_a["y2"]),
    )
    bx1, by1, bx2, by2 = (
        float(source_b["x1"]),
        float(source_b["y1"]),
        float(source_b["x2"]),
        float(source_b["y2"]),
    )
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    intersection = (ix2 - ix1) * (iy2 - iy1)
    area_a = max(0.0, (ax2 - ax1) * (ay2 - ay1))
    area_b = max(0.0, (bx2 - bx1) * (by2 - by1))
    union = area_a + area_b - intersection
    if union <= 0:
        return 0.0
    return intersection / union


def compute_ap_from_pr_curve(recalls: list[float], precisions: list[float]) -> float:
    if not recalls or not precisions or len(recalls) != len(precisions):
        return 0.0
    recall_values = [0.0] + recalls + [1.0]
    precision_values = [0.0] + precisions + [0.0]
    for index in range(len(precision_values) - 2, -1, -1):
        precision_values[index] = max(precision_values[index], precision_values[index + 1])
    area_sum = 0.0
    value_index = 0
    for point in range(101):
        target_recall = point / 100.0
        while value_index < len(recall_values) and recall_values[value_index] < target_recall:
            value_index += 1
        if value_index >= len(precision_values):
            area_sum += 0.0
        else:
            area_sum += float(precision_values[value_index])
    return area_sum / 101.0


def average_precision_by_iou_threshold(
    gt_boxes: list[dict[str, Any]],
    pred_boxes: list[dict[str, Any]],
    *,
    iou_thresholds: tuple[float, ...],
) -> list[tuple[float, float]] | None:
    if not gt_boxes:
        return [] if pred_boxes else None
    if not pred_boxes:
        return [(threshold, 0.0) for threshold in iou_thresholds]

    sorted_pred = sorted(
        pred_boxes,
        key=lambda row: float(row.get("confidence") if row.get("confidence") is not None else 0.0),
        reverse=True,
    )
    gt_total = float(len(gt_boxes))
    ap_values: list[tuple[float, float]] = []
    for iou_threshold in iou_thresholds:
        matched_gt: set[int] = set()
        tp_prefix: list[float] = []
        fp_prefix: list[float] = []
        tp_total = 0.0
        fp_total = 0.0
        for pred_box in sorted_pred:
            best_gt_idx = -1
            best_iou = 0.0
            for gt_idx, gt_box in enumerate(gt_boxes):
                if gt_idx in matched_gt:
                    continue
                iou = bbox_iou(gt_box, pred_box)
                if iou >= iou_threshold and iou > best_iou:
                    best_iou = iou
                    best_gt_idx = gt_idx
            if best_gt_idx >= 0:
                matched_gt.add(best_gt_idx)
                tp_total += 1.0
            else:
                fp_total += 1.0
            tp_prefix.append(tp_total)
            fp_prefix.append(fp_total)

        recalls = [tp / gt_total for tp in tp_prefix]
        precisions = [
            (tp_prefix[index] / (tp_prefix[index] + fp_prefix[index]))
            if (tp_prefix[index] + fp_prefix[index]) > 0
            else 0.0
            for index in range(len(tp_prefix))
        ]
        ap_values.append((float(iou_threshold), compute_ap_from_pr_curve(recalls, precisions)))
    return ap_values


def map50_95_score(
    gt_layouts: tuple[dict[str, Any], ...],
    pred_layouts: list[dict[str, Any]],
    *,
    class_remap: dict[str, str],
    excluded_classes: frozenset[str],
    iou_thresholds: tuple[float, ...],
) -> tuple[float, dict[str, Any]]:
    gt_by_class: dict[str, list[dict[str, Any]]] = {}
    pred_by_class: dict[str, list[dict[str, Any]]] = {}

    for row in gt_layouts:
        class_name = normalize_layout_class_for_benchmark(str(row["class_name"]), class_remap)
        if class_name in excluded_classes:
            continue
        gt_by_class.setdefault(class_name, []).append(row)
    for row in pred_layouts:
        class_name = normalize_layout_class_for_benchmark(str(row["class_name"]), class_remap)
        if class_name in excluded_classes:
            continue
        pred_by_class.setdefault(class_name, []).append(row)

    class_names = sorted(set(gt_by_class.keys()) | set(pred_by_class.keys()))
    if not class_names:
        return 1.0, {"map50_95": 1.0, "map50": 1.0}

    class_map_values: list[float] = []
    class_ap50_values: list[float] = []
    for class_name in class_names:
        gt_boxes = gt_by_class.get(class_name, [])
        pred_boxes = pred_by_class.get(class_name, [])
        ap_by_threshold = average_precision_by_iou_threshold(
            gt_boxes,
            pred_boxes,
            iou_thresholds=iou_thresholds,
        )
        if ap_by_threshold is None:
            continue
        ap50_95 = (
            sum(ap_value for _threshold, ap_value in ap_by_threshold) / len(ap_by_threshold)
            if ap_by_threshold
            else 0.0
        )
        class_map_values.append(float(ap50_95))

        ap50 = next((ap for threshold, ap in ap_by_threshold if math.isclose(threshold, 0.5, abs_tol=1e-9)), 0.0)
        class_ap50_values.append(ap50)

    mean_map50_95 = sum(class_map_values) / len(class_map_values) if class_map_values else 1.0
    mean_map50 = sum(class_ap50_values) / len(class_ap50_values) if class_ap50_values else 1.0
    return mean_map50_95, {
        "map50_95": mean_map50_95,
        "map50": mean_map50,
    }


def normalize_prediction_rows(
    pred_layouts: list[dict[str, Any]],
    *,
    class_remap: dict[str, str],
    excluded_classes: frozenset[str],
) -> list[dict[str, Any]]:
    normalized_rows: list[dict[str, Any]] = []
    for row in pred_layouts:
        if not isinstance(row, dict):
            continue
        class_name = str(row.get("class_name") or "").strip()
        if not class_name:
            continue
        class_name = normalize_layout_class_for_benchmark(class_name, class_remap)
        if class_name in excluded_classes:
            continue
        try:
            x1 = float(row["x1"])
            y1 = float(row["y1"])
            x2 = float(row["x2"])
            y2 = float(row["y2"])
        except (KeyError, TypeError, ValueError):
            continue
        confidence_value = row.get("confidence")
        try:
            confidence = None if confidence_value is None else float(confidence_value)
        except (TypeError, ValueError):
            confidence = None
        normalized_rows.append(
            {
                "class_name": class_name,
                "confidence": confidence,
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
            }
        )
    return normalized_rows

