import unittest

import numpy as np

from isp_tool import __version__
from isp_tool.bayer import (
    bayer_to_rgb_bilinear,
    channel_positions,
    split_planes,
)
from isp_tool.models import RawMetadata
from isp_tool.modules.white_balance import WhiteBalance
from isp_tool.preview import (
    bayer_cell_rgb,
    bayer_false_color,
    resize_bayer_mosaic_preview,
)


class BayerMosaicDisplayTests(unittest.TestCase):
    def setUp(self):
        self.metadata = RawMetadata(
            width=8,
            height=6,
            bit_depth=12,
            bayer_pattern="RGGB",
            black_level=(64, 68, 72, 76),
            white_level=4095,
        )

    def test_raw_preview_does_not_apply_black_level_correction(self):
        normalized = {
            "R": 0.20,
            "Gr": 0.40,
            "Gb": 0.50,
            "B": 0.70,
        }
        raw = np.empty((6, 8), np.float32)
        for index, (name, (y, x)) in enumerate(
            channel_positions("RGGB").items()
        ):
            black = self.metadata.black_level[index]
            raw[y::2, x::2] = (
                black
                + normalized[name]
                * (self.metadata.white_level - black)
            )
        preview = bayer_false_color(
            raw, self.metadata, already_normalized=False
        )
        channel_index = {"R": 0, "Gr": 1, "Gb": 1, "B": 2}
        for name, (y, x) in channel_positions("RGGB").items():
            samples = preview[y::2, x::2]
            expected = np.zeros(3, np.float32)
            expected[channel_index[name]] = (
                float(raw[y, x]) / self.metadata.white_level
            )
            np.testing.assert_allclose(
                samples,
                np.broadcast_to(expected, samples.shape),
                atol=1e-6,
            )

    def test_normalized_wb_values_above_two_are_not_treated_as_dn(self):
        normalized = np.zeros((6, 8), np.float32)
        for name, (y, x) in channel_positions("RGGB").items():
            normalized[y::2, x::2] = {
                "R": 3.0,
                "Gr": 0.6,
                "Gb": 0.7,
                "B": 2.5,
            }[name]
        preview = bayer_false_color(
            normalized,
            self.metadata,
            already_normalized=True,
        )
        self.assertEqual(float(preview[0, 0, 0]), 1.0)
        self.assertEqual(float(preview[1, 1, 2]), 1.0)
        self.assertAlmostEqual(float(preview[0, 1, 1]), 0.6)
        self.assertEqual(float(preview[0, 1, 0]), 0.0)
        self.assertEqual(float(preview[0, 1, 2]), 0.0)

    def test_balanced_cfa_planes_remain_balanced_after_demosaic(self):
        bayer = np.empty((20, 24), np.float32)
        source_values = {
            "R": 0.25,
            "Gr": 0.50,
            "Gb": 0.50,
            "B": 0.20,
        }
        for name, (y, x) in channel_positions("RGGB").items():
            bayer[y::2, x::2] = source_values[name]
        wb = WhiteBalance()
        wb.parameters.update({
            "r_gain": 2.0,
            "gr_gain": 1.0,
            "gb_gain": 1.0,
            "b_gain": 2.5,
            "exposure_gain": 1.0,
        })
        balanced, domain, _ = wb.process(
            bayer, "bayer", self.metadata
        )
        self.assertEqual(domain, "bayer")
        for plane in split_planes(balanced, "RGGB").values():
            np.testing.assert_allclose(plane, 0.5, atol=1e-7)
        rgb = bayer_to_rgb_bilinear(balanced, "RGGB")
        np.testing.assert_allclose(rgb, 0.5, atol=1e-6)
        np.testing.assert_allclose(
            bayer_cell_rgb(
                balanced,
                self.metadata,
                already_normalized=True,
            ),
            0.5,
            atol=1e-7,
        )

    def test_fit_resize_preserves_all_four_cfa_phases(self):
        bayer = np.empty((20, 24), np.float32)
        for name, (y, x) in channel_positions("RGGB").items():
            bayer[y::2, x::2] = {
                "R": 0.2,
                "Gr": 0.4,
                "Gb": 0.5,
                "B": 0.7,
            }[name]
        mosaic = bayer_false_color(
            bayer, self.metadata, already_normalized=True
        )
        resized = resize_bayer_mosaic_preview(
            mosaic, 8, 6, "RGGB"
        )
        expected_channels = {
            "R": (0, 0.2),
            "Gr": (1, 0.4),
            "Gb": (1, 0.5),
            "B": (2, 0.7),
        }
        for name, (y, x) in channel_positions("RGGB").items():
            channel, expected = expected_channels[name]
            samples = resized[y::2, x::2]
            self.assertTrue(
                np.allclose(samples[:, :, channel], expected)
            )
            self.assertTrue(
                np.allclose(
                    np.delete(samples, channel, axis=2), 0.0
                )
            )

    def test_version_is_v0413(self):
        self.assertGreaterEqual(
            tuple(map(int, __version__.split("."))),
            (0, 4, 13),
        )


if __name__ == "__main__":
    unittest.main()
