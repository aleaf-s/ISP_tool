import tempfile
import unittest
import json
from pathlib import Path

import cv2
import numpy as np

from isp_tool.auto_calibration import (
    AutoCalibrationController,
    BLCAnalyzer,
    DPCAnalyzer,
    DPCCalibrator,
    NoiseProfiler,
    SharpenAnalyzer,
    ToneAnalyzer,
    load_defect_map,
    save_defect_map,
)
from isp_tool.auto_calibration.base import AnalysisCancelled
from isp_tool.auto_calibration.persistence import (
    load_recommendation,
    save_recommendation,
)
from isp_tool.bayer import channel_positions
from isp_tool.config import load_config, migrate_config, save_config
from isp_tool.calibration.report import export_calibration_report
from isp_tool.models import CalibrationSession, ImageROI, RawMetadata
from isp_tool.pipeline import ISPPipeline


class AutoBLCTests(unittest.TestCase):
    def setUp(self):
        self.metadata = RawMetadata(
            width=120,
            height=96,
            bit_depth=12,
            bayer_pattern="RGGB",
            black_level=[64, 66, 65, 68],
            white_level=4095,
        )

    def _dark_frame(self):
        rng = np.random.default_rng(4)
        image = np.zeros((96, 120), np.float32)
        levels = {"R": 64, "Gr": 66, "Gb": 65, "B": 68}
        for name, (y, x) in channel_positions("RGGB").items():
            plane = image[y::2, x::2]
            plane[:] = levels[name] + rng.normal(0, 0.8, plane.shape)
        image[12, 18] = 4095
        return image

    def test_four_channel_dark_level_is_recovered_robustly(self):
        pipeline = ISPPipeline()
        result = AutoCalibrationController(pipeline).analyze(
            BLCAnalyzer(), self._dark_frame(), self.metadata
        )
        expected = {"r": 64, "gr": 66, "gb": 65, "b": 68}
        for key, value in expected.items():
            self.assertAlmostEqual(result.suggested_parameters[key], value, delta=1)
        self.assertIn("Hot Pixel Candidate Mask", result.artifacts)
        self.assertGreater(result.confidence, 0.7)

    def test_bright_roi_produces_warning(self):
        image = self._dark_frame() + 600
        result = AutoCalibrationController(ISPPipeline()).analyze(
            BLCAnalyzer(), image, self.metadata
        )
        self.assertTrue(any("可能不是暗场" in item for item in result.warnings))


class DPCCalibrationTests(unittest.TestCase):
    def setUp(self):
        self.metadata = RawMetadata(
            width=64, height=48, bit_depth=12,
            bayer_pattern="RGGB", black_level=[0] * 4, white_level=1.0,
        )

    def test_persistent_defects_are_separated_from_random_noise(self):
        rng = np.random.default_rng(7)
        dark_frames = []
        flat_frames = []
        for index in range(6):
            dark = np.clip(rng.normal(0.02, 0.001, (48, 64)), 0, 1).astype(np.float32)
            flat = np.clip(rng.normal(0.5, 0.002, (48, 64)), 0, 1).astype(np.float32)
            dark[10, 12] = 0.9
            flat[11, 13] = 0.02
            dark[20 + index, 30] = 0.8  # non-persistent random outlier
            dark_frames.append(dark)
            flat_frames.append(flat)
        result = AutoCalibrationController(ISPPipeline()).analyze(
            DPCCalibrator(),
            dark_frames[0],
            self.metadata,
            dark_frames=dark_frames,
            flat_frames=flat_frames,
            persistence_threshold=0.8,
        )
        defect = result.artifacts["Persistent Defect Mask"]
        self.assertEqual(defect[10, 12], 1)
        self.assertEqual(defect[11, 13], 2)
        self.assertEqual(defect[20, 30], 0)
        self.assertEqual(result.suggested_parameters["mode"], "Hybrid")

    def test_defect_map_json_and_npz_round_trip(self):
        frames = [np.full((48, 64), 0.02, np.float32) for _ in range(4)]
        for frame in frames:
            frame[8, 8] = 1.0
        recommendation = AutoCalibrationController(ISPPipeline()).analyze(
            DPCCalibrator(),
            frames[0],
            self.metadata,
            dark_frames=frames,
        )
        from isp_tool.auto_calibration.dpc_calibrator import DefectMap
        defect_map = DefectMap.from_dict(
            recommendation.measurements["defect_map"]
        )
        with tempfile.TemporaryDirectory() as folder:
            for suffix in (".json", ".npz"):
                path = Path(folder) / f"defects{suffix}"
                save_defect_map(str(path), defect_map)
                restored = load_defect_map(str(path), self.metadata)
                np.testing.assert_array_equal(
                    restored.to_array(), defect_map.to_array()
                )

    def test_single_frame_recommends_valid_threshold(self):
        image = np.full((48, 64), 0.2, np.float32)
        image[10, 10] = 0.9
        result = AutoCalibrationController(ISPPipeline()).analyze(
            DPCAnalyzer(), image, self.metadata
        )
        self.assertGreaterEqual(result.suggested_parameters["threshold"], 0.005)
        self.assertTrue(result.artifacts["Hot Pixel Mask"][10, 10])


