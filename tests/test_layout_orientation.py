from __future__ import annotations

import unittest

from app.layout_orientation import (
    infer_layout_orientation_from_bbox,
    is_effective_vertical,
    normalize_layout_orientation,
)


class LayoutOrientationTests(unittest.TestCase):
    def test_normalize_layout_orientation(self) -> None:
        self.assertEqual(normalize_layout_orientation(None), "horizontal")
        self.assertEqual(normalize_layout_orientation(""), "horizontal")
        self.assertEqual(normalize_layout_orientation("automatic"), "horizontal")
        self.assertEqual(normalize_layout_orientation("h"), "horizontal")
        self.assertEqual(normalize_layout_orientation("horizontal"), "horizontal")
        self.assertEqual(normalize_layout_orientation("v"), "vertical")
        self.assertEqual(normalize_layout_orientation("vertical"), "vertical")
        self.assertEqual(normalize_layout_orientation("unknown"), "horizontal")

    def test_infer_layout_orientation_from_bbox(self) -> None:
        self.assertEqual(
            infer_layout_orientation_from_bbox(
                bbox={"x1": 0.1, "y1": 0.1, "x2": 0.4, "y2": 0.85}
            ),
            "vertical",
        )
        self.assertEqual(
            infer_layout_orientation_from_bbox(
                bbox={"x1": 0.1, "y1": 0.1, "x2": 0.8, "y2": 0.4}
            ),
            "horizontal",
        )

    def test_effective_vertical_respects_explicit_orientation_and_ratio(self) -> None:
        bbox = {"x1": 0.1, "y1": 0.1, "x2": 0.4, "y2": 0.8}  # h/w = 0.7 / 0.3 = 2.33
        self.assertTrue(is_effective_vertical(orientation="unknown", bbox=bbox))
        self.assertTrue(is_effective_vertical(orientation="vertical", bbox={"x1": 0.1, "y1": 0.1, "x2": 0.9, "y2": 0.3}))
        self.assertFalse(is_effective_vertical(orientation="horizontal", bbox=bbox))

        near_square_bbox = {"x1": 0.1, "y1": 0.1, "x2": 0.5, "y2": 0.7}  # h/w = 1.5
        self.assertFalse(is_effective_vertical(orientation="unknown", bbox=near_square_bbox))


if __name__ == "__main__":
    unittest.main()
