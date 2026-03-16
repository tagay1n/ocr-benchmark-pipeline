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


if __name__ == "__main__":
    unittest.main()