class NoiseProfileTests(unittest.TestCase):
    def test_shot_and_read_noise_fit(self):
        rng = np.random.default_rng(11)
        height, width = 160, 192
        image = np.zeros((height, width, 3), np.float32)
        levels = (0.08, 0.18, 0.35, 0.65)
        shot, read = 0.00018, 0.000015
        rois = []
        band = height // len(levels)
        for index, level in enumerate(levels):
            sigma = np.sqrt(shot * level + read)
            y0 = index * band
            values = rng.normal(level, sigma, (band, width, 3))
            image[y0:y0 + band] = np.clip(values, 0, 1)
            rois.append(ImageROI(4, y0 + 4, width - 8, band - 8))
        metadata = RawMetadata(width=width, height=height)
        result = AutoCalibrationController(ISPPipeline()).analyze(
            NoiseProfiler(),
            image,
            metadata,
            rois=rois,
            domain="rgb",
        )
        fitted = result.measurements["channel_models"]["G"]
        self.assertAlmostEqual(fitted["shot_noise"], shot, delta=shot * 0.45)
        self.assertAlmostEqual(fitted["read_noise"], read, delta=read * 0.8)
        self.assertIn(result.suggested_parameters["radius"], {3, 5, 7})
        self.assertGreater(result.confidence, 0.25)


class ToneAndSharpenTests(unittest.TestCase):
    def setUp(self):
        self.metadata = RawMetadata(width=256, height=128)
        x = np.linspace(0, 1.4, 256, dtype=np.float32)
        linear = np.tile(x, (128, 1))
        self.rgb = np.repeat(linear[:, :, None], 3, axis=2)

    def test_tone_curve_is_monotonic_and_finite(self):
        result = AutoCalibrationController(ISPPipeline()).analyze(
            ToneAnalyzer(), self.rgb, self.metadata, mode="Natural"
        )
        curve = result.artifacts["Suggested Tone Curve"][:, 1]
        self.assertTrue(np.all(np.isfinite(curve)))
        self.assertTrue(np.all(np.diff(curve) >= -1e-6))
        self.assertTrue(result.measurements["curve_monotonic"])

    def test_highlight_mode_clips_less_than_high_contrast(self):
        controller = AutoCalibrationController(ISPPipeline())
        protected = controller.analyze(
            ToneAnalyzer(), self.rgb, self.metadata, mode="Preserve Highlights"
        )
        contrast = controller.analyze(
            ToneAnalyzer(), self.rgb, self.metadata, mode="High Contrast"
        )
        self.assertLess(
            protected.measurements["predicted_clipped_high"],
            contrast.measurements["predicted_clipped_high"],
        )

    def test_high_noise_produces_more_conservative_sharpen(self):
        base = np.zeros((128, 256, 3), np.float32)
        base[:, :128] = 0.2
        base[:, 128:] = 0.75
        rng = np.random.default_rng(2)
        clean = np.clip(base + rng.normal(0, 0.002, base.shape), 0, 1)
        noisy = np.clip(base + rng.normal(0, 0.055, base.shape), 0, 1)
        controller = AutoCalibrationController(ISPPipeline())
        clean_result = controller.analyze(
            SharpenAnalyzer(), clean, self.metadata
        )
        noisy_result = controller.analyze(
            SharpenAnalyzer(), noisy, self.metadata
        )
        self.assertLess(
            noisy_result.suggested_parameters["strength"],
            clean_result.suggested_parameters["strength"],
        )
        self.assertGreater(
            noisy_result.suggested_parameters["threshold"],
            clean_result.suggested_parameters["threshold"],
        )


