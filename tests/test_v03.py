import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from isp_tool.analysis.vectorscope import (
    compute_vectorscope,
    vectorscope_coordinates,
)
from isp_tool.bayer import channel_positions
from isp_tool.calibration.ae import estimate_exposure
from isp_tool.calibration.awb import estimate_awb
from isp_tool.calibration.ccm_solver import apply_ccm, solve_ccm
from isp_tool.calibration.colorchecker import (
    colorchecker_reference,
    generate_colorchecker_grid,
    sample_colorchecker,
)
from isp_tool.calibration.flat_field import generate_lsc_mesh
from isp_tool.calibration.lsc_mesh import (
    interpolate_mesh_channels,
    load_lsc_mesh,
    save_lsc_mesh,
)
from isp_tool.calibration.report import export_calibration_report
from isp_tool.config import load_config, migrate_config, save_config
from isp_tool.models import (
    AEResult,
    AWBResult,
    CalibrationSession,
    ImageROI,
    ISPError,
    LSCMesh,
    RawMetadata,
)
from isp_tool.pipeline import ISPPipeline
from isp_tool.raw_io import synthetic_bayer


def constant_mesh(rows=5, cols=7, values=(1.0, 1.0, 1.0, 1.0)):
    arrays = [np.full((rows, cols), value, np.float32) for value in values]
    return LSCMesh(rows, cols, *arrays)


class LSCMeshTests(unittest.TestCase):
    def test_constant_mesh_interpolation(self):
        mesh = constant_mesh(values=(1.1, 1.2, 1.3, 1.4))
        maps = interpolate_mesh_channels(mesh, (100, 140))
        for name, expected in zip(("R", "Gr", "Gb", "B"), (1.1, 1.2, 1.3, 1.4)):
            np.testing.assert_allclose(maps[name], expected, atol=1e-6)

    def test_mesh_four_channel_mapping_in_pipeline(self):
        source = synthetic_bayer(160, 120)
        pipeline = ISPPipeline()
        for module in pipeline.modules:
            module.enabled = module.module_id == "lens_shading_correction"
        lsc = pipeline.module_by_id("lens_shading_correction")
        lsc.set_mesh(constant_mesh(values=(1.1, 1.2, 1.3, 1.4)))
        lsc.parameters["mode"] = "Mesh Model"
        result = pipeline.process(source.image, "bayer", source.metadata)[3].image
        for name, (y, x) in channel_positions("RGGB").items():
            expected = {"R": 1.1, "Gr": 1.2, "Gb": 1.3, "B": 1.4}[name]
            ratio = result[y::2, x::2] / source.image[y::2, x::2]
            self.assertAlmostEqual(float(ratio.mean()), expected, places=5)

    def test_mesh_roi_matches_full_frame(self):
        source = synthetic_bayer(240, 180)
        pipeline = ISPPipeline()
        nodes = np.linspace(1, 2, 35, dtype=np.float32).reshape(5, 7)
        mesh = LSCMesh(5, 7, nodes, nodes * 0.95, nodes * 1.02, nodes * 1.05)
        lsc = pipeline.module_by_id("lens_shading_correction")
        lsc.set_mesh(mesh)
        lsc.parameters["mode"] = "Mesh Model"
        roi = ImageROI(40, 30, 100, 80)
        full = pipeline.process(source.image, "bayer", source.metadata)
        partial = pipeline.process(source.image, "bayer", source.metadata, roi=roi)
        ys, xs = roi.slices()
        for full_stage, partial_stage in zip(full, partial):
            np.testing.assert_allclose(
                full_stage.image[ys, xs], partial_stage.image, atol=1e-6
            )

    def test_invalid_mesh_rejected(self):
        mesh = constant_mesh()
        mesh.r[0, 0] = np.nan
        with self.assertRaises(ISPError):
            mesh.validate()

    def test_mesh_json_csv_npz_round_trip(self):
        mesh = constant_mesh(values=(1.1, 1.2, 1.3, 1.4))
        with tempfile.TemporaryDirectory() as directory:
            for suffix in (".json", ".csv", ".npz", ".npy"):
                path = Path(directory) / f"mesh{suffix}"
                save_lsc_mesh(str(path), mesh)
                restored = load_lsc_mesh(str(path))
                for name in mesh.channels():
                    np.testing.assert_allclose(
                        restored.channels()[name], mesh.channels()[name]
                    )

    def test_lsc_gain_map_cache_hits_on_second_use(self):
        source = synthetic_bayer(160, 120)
        pipeline = ISPPipeline()
        module = pipeline.module_by_id("lens_shading_correction")
        module.set_mesh(constant_mesh())
        module.parameters["mode"] = "Mesh Model"
        first = module.process(source.image, "bayer", source.metadata)
        second = module.process(source.image, "bayer", source.metadata)
        self.assertIn(first[2]["Gain Map Cache"], {"Hit", "Miss"})
        self.assertEqual(second[2]["Gain Map Cache"], "Hit")

    def test_flat_field_mesh_improves_uniformity(self):
        height, width = 240, 320
        yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
        radius2 = ((xx - width / 2) / (width / 2)) ** 2 + ((yy - height / 2) / (height / 2)) ** 2
        flat = np.clip(0.8 * (1 - 0.28 * radius2), 0.18, 0.8)
        metadata = RawMetadata(
            width=width, height=height, black_level=[0] * 4, white_level=1
        )
        mesh, diagnostics, _ = generate_lsc_mesh(
            flat, metadata, rows=9, cols=11, smoothing=0.4
        )
        self.assertLess(
            diagnostics["mean_cv_after"], diagnostics["mean_cv_before"] * 0.3
        )
        self.assertEqual((mesh.rows, mesh.cols), (9, 11))


