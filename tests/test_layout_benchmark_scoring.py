from __future__ import annotations

import unittest

from app import layout_benchmark_scoring


class LayoutBenchmarkScoringModuleTests(unittest.TestCase):
    def test_normalize_prediction_rows_applies_remap_and_exclusions(self) -> None:
        rows = [
            {"class_name": "title", "x1": 0.1, "y1": 0.1, "x2": 0.6, "y2": 0.2, "confidence": 0.9},
            {"class_name": "picture_text", "x1": 0.2, "y1": 0.2, "x2": 0.5, "y2": 0.3, "confidence": 0.8},
            {"class_name": "text", "x1": 0.2, "y1": 0.4, "x2": 0.7, "y2": 0.5, "confidence": "0.7"},
        ]
        normalized = layout_benchmark_scoring.normalize_prediction_rows(
            rows,
            class_remap={"title": "section_header"},
            excluded_classes=frozenset({"picture_text"}),
        )
        self.assertEqual(len(normalized), 2)
        self.assertEqual(normalized[0]["class_name"], "section_header")
        self.assertEqual(normalized[1]["class_name"], "text")

    def test_map50_95_score_prefers_perfect_match(self) -> None:
        gt = (
            {"class_name": "text", "bbox": {"x1": 0.1, "y1": 0.1, "x2": 0.6, "y2": 0.6}},
        )
        perfect_pred = [{"class_name": "text", "x1": 0.1, "y1": 0.1, "x2": 0.6, "y2": 0.6, "confidence": 0.9}]
        shifted_pred = [{"class_name": "text", "x1": 0.18, "y1": 0.18, "x2": 0.68, "y2": 0.68, "confidence": 0.9}]

        perfect_score, perfect_metrics = layout_benchmark_scoring.map50_95_score(
            gt,
            perfect_pred,
            class_remap={},
            excluded_classes=frozenset(),
            iou_thresholds=tuple(round(0.5 + 0.05 * idx, 2) for idx in range(10)),
        )
        shifted_score, shifted_metrics = layout_benchmark_scoring.map50_95_score(
            gt,
            shifted_pred,
            class_remap={},
            excluded_classes=frozenset(),
            iou_thresholds=tuple(round(0.5 + 0.05 * idx, 2) for idx in range(10)),
        )
        self.assertGreater(perfect_score, shifted_score)
        self.assertEqual(float(perfect_metrics["map50"]), 1.0)
        self.assertLess(float(shifted_metrics["map50_95"]), 1.0)

    def test_average_precision_returns_none_when_both_empty(self) -> None:
        ap = layout_benchmark_scoring.average_precision_by_iou_threshold(
            [],
            [],
            iou_thresholds=(0.5, 0.75),
        )
        self.assertIsNone(ap)


if __name__ == "__main__":
    unittest.main()

