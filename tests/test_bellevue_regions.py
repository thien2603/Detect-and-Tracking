import json
import unittest
from pathlib import Path

import cv2
import numpy as np

from scripts.preview_bellevue_regions import area, split_intersection


class BellevueRegionTests(unittest.TestCase):
    def test_rectangle_partition(self):
        count, alert = split_intersection([[0, 0], [400, 0], [400, 200], [0, 200]])
        self.assertEqual(area(count), 60000)
        self.assertEqual(area(alert), 20000)
        self.assertEqual(count[1], alert[0])
        self.assertEqual(count[2], alert[3])

    def test_four_camera_partitions(self):
        root = Path(__file__).resolve().parents[1]
        layout = json.loads((root / "configs/bellevue-region-layout.json").read_text())
        self.assertEqual(len(layout["cameras"]), 4)
        for camera in layout["cameras"]:
            with self.subTest(camera=camera["id"]):
                count, alert = split_intersection(camera["intersection"])
                total = area(count) + area(alert)
                self.assertAlmostEqual(area(count) / total, 0.75, delta=0.004)
                self.assertAlmostEqual(total / area(camera["intersection"]), 1, delta=0.004)
                overlap, _ = cv2.intersectConvexConvex(
                    np.array(count, np.float32), np.array(alert, np.float32)
                )
                self.assertLessEqual(overlap, 1)
                for x, y in count + alert:
                    self.assertTrue(0 <= x < 1280 and 0 <= y < 720)

    def test_reject_crossed_polygon(self):
        with self.assertRaises(ValueError):
            split_intersection([[0, 0], [100, 100], [0, 100], [100, 0]])

    def test_reject_degenerate_polygon(self):
        with self.assertRaises(ValueError):
            split_intersection([[0, 0], [1, 0], [2, 0], [3, 0]])

    def test_reject_invalid_fraction(self):
        for fraction in (0, 1, -0.1):
            with self.subTest(fraction=fraction), self.assertRaises(ValueError):
                split_intersection([[0, 0], [100, 0], [100, 100], [0, 100]], fraction)


if __name__ == "__main__":
    unittest.main()