class AWBAETests(unittest.TestCase):
    def setUp(self):
        self.metadata = RawMetadata(
            width=80, height=60, black_level=[0] * 4, white_level=1
        )

    def test_roi_neutral_awb_estimates_four_gains(self):
        image = np.zeros((60, 80), np.float32)
        values = {"R": 0.4, "Gr": 0.8, "Gb": 0.8, "B": 0.2}
        for name, (y, x) in channel_positions("RGGB").items():
            image[y::2, x::2] = values[name]
        result = estimate_awb(image, self.metadata, "ROI Neutral")
        self.assertAlmostEqual(result.r_gain, 2.0, places=5)
        self.assertAlmostEqual(result.gr_gain, 1.0, places=5)
        self.assertAlmostEqual(result.gb_gain, 1.0, places=5)
        self.assertAlmostEqual(result.b_gain, 4.0, places=5)

    def test_awb_gain_limit_and_low_colored_scene_confidence(self):
        image = np.zeros((60, 80), np.float32)
        values = {"R": 0.7, "Gr": 0.5, "Gb": 0.5, "B": 0.03}
        for name, (y, x) in channel_positions("RGGB").items():
            image[y::2, x::2] = values[name]
        result = estimate_awb(image, self.metadata, "Gray World", gain_limit=3)
        self.assertEqual(result.b_gain, 3.0)
        self.assertLess(result.confidence, 0.4)
        self.assertTrue(result.diagnostics["gain_limited"])

    def test_ae_percentile_and_gain_limit(self):
        image = np.full((40, 50, 3), 0.1, np.float32)
        result = estimate_exposure(
            image, "rgb", self.metadata, "Percentile",
            target_level=0.5, maximum_gain=3,
        )
        self.assertAlmostEqual(result.current_level, 0.1, places=5)
        self.assertEqual(result.suggested_gain, 3.0)

    def test_ae_highlight_protection_limits_clipping(self):
        image = np.full((100, 100, 3), 0.2, np.float32)
        image[:10] = 0.95
        result = estimate_exposure(
            image, "rgb", self.metadata, "Highlight Protected",
            target_level=0.6, maximum_allowed_clipping=0.01,
        )
        self.assertTrue(result.diagnostics["highlight_limited"])
        self.assertLessEqual(result.predicted_clipped_ratio, 0.011)


class ColorCalibrationTests(unittest.TestCase):
    def test_colorchecker_reference_has_24_linear_patches(self):
        names, rgb = colorchecker_reference()
        self.assertEqual(len(names), 24)
        self.assertEqual(rgb.shape, (24, 3))

    def test_grid_and_sampling_return_24_patches(self):
        polygons = generate_colorchecker_grid(
            [(10, 10), (310, 20), (300, 210), (20, 200)]
        )
        self.assertEqual(len(polygons), 24)
        references = np.linspace(0.08, 0.85, 72, dtype=np.float32).reshape(24, 3)
        image = np.zeros((220, 320, 3), np.float32)
        for polygon, color in zip(polygons, references):
            cv2.fillConvexPoly(
                image,
                np.round(np.asarray(polygon)).astype(np.int32),
                tuple(map(float, color)),
            )
        patches = sample_colorchecker(
            image, polygons, references, [f"P{i + 1}" for i in range(24)]
        )
        self.assertEqual(len(patches), 24)
        np.testing.assert_allclose(
            np.stack([patch.measured_rgb for patch in patches]),
            references,
            atol=1e-5,
        )

    def test_known_matrix_and_offset_are_recovered(self):
        rng = np.random.default_rng(8)
        measured = rng.uniform(0.08, 0.75, (24, 3))
        matrix = np.array([
            [1.15, -0.08, -0.02],
            [-0.04, 1.10, -0.03],
            [0.01, -0.12, 1.18],
        ])
        offset = np.array([0.01, -0.005, 0.02])
        reference = apply_ccm(measured, matrix, offset)
        result = solve_ccm(measured, reference, include_offset=True)
        np.testing.assert_allclose(result.matrix, matrix, atol=1e-5)
        np.testing.assert_allclose(result.offset, offset, atol=1e-5)
        self.assertLess(result.delta_e_after["mean"], result.delta_e_before["mean"])
        self.assertLess(
            result.diagnostics["delta_e76_after"]["mean"],
            result.diagnostics["delta_e76_before"]["mean"],
        )

    def test_ridge_solver_handles_weighted_samples(self):
        rng = np.random.default_rng(4)
        measured = rng.uniform(0.1, 0.8, (24, 3))
        reference = measured @ np.array([
            [1.05, -0.02, 0.01],
            [0.01, 0.98, 0.02],
            [-0.01, 0.03, 1.04],
        ]).T
        result = solve_ccm(
            measured, reference, ridge=1e-3,
            weights=np.linspace(1, 2, 24), white_constraint=True,
        )
        self.assertTrue(np.all(np.isfinite(result.matrix)))
        self.assertGreater(result.condition_number, 0)