class ControllerTests(unittest.TestCase):
    def test_analyze_preview_revert_and_apply_lifecycle(self):
        pipeline = ISPPipeline()
        changes = []
        controller = AutoCalibrationController(
            pipeline, lambda: changes.append("changed")
        )
        metadata = RawMetadata(width=64, height=64)
        image = np.full((64, 64), 72.0, np.float32)
        original = dict(
            pipeline.module_by_id("black_level_correction").parameters
        )
        recommendation = controller.analyze(
            BLCAnalyzer(), image, metadata
        )
        self.assertEqual(
            pipeline.module_by_id("black_level_correction").parameters,
            original,
        )
        controller.preview(recommendation)
        self.assertNotEqual(
            pipeline.module_by_id("black_level_correction").parameters,
            original,
        )
        controller.revert()
        self.assertEqual(
            pipeline.module_by_id("black_level_correction").parameters,
            original,
        )
        controller.apply(recommendation)
        self.assertTrue(recommendation.applied)
        self.assertFalse(controller.has_preview)
        self.assertGreaterEqual(len(changes), 3)

    def test_stale_generation_is_rejected(self):
        pipeline = ISPPipeline()
        controller = AutoCalibrationController(pipeline)
        generation, token = controller.begin_analysis()
        controller.begin_analysis()
        with self.assertRaises(AnalysisCancelled):
            controller.analyze(
                BLCAnalyzer(),
                np.full((32, 32), 64, np.float32),
                RawMetadata(width=32, height=32),
                generation=generation,
                cancel_token=token,
            )


class V4PersistenceTests(unittest.TestCase):
    def test_v3_migrates_to_v4_defaults(self):
        migrated = migrate_config({
            "schema_version": 3,
            "raw": {},
            "pipeline": [],
            "calibration": {},
        })
        self.assertEqual(migrated["schema_version"], 4)
        calibration = migrated["calibration"]
        self.assertEqual(calibration["auto_recommendations"], {})
        self.assertEqual(calibration["calibration_history"], [])
        self.assertIsNone(calibration["noise_profile"])

    def test_recommendation_summary_and_artifacts_round_trip(self):
        pipeline = ISPPipeline()
        metadata = RawMetadata(width=32, height=32)
        recommendation = AutoCalibrationController(pipeline).analyze(
            BLCAnalyzer(), np.full((32, 32), 72, np.float32), metadata
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "analysis.json"
            save_recommendation(str(path), recommendation)
            restored = load_recommendation(str(path))
            self.assertEqual(restored.suggested_parameters,
                             recommendation.suggested_parameters)
            self.assertEqual(set(restored.artifacts),
                             set(recommendation.artifacts))
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("artifact_file", data)

    def test_static_dpc_map_is_externalized_and_loaded(self):
        pipeline = ISPPipeline()
        module = pipeline.module_by_id("defective_pixel_correction")
        defect = np.zeros((32, 48), np.uint8)
        defect[4, 6] = 1
        defect[5, 7] = 2
        module.set_defect_map(defect)
        module.parameters["mode"] = "Static Map"
        metadata = RawMetadata(
            width=48, height=32, bayer_pattern="RGGB",
            black_level=[0] * 4, white_level=1,
        )
        session = CalibrationSession(raw_metadata=metadata)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            save_config(
                str(path), metadata, pipeline, calibration=session
            )
            raw = json.loads(path.read_text(encoding="utf-8"))
            dpc = next(
                item for item in raw["pipeline"]
                if item["id"] == "defective_pixel_correction"
            )
            self.assertIn("external_path", dpc["state"])
            self.assertTrue((path.parent / dpc["state"]["external_path"]).exists())
            loaded = load_config(str(path))
            restored_dpc = next(
                item for item in loaded["pipeline"]
                if item["id"] == "defective_pixel_correction"
            )
            self.assertEqual(restored_dpc["state"]["shape"], [32, 48])
            self.assertEqual(len(restored_dpc["state"]["defect_pixels"]), 2)

    def test_markdown_report_includes_auto_analysis(self):
        pipeline = ISPPipeline()
        metadata = RawMetadata(width=32, height=32)
        session = CalibrationSession(raw_metadata=metadata)
        controller = AutoCalibrationController(pipeline, session=session)
        recommendation = controller.analyze(
            BLCAnalyzer(), np.full((32, 32), 72, np.float32), metadata
        )
        controller.apply(recommendation)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "report.md"
            export_calibration_report(str(path), session)
            text = path.read_text(encoding="utf-8")
            self.assertIn("Automatic Analysis", text)
            self.assertIn("auto_blc", text)
            self.assertIn("Applied recommendation count: 1", text)


if __name__ == "__main__":
    unittest.main()
