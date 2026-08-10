import unittest

import numpy as np

from isp_tool.bayer import channel_positions
from isp_tool.models import RawMetadata
from isp_tool.modules import (
    BlackLevelCorrection,
    ColorCorrectionMatrix,
    ToneMapping,
    WhiteBalance,
)
from isp_tool.preview import bayer_mosaic_rgb


class ModuleTests(unittest.TestCase):
    def setUp(self):
        self.metadata = RawMetadata(
            width=8,
            height=8,
            bit_depth=12,
            bayer_pattern="RGGB",
            black_level=[64.0] * 4,
            white_level=4095.0,
        )

    def test_blc_maps_black_to_zero_and_white_to_one(self):
        source = np.full((8, 8), 64.0, np.float32)
        source[4:, :] = 4095.0
        module = BlackLevelCorrection()
        output, domain, diagnostics = module.process(source, "bayer", self.metadata)
        self.assertEqual(domain, "bayer")
        self.assertAlmostEqual(float(output[:4].max()), 0.0)
        self.assertAlmostEqual(float(output[4:].min()), 1.0)
        self.assertEqual(diagnostics["负值截断"], 0)

    def test_zero_blc_matches_uncorrected_raw_preview(self):
        source = np.linspace(
            0.0,
            self.metadata.white_level,
            64,
            dtype=np.float32,
        ).reshape(8, 8)
        module = BlackLevelCorrection()
        module.parameters.update({
            "r": 0.0,
            "gr": 0.0,
            "gb": 0.0,
            "b": 0.0,
            "global_offset": 0.0,
        })

        output, _, _ = module.process(
            source,
            "bayer",
            self.metadata,
        )
        before = bayer_mosaic_rgb(
            source,
            self.metadata,
            already_normalized=False,
        )
        after = bayer_mosaic_rgb(
            output,
            self.metadata,
            already_normalized=True,
        )

        np.testing.assert_allclose(
            output,
            source / self.metadata.white_level,
            atol=1e-7,
        )
        np.testing.assert_allclose(after, before, atol=1e-7)

    def test_white_balance_uses_four_bayer_gains(self):
        source = np.ones((8, 8), np.float32)
        module = WhiteBalance()
        module.parameters.update({
            "r_gain": 2.0,
            "gr_gain": 1.1,
            "gb_gain": 1.2,
            "b_gain": 1.8,
            "exposure_gain": 1.0,
            "gain_limit": 8.0,
        })
        output, _, _ = module.process(source, "bayer", self.metadata)
        expected = {"R": 2.0, "Gr": 1.1, "Gb": 1.2, "B": 1.8}
        for name, (y, x) in channel_positions("RGGB").items():
            self.assertAlmostEqual(float(output[y::2, x::2].mean()), expected[name], places=5)

    def test_identity_ccm_preserves_rgb(self):
        rng = np.random.default_rng(2)
        source = rng.random((10, 12, 3), dtype=np.float32)
        output, domain, _ = ColorCorrectionMatrix().process(source, "rgb", self.metadata)
        self.assertEqual(domain, "rgb")
        np.testing.assert_allclose(output, source, atol=1e-6)

    def test_gamma_mid_gray(self):
        source = np.full((3, 4, 3), 0.25, np.float32)
        module = ToneMapping()
        module.parameters["gamma"] = 2.0
        output, _, _ = module.process(source, "rgb", self.metadata)
        np.testing.assert_allclose(output, 0.5, atol=1e-6)


if __name__ == "__main__":
    unittest.main()
