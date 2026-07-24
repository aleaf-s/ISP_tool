import unittest

import numpy as np

from isp_tool.analysis import compute_statistics, compute_waveform
from isp_tool.config import migrate_config
from isp_tool.models import ImageROI, RawMetadata
from isp_tool.modules import (
    ColorCorrectionMatrix,
    DefectivePixelCorrection,
    LensShadingCorrection,
    ToneMapping,
)
from isp_tool.modules.tone import evaluate_tone_curve
from isp_tool.pipeline import ISPPipeline
from isp_tool.raw_io import synthetic_bayer


class ROITests(unittest.TestCase):
    def test_roi_aligns_to_even_bayer_boundaries(self):
        roi = ImageROI(11, 13, 51, 49).align_for_bayer((200, 300))
        self.assertEqual((roi.x, roi.y), (10, 12))
        self.assertEqual(roi.width % 2, 0)
        self.assertEqual(roi.height % 2, 0)
        self.assertGreaterEqual(roi.x2, 62)
        self.assertGreaterEqual(roi.y2, 62)

    def test_roi_halo_contains_core_and_is_bayer_aligned(self):
        roi = ImageROI(20, 30, 80, 60)
        expanded = roi.expanded(17, (160, 200), bayer_aligned=True)
        self.assertLessEqual(expanded.x, roi.x)
        self.assertLessEqual(expanded.y, roi.y)
        self.assertGreaterEqual(expanded.x2, roi.x2)
        self.assertGreaterEqual(expanded.y2, roi.y2)
        self.assertEqual(expanded.x % 2, 0)
        self.assertEqual(expanded.y % 2, 0)

    def test_roi_pipeline_matches_full_frame_crop(self):
        source = synthetic_bayer(320, 240)
        pipeline = ISPPipeline()
        lsc = pipeline.module_by_id("lens_shading_correction")
        lsc.parameters.update({
            "r_strength": 0.7,
            "gr_strength": 0.5,
            "gb_strength": 0.55,
            "b_strength": 0.8,
        })
        roi = ImageROI(54, 42, 120, 100)
        full = pipeline.process(source.image, source.domain, source.metadata)
        partial = pipeline.process(
            source.image, source.domain, source.metadata, roi=roi, roi_halo=24
        )
        ys, xs = roi.slices()
        for full_stage, roi_stage in zip(full, partial):
            with self.subTest(stage=full_stage.name):
                np.testing.assert_allclose(
                    full_stage.image[ys, xs], roi_stage.image, atol=1e-6
                )

    def test_roi_change_invalidates_cache(self):
        source = synthetic_bayer(160, 120)
        pipeline = ISPPipeline()
        cache = {}
        pipeline.process_cached(
            source.image, source.domain, source.metadata,
            pipeline.snapshot(), cache, 1, ImageROI(20, 20, 60, 60),
        )
        pipeline.process_cached(
            source.image, source.domain, source.metadata,
            pipeline.snapshot(), cache, 1, ImageROI(40, 20, 60, 60),
        )
        self.assertEqual(cache["last_metrics"]["cache_hits"], 0)
        self.assertEqual(cache["last_metrics"]["recomputed"], len(pipeline.modules))


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.metadata = RawMetadata(
            width=32, height=32, bit_depth=12, bayer_pattern="RGGB",
            black_level=[0.0] * 4, white_level=1.0,
        )

    def test_dpc_returns_separate_hot_and_dark_mask(self):
        source = np.full((32, 32), 0.5, np.float32)
        source[8, 8] = 1.0
        source[15, 15] = 0.0
        module = DefectivePixelCorrection()
        output, domain, diagnostics, artifacts = module.process(
            source, "bayer", self.metadata
        )
        self.assertEqual(domain, "bayer")
        self.assertEqual(output.shape, source.shape)
        self.assertIn("Defect Mask", artifacts)
        self.assertGreaterEqual(diagnostics["亮坏点"], 1)
        self.assertGreaterEqual(diagnostics["暗坏点"], 1)
        self.assertEqual(artifacts["Defect Mask"][8, 8], 1)
        self.assertEqual(artifacts["Defect Mask"][15, 15], 2)

    def test_lsc_gain_map_is_artifact_and_respects_max_gain(self):
        source = np.ones((32, 32), np.float32)
        module = LensShadingCorrection()
        module.parameters.update({
            "r_strength": 3.0,
            "gr_strength": 3.0,
            "gb_strength": 3.0,
            "b_strength": 3.0,
            "max_gain": 2.0,
        })
        output, _, _, artifacts = module.process(source, "bayer", self.metadata)
        gain = artifacts["LSC Gain Map"]
        self.assertLessEqual(float(gain.max()), 2.0)
        np.testing.assert_allclose(output, gain, atol=1e-6)


