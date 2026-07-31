from concurrent.futures import CancelledError
import unittest

import cv2
import numpy as np

from isp_tool import __version__
from isp_tool.bayer import (
    bayer_to_rgb_bilinear,
    masks,
)
from isp_tool.models import RawMetadata
from isp_tool.modules import (
    ColorCorrectionMatrix,
    DefectivePixelCorrection,
    LensShadingCorrection,
    NoiseReduction,
    Sharpen,
)
from isp_tool.modules.color_adjust import ColorAdjustment
from isp_tool.modules.tone import evaluate_tone_curve
from isp_tool.pipeline import ISPPipeline
from isp_tool.raw_io import synthetic_bayer
from isp_tool.ui.performance_metrics import PerformanceMetrics


def reference_bilinear(image, pattern):
    src = np.asarray(image, dtype=np.float32)
    cfa_masks = masks(src.shape, pattern)
    kernels = {
        "R": np.array([[1, 2, 1], [2, 4, 2], [1, 2, 1]], np.float32),
        "G": np.array([[0, 1, 0], [1, 4, 1], [0, 1, 0]], np.float32),
        "B": np.array([[1, 2, 1], [2, 4, 2], [1, 2, 1]], np.float32),
    }
    channels = []
    for channel in ("R", "G", "B"):
        mask = (
            cfa_masks["Gr"] | cfa_masks["Gb"]
            if channel == "G"
            else cfa_masks[channel]
        )
        weights = mask.astype(np.float32)
        numerator = cv2.filter2D(
            src * weights,
            -1,
            kernels[channel],
            borderType=cv2.BORDER_REFLECT_101,
        )
        denominator = cv2.filter2D(
            weights,
            -1,
            kernels[channel],
            borderType=cv2.BORDER_REFLECT_101,
        )
        channels.append(numerator / np.maximum(denominator, 1e-8))
    return np.stack(channels, axis=-1)


def reference_tone(values, parameters):
    src = np.asarray(values, dtype=np.float32)
    black = float(parameters["black_point"])
    white = max(float(parameters["white_point"]), black + 1e-6)
    linear = np.clip((src - black) / (white - black), 0.0, 1.0)
    toe = float(parameters["toe_strength"])
    if toe > 0:
        lifted = linear * linear * (3.0 - 2.0 * linear)
        linear = linear * (1.0 - toe) + lifted * toe
    shoulder = float(parameters["shoulder_strength"])
    if shoulder > 0:
        compressed = linear / (
            linear + (1.0 - linear) * (1.0 + 2.0 * shoulder)
        )
        linear = linear * (1.0 - shoulder) + compressed * shoulder
    contrast = float(parameters["contrast"])
    linear = np.clip(
        (linear - 0.18) * contrast + 0.18, 0.0, 1.0
    )
    gamma = max(float(parameters["gamma"]), 0.01)
    return np.power(linear, 1.0 / gamma).astype(np.float32)


class OptimizedKernelParityTests(unittest.TestCase):
    def test_bilinear_matches_previous_normalized_convolution_at_borders(self):
        rng = np.random.default_rng(46)
        for shape in ((31, 43), (32, 44)):
            for pattern in ("RGGB", "GRBG", "GBRG", "BGGR"):
                with self.subTest(shape=shape, pattern=pattern):
                    source = rng.random(shape, dtype=np.float32)
                    np.testing.assert_array_equal(
                        bayer_to_rgb_bilinear(source, pattern),
                        reference_bilinear(source, pattern),
                    )

    def test_tone_matches_previous_numpy_formula(self):
        source = np.random.default_rng(2).random(
            (39, 53, 3), dtype=np.float32
        )
        parameters = {
            "black_point": 0.03,
            "white_point": 1.17,
            "toe_strength": 0.27,
            "shoulder_strength": 0.41,
            "contrast": 1.13,
            "gamma": 2.31,
        }
        np.testing.assert_allclose(
            evaluate_tone_curve(source, parameters),
            reference_tone(source, parameters),
            atol=3e-7,
            rtol=1e-6,
        )

    def test_ccm_effective_transform_matches_previous_blend_formula(self):
        source = np.random.default_rng(4).random(
            (27, 41, 3), dtype=np.float32
        )
        module = ColorCorrectionMatrix()
        module.parameters.update(
            {
                "m00": 1.13,
                "m01": -0.08,
                "m12": 0.07,
                "m21": -0.04,
                "offset_r": 0.013,
                "offset_b": -0.009,
                "strength": 0.37,
            }
        )
        matrix = module.matrix()
        offset = np.array(
            [
                module.parameters["offset_r"],
                module.parameters["offset_g"],
                module.parameters["offset_b"],
            ],
            np.float32,
        )
        corrected = np.einsum("...c,dc->...d", source, matrix) + offset
        expected = (
            source * (1.0 - module.parameters["strength"])
            + corrected * module.parameters["strength"]
        )
        actual = module.process(source, "rgb", RawMetadata())[0]
        np.testing.assert_allclose(actual, expected, atol=3e-7, rtol=1e-6)


