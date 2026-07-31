import unittest

import numpy as np

from isp_tool.bayer import (
    bayer_to_rgb_adaptive,
    bayer_to_rgb_bilinear,
    bayer_to_rgb_constant_color_difference,
    bayer_to_rgb_nearest,
    channel_positions,
    merge_planes,
    resize_bayer_preview,
    split_planes,
)


class BayerTests(unittest.TestCase):
    def test_channel_positions_have_expected_green_names(self):
        for pattern in ("RGGB", "GRBG", "GBRG", "BGGR"):
            positions = channel_positions(pattern)
            self.assertEqual(set(positions), {"R", "Gr", "Gb", "B"})
            self.assertEqual(len(set(positions.values())), 4)
            self.assertEqual(positions["Gr"][0], positions["R"][0])
            self.assertEqual(positions["Gb"][0], positions["B"][0])

    def test_split_merge_round_trip(self):
        source = np.arange(8 * 12, dtype=np.float32).reshape(8, 12)
        for pattern in ("RGGB", "GRBG", "GBRG", "BGGR"):
            merged = merge_planes(split_planes(source, pattern), pattern)
            np.testing.assert_array_equal(merged, source)

    def test_resize_preserves_four_plane_values(self):
        source = np.zeros((100, 200), np.float32)
        values = {"R": 0.1, "Gr": 0.2, "Gb": 0.3, "B": 0.4}
        for name, (y, x) in channel_positions("RGGB").items():
            source[y::2, x::2] = values[name]
        resized = resize_bayer_preview(source, "RGGB", max_side=80)
        self.assertLessEqual(max(resized.shape), 80)
        for name, plane in split_planes(resized, "RGGB").items():
            self.assertAlmostEqual(float(plane.mean()), values[name], places=5)

    def test_bilinear_demosaic_constant_color(self):
        source = np.zeros((32, 40), np.float32)
        values = {"R": 0.2, "Gr": 0.4, "Gb": 0.4, "B": 0.8}
        for name, (y, x) in channel_positions("RGGB").items():
            source[y::2, x::2] = values[name]
        rgb = bayer_to_rgb_bilinear(source, "RGGB")
        center = rgb[3:-3, 3:-3].mean(axis=(0, 1))
        np.testing.assert_allclose(center, [0.2, 0.4, 0.8], atol=1e-5)

    def test_all_product_demosaic_algorithms_keep_rgb_order(self):
        values = {"R": 0.2, "Gr": 0.4, "Gb": 0.4, "B": 0.8}
        algorithms = (
            bayer_to_rgb_nearest,
            bayer_to_rgb_bilinear,
            bayer_to_rgb_adaptive,
            bayer_to_rgb_constant_color_difference,
        )
        for pattern in ("RGGB", "GRBG", "GBRG", "BGGR"):
            for algorithm in algorithms:
                with self.subTest(
                    pattern=pattern,
                    algorithm=algorithm.__name__,
                ):
                    source = np.zeros((32, 40), np.float32)
                    for name, (y, x) in channel_positions(pattern).items():
                        source[y::2, x::2] = values[name]
                    rgb = algorithm(source, pattern)
                    center = rgb[4:-4, 4:-4].mean(axis=(0, 1))
                    np.testing.assert_allclose(
                        center,
                        [0.2, 0.4, 0.8],
                        atol=2e-4,
                    )


if __name__ == "__main__":
    unittest.main()