class AnalysisAndConfigTests(unittest.TestCase):
    def test_tone_curve_preview_matches_module(self):
        module = ToneMapping()
        module.parameters.update({
            "gamma": 2.0,
            "black_point": 0.05,
            "white_point": 0.9,
            "contrast": 1.2,
            "toe_strength": 0.3,
            "shoulder_strength": 0.4,
        })
        source = np.linspace(0, 1, 99, dtype=np.float32).reshape(3, 11, 3)
        expected = evaluate_tone_curve(source, module.parameters)
        actual, _, _ = module.process(source, "rgb", RawMetadata())
        np.testing.assert_allclose(actual, expected, atol=1e-7)

    def test_ccm_strength_and_offset(self):
        module = ColorCorrectionMatrix()
        source = np.full((4, 5, 3), [0.2, 0.3, 0.4], np.float32)
        module.parameters.update({
            "m00": 2.0,
            "offset_r": 0.1,
            "strength": 0.0,
        })
        bypass, _, _ = module.process(source, "rgb", RawMetadata())
        np.testing.assert_allclose(bypass, source, atol=1e-7)
        module.parameters["strength"] = 1.0
        corrected, _, _ = module.process(source, "rgb", RawMetadata())
        np.testing.assert_allclose(corrected[:, :, 0], 0.5, atol=1e-7)

    def test_waveform_modes_have_requested_shape_and_range(self):
        image = np.random.default_rng(3).random((80, 120, 3), dtype=np.float32)
        for mode in ("Luma", "RGB Overlay", "RGB Parade"):
            waveform = compute_waveform(
                image, "rgb", RawMetadata(), mode=mode, width=101, height=64
            )
            self.assertEqual(waveform.shape, (64, 101, 3))
            self.assertGreaterEqual(float(waveform.min()), 0.0)
            self.assertLessEqual(float(waveform.max()), 1.0)

    def test_bayer_statistics_include_four_channels(self):
        image = np.arange(64, dtype=np.float32).reshape(8, 8)
        stats = compute_statistics(image, "bayer", RawMetadata(white_level=63))
        self.assertEqual(set(stats["channels"]), {"R", "Gr", "Gb", "B"})
        for channel in stats["channels"].values():
            self.assertIn("mean", channel)
            self.assertIn("median", channel)
            self.assertIn("std", channel)

    def test_v1_config_migrates_to_current_schema(self):
        old = {
            "version": "0.1.0",
            "raw": {"width": 100, "height": 80},
            "pipeline": [{
                "name": "white_balance",
                "enabled": True,
                "parameters": {"r_gain": 2.1},
            }],
        }
        migrated = migrate_config(old)
        self.assertEqual(migrated["schema_version"], 4)
        self.assertEqual(migrated["tool_version"], "0.1.0")
        self.assertEqual(migrated["pipeline"][0]["id"], "white_balance")
        self.assertIn("ui_state", migrated)

    def test_invalid_config_parameters_are_clamped_or_ignored(self):
        pipeline = ISPPipeline()
        warnings = pipeline.load_snapshot([
            {
                "id": "white_balance",
                "enabled": True,
                "parameters": {"r_gain": 999, "unknown": 3},
            },
            {"id": "not_a_module", "enabled": True, "parameters": {}},
        ])
        self.assertEqual(
            pipeline.module_by_id("white_balance").parameters["r_gain"], 8
        )
        self.assertGreaterEqual(len(warnings), 2)


if __name__ == "__main__":
    unittest.main()