class NeutralFastPathTests(unittest.TestCase):
    def test_neutral_modules_reuse_input_without_rgb_copies(self):
        source = np.random.default_rng(8).random(
            (32, 48, 3), dtype=np.float32
        )
        for module in (
            ColorCorrectionMatrix(),
            NoiseReduction(),
            Sharpen(),
        ):
            with self.subTest(module=module.module_id):
                output = module.process(source, "rgb", RawMetadata())[0]
                self.assertTrue(np.shares_memory(output, source))

    def test_neutral_lsc_reuses_bayer_input_and_keeps_gain_artifact(self):
        source = np.random.default_rng(9).random(
            (32, 48), dtype=np.float32
        )
        output, _, _, artifacts = LensShadingCorrection().process(
            source, "bayer", RawMetadata(width=48, height=32)
        )
        self.assertTrue(np.shares_memory(output, source))
        np.testing.assert_array_equal(
            artifacts["LSC Gain Map"], np.ones_like(source)
        )

    def test_neutral_color_adjustment_preserves_final_clipping_behavior(self):
        source = np.array([[[-0.1, 0.4, 1.2]]], np.float32)
        output = ColorAdjustment().process(
            source, "rgb", RawMetadata()
        )[0]
        np.testing.assert_array_equal(
            output, np.array([[[0.0, 0.4, 1.0]]], np.float32)
        )


class PipelinePerformanceContractTests(unittest.TestCase):
    def test_pipeline_reports_wall_overhead_and_module_timings(self):
        loaded = synthetic_bayer(96, 64)
        pipeline = ISPPipeline()
        cache = {}
        snapshot = pipeline.snapshot()
        pipeline.process_cached(
            loaded.image,
            loaded.domain,
            loaded.metadata,
            snapshot,
            cache,
            1,
        )
        metrics = cache["last_metrics"]
        self.assertGreaterEqual(
            metrics["wall_elapsed_ms"], metrics["elapsed_ms"]
        )
        self.assertGreaterEqual(metrics["overhead_ms"], 0.0)
        self.assertEqual(
            set(metrics["module_timings"]),
            {module.module_id for module in pipeline.modules},
        )

        pipeline.process_cached(
            loaded.image,
            loaded.domain,
            loaded.metadata,
            snapshot,
            cache,
            1,
        )
        self.assertEqual(cache["last_metrics"]["recomputed"], 0)
        self.assertEqual(cache["last_metrics"]["module_timings"], {})

    def test_superseded_pipeline_can_stop_between_modules(self):
        loaded = synthetic_bayer(96, 64)
        cache = {}
        with self.assertRaises(CancelledError):
            ISPPipeline().process_cached(
                loaded.image,
                loaded.domain,
                loaded.metadata,
                ISPPipeline().snapshot(),
                cache,
                1,
                cancel_check=lambda: True,
            )
        self.assertNotIn("results", cache)

    def test_performance_details_rank_slowest_modules(self):
        metrics = PerformanceMetrics()
        metrics.record("module:slow", 20)
        metrics.record("module:fast", 2)
        details = metrics.details_text()
        self.assertIn("slowest rolling average first", details)
        self.assertLess(details.index("slow"), details.index("fast"))


class VersionTests(unittest.TestCase):
    def test_version_is_at_least_v046(self):
        self.assertGreaterEqual(
            tuple(map(int, __version__.split("."))), (0, 4, 6)
        )


if __name__ == "__main__":
    unittest.main()