class VectorAndConfigTests(unittest.TestCase):
    def test_vectorscope_output_and_gray_center(self):
        image = np.full((60, 80, 3), 0.5, np.float32)
        result = compute_vectorscope(
            image, "rgb", RawMetadata(), mode="YCbCr", size=128
        )
        self.assertEqual(result.shape, (128, 128, 3))
        self.assertGreaterEqual(float(result.min()), 0)
        self.assertLessEqual(float(result.max()), 1)
        x, y, center = vectorscope_coordinates(np.array([[0.5, 0.5, 0.5]]))
        self.assertAlmostEqual(float(x[0]), center[0], places=5)
        self.assertAlmostEqual(float(y[0]), center[1], places=5)

    def test_primary_vectorscope_directions_are_distinct(self):
        colors = np.eye(3, dtype=np.float32)
        x, y, _ = vectorscope_coordinates(colors)
        points = np.round(np.column_stack([x, y]), 4)
        self.assertEqual(len(np.unique(points, axis=0)), 3)

    def test_v2_config_migrates_to_v3(self):
        migrated = migrate_config({
            "schema_version": 2,
            "tool_version": "0.2.0",
            "raw": {},
            "pipeline": [],
            "ui_state": {},
        })
        self.assertEqual(migrated["schema_version"], 4)
        self.assertIn("calibration", migrated)

    def test_calibration_session_round_trip(self):
        session = CalibrationSession(
            name="D65",
            sensor_name="Synthetic",
            lsc_mesh=constant_mesh(),
            awb_result=AWBResult(2, 1, 1, 1.5, 0.9, "Gray World", 100),
            ae_result=AEResult(0.2, 0.45, 2.25, 0, 0.01, "Median Luma"),
        )
        restored = CalibrationSession.from_dict(
            json.loads(json.dumps(session.to_dict()))
        )
        self.assertEqual(restored.name, "D65")
        self.assertEqual(restored.lsc_mesh.rows, session.lsc_mesh.rows)
        self.assertAlmostEqual(restored.awb_result.r_gain, 2)

    def test_v3_config_round_trip_includes_calibration(self):
        source = synthetic_bayer(160, 120)
        pipeline = ISPPipeline()
        session = CalibrationSession(
            name="Round trip",
            raw_metadata=source.metadata,
            lsc_mesh=constant_mesh(),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            save_config(
                str(path), source.metadata, pipeline, calibration=session
            )
            loaded = load_config(str(path))
            restored = CalibrationSession.from_dict(loaded["calibration"])
            self.assertEqual(loaded["schema_version"], 4)
            self.assertEqual(restored.name, "Round trip")
            self.assertIsNotNone(restored.lsc_mesh)

    def test_missing_external_mesh_degrades_with_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({
                "schema_version": 3,
                "raw": {},
                "pipeline": [],
                "calibration": {
                    "lsc_mesh": {"external_path": "missing_mesh.json"}
                },
                "ui_state": {},
            }), encoding="utf-8")
            loaded = load_config(str(path))
            self.assertIsNone(loaded["calibration"]["lsc_mesh"])
            self.assertTrue(loaded["_warnings"])

    def test_report_exports_json_csv_and_markdown(self):
        session = CalibrationSession(
            name="Report",
            sensor_name="Synthetic",
            lsc_mesh=constant_mesh(),
            awb_result=AWBResult(2, 1, 1, 1.5, 0.8, "Gray World", 100),
        )
        with tempfile.TemporaryDirectory() as directory:
            for suffix in (".json", ".csv", ".md"):
                path = Path(directory) / f"report{suffix}"
                export_calibration_report(str(path), session)
                self.assertTrue(path.exists())
                self.assertGreater(path.stat().st_size, 20)


if __name__ == "__main__":
    unittest.main()
