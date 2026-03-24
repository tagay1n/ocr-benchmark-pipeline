from __future__ import annotations

import unittest

from app import layout_ordering


class LayoutOrderingModuleTests(unittest.TestCase):
    def test_normalize_layout_order_mode_maps_aliases(self) -> None:
        self.assertEqual(layout_ordering.normalize_layout_order_mode("manual"), "auto")
        self.assertEqual(layout_ordering.normalize_layout_order_mode("single-column"), "single")
        self.assertEqual(layout_ordering.normalize_layout_order_mode("two_page"), "two-page")
        self.assertEqual(layout_ordering.normalize_layout_order_mode("unknown"), "auto")

    def test_order_layout_items_by_mode_single_is_top_to_bottom_then_left_to_right(self) -> None:
        items = [
            {"id": 1, "x1": 0.4, "y1": 0.3, "x2": 0.8, "y2": 0.4, "width": 0.4, "height": 0.1, "center_x": 0.6, "center_y": 0.35, "reading_order": 1},
            {"id": 2, "x1": 0.1, "y1": 0.1, "x2": 0.3, "y2": 0.2, "width": 0.2, "height": 0.1, "center_x": 0.2, "center_y": 0.15, "reading_order": 2},
            {"id": 3, "x1": 0.1, "y1": 0.3, "x2": 0.3, "y2": 0.4, "width": 0.2, "height": 0.1, "center_x": 0.2, "center_y": 0.35, "reading_order": 3},
        ]
        ordered = layout_ordering.order_layout_items_by_mode(items, "single")
        self.assertEqual(ordered, [2, 3, 1])

    def test_insertion_reading_order_by_mode_places_candidate_between_neighbors(self) -> None:
        items = [
            {"id": 10, "x1": 0.1, "y1": 0.1, "x2": 0.8, "y2": 0.2, "width": 0.7, "height": 0.1, "center_x": 0.45, "center_y": 0.15, "reading_order": 1},
            {"id": 11, "x1": 0.1, "y1": 0.5, "x2": 0.8, "y2": 0.6, "width": 0.7, "height": 0.1, "center_x": 0.45, "center_y": 0.55, "reading_order": 2},
        ]
        order = layout_ordering.insertion_reading_order_by_mode(
            items,
            bbox={"x1": 0.1, "y1": 0.3, "x2": 0.8, "y2": 0.4},
            mode="single",
        )
        self.assertEqual(order, 2)

    def test_infer_layout_order_mode_detects_multi_column(self) -> None:
        items = [
            {"id": 1, "x1": 0.30, "y1": 0.1, "x2": 0.50, "y2": 0.2, "width": 0.2, "height": 0.1, "center_x": 0.4, "center_y": 0.15, "reading_order": 1},
            {"id": 2, "x1": 0.52, "y1": 0.12, "x2": 0.72, "y2": 0.22, "width": 0.2, "height": 0.1, "center_x": 0.62, "center_y": 0.17, "reading_order": 2},
            {"id": 3, "x1": 0.30, "y1": 0.3, "x2": 0.50, "y2": 0.4, "width": 0.2, "height": 0.1, "center_x": 0.4, "center_y": 0.35, "reading_order": 3},
            {"id": 4, "x1": 0.52, "y1": 0.32, "x2": 0.72, "y2": 0.42, "width": 0.2, "height": 0.1, "center_x": 0.62, "center_y": 0.37, "reading_order": 4},
        ]
        mode = layout_ordering.infer_layout_order_mode(items)
        self.assertEqual(mode, "multi-column")

    def test_insertion_multi_column_prefers_same_column_anchor_order(self) -> None:
        # Reading orders are intentionally interleaved to ensure insertion uses
        # the same-column anchor rather than recomputing full page ordering.
        items = [
            {"id": 1, "x1": 0.08, "y1": 0.10, "x2": 0.38, "y2": 0.18, "width": 0.30, "height": 0.08, "center_x": 0.23, "center_y": 0.14, "reading_order": 1},
            {"id": 2, "x1": 0.56, "y1": 0.12, "x2": 0.86, "y2": 0.20, "width": 0.30, "height": 0.08, "center_x": 0.71, "center_y": 0.16, "reading_order": 2},
            {"id": 3, "x1": 0.08, "y1": 0.28, "x2": 0.38, "y2": 0.36, "width": 0.30, "height": 0.08, "center_x": 0.23, "center_y": 0.32, "reading_order": 3},
            {"id": 4, "x1": 0.56, "y1": 0.30, "x2": 0.86, "y2": 0.38, "width": 0.30, "height": 0.08, "center_x": 0.71, "center_y": 0.34, "reading_order": 4},
            {"id": 5, "x1": 0.08, "y1": 0.46, "x2": 0.38, "y2": 0.54, "width": 0.30, "height": 0.08, "center_x": 0.23, "center_y": 0.50, "reading_order": 5},
        ]
        order = layout_ordering.insertion_reading_order_by_mode(
            items,
            bbox={"x1": 0.08, "y1": 0.40, "x2": 0.38, "y2": 0.48},
            mode="multi-column",
        )
        self.assertEqual(order, 4)

    def test_insertion_auto_uses_multi_column_stable_rule_when_detected(self) -> None:
        items = [
            {"id": 11, "x1": 0.08, "y1": 0.10, "x2": 0.38, "y2": 0.18, "width": 0.30, "height": 0.08, "center_x": 0.23, "center_y": 0.14, "reading_order": 1},
            {"id": 12, "x1": 0.56, "y1": 0.12, "x2": 0.86, "y2": 0.20, "width": 0.30, "height": 0.08, "center_x": 0.71, "center_y": 0.16, "reading_order": 2},
            {"id": 13, "x1": 0.08, "y1": 0.28, "x2": 0.38, "y2": 0.36, "width": 0.30, "height": 0.08, "center_x": 0.23, "center_y": 0.32, "reading_order": 3},
            {"id": 14, "x1": 0.56, "y1": 0.30, "x2": 0.86, "y2": 0.38, "width": 0.30, "height": 0.08, "center_x": 0.71, "center_y": 0.34, "reading_order": 4},
            {"id": 15, "x1": 0.08, "y1": 0.46, "x2": 0.38, "y2": 0.54, "width": 0.30, "height": 0.08, "center_x": 0.23, "center_y": 0.50, "reading_order": 5},
        ]
        order = layout_ordering.insertion_reading_order_by_mode(
            items,
            bbox={"x1": 0.08, "y1": 0.40, "x2": 0.38, "y2": 0.48},
            mode="auto",
        )
        self.assertEqual(order, 4)

    def test_insertion_auto_handles_borderline_two_column_with_same_column_anchor(self) -> None:
        # Borderline page: not enough boxes for explicit multi-column detection,
        # but insertion should still anchor in the geometrically matching column.
        items = [
            {"id": 21, "x1": 0.08, "y1": 0.10, "x2": 0.38, "y2": 0.18, "width": 0.30, "height": 0.08, "center_x": 0.23, "center_y": 0.14, "reading_order": 1},
            {"id": 22, "x1": 0.56, "y1": 0.14, "x2": 0.86, "y2": 0.22, "width": 0.30, "height": 0.08, "center_x": 0.71, "center_y": 0.18, "reading_order": 2},
            {"id": 23, "x1": 0.08, "y1": 0.42, "x2": 0.38, "y2": 0.50, "width": 0.30, "height": 0.08, "center_x": 0.23, "center_y": 0.46, "reading_order": 3},
        ]
        order = layout_ordering.insertion_reading_order_by_mode(
            items,
            bbox={"x1": 0.08, "y1": 0.28, "x2": 0.38, "y2": 0.36},
            mode="auto",
        )
        self.assertEqual(order, 2)


if __name__ == "__main__":
    unittest.main()
