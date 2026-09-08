import time
import tkinter as tk
import unittest

import numpy as np

from isp_tool import __version__
from isp_tool.calibration.ccm_solver import apply_ccm, solve_ccm_from_patches
from isp_tool.calibration.colorchecker import (
    colorchecker_reference,
    generate_colorchecker_grid,
    sample_colorchecker,
)
from isp_tool.models import ColorCheckerPatch, ImageROI, ISPError


class ColorCheckerReferenceTests(unittest.TestCase):
    def test_non_d65_references_are_adapted_to_srgb_white(self):
        for illuminant in ("D50", "A"):
            with self.subTest(illuminant=illuminant):
                _names, references = colorchecker_reference(
                    illuminant=illuminant
                )
                neutral_row = references[18:24]
                self.assertLess(
                    float(np.max(np.ptp(neutral_row, axis=1))),
                    0.025,
                )

    def test_crossed_chart_corners_are_rejected(self):
        with self.assertRaises(ISPError):
            generate_colorchecker_grid(
                ((0, 0), (100, 100), (100, 0), (0, 100))
            )


class RobustPatchRefitTests(unittest.TestCase):
    def test_synthetic_chart_sampling_recovers_signed_ccm(self):
        import cv2

        names, reference = colorchecker_reference(illuminant="D65")
        expected = np.array([
            [1.18, -0.12, -0.06],
            [-0.08, 1.16, -0.08],
            [-0.05, -0.13, 1.18],
        ])
        measured = reference @ np.linalg.inv(expected).T
        image = np.zeros((400, 600, 3), np.float32)
        polygons = generate_colorchecker_grid(
            ((0, 0), (599, 0), (599, 399), (0, 399)),
            inner_scale=0.92,
        )
        for color, polygon in zip(measured, polygons):
            cv2.fillConvexPoly(
                image,
                np.rint(polygon).astype(np.int32),
                tuple(map(float, color)),
            )
        patches = sample_colorchecker(
            image, polygons, reference, names, statistic="Median"
        )

        result = solve_ccm_from_patches(
            patches, include_offset=False
        )

        np.testing.assert_allclose(result.matrix, expected, atol=0.035)
        self.assertLess(result.delta_e_after["mean"], 1.0)
        self.assertTrue(result.diagnostics["safe_to_apply"])

    def test_one_gross_patch_is_rejected_and_refitted(self):
        rng = np.random.default_rng(437)
        measured = rng.uniform(0.08, 0.80, (24, 3))
        expected = np.array([
            [1.18, -0.12, -0.06],
            [-0.08, 1.16, -0.08],
            [-0.05, -0.13, 1.18],
        ])
        reference = apply_ccm(measured, expected)
        reference[7] = (1.2, 0.0, 0.0)
        patches = [
            ColorCheckerPatch(
                index + 1,
                f"P{index + 1}",
                [],
                measured[index],
                reference[index],
                diagnostics={
                    "valid": True,
                    "reference_index": index,
                    "quality_score": 1.0,
                },
            )
            for index in range(24)
        ]

        result = solve_ccm_from_patches(
            patches, include_offset=False
        )

        self.assertEqual(result.diagnostics["auto_rejected_patch_ids"], [8])
        self.assertIn(8, result.diagnostics["rejected_patch_ids"])
        self.assertLess(result.delta_e_after["mean"], 0.2)
        self.assertTrue(result.diagnostics["safe_to_apply"])


class HiddenTkCCMWorkflowTests(unittest.TestCase):
    def _root(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        root.withdraw()
        return root

    @staticmethod
    def _wait(root, condition, timeout=5.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            root.update()
            if condition():
                return
            time.sleep(0.01)
        raise AssertionError("condition timed out")

    def test_current_roi_is_the_actual_chart_sampling_source(self):
        from isp_tool.ui.app import ISPApplication

        root = self._root()
        app = ISPApplication(root)
        try:
            self._wait(root, lambda: bool(app.results))
            app.open_calibration_workspace()
            panel = app.calibration_workspace.auto_panel
            panel.select_module("CCM")
            app.roi = ImageROI(8, 6, 72, 48)
            # Twenty-four unrelated ROIs must not be mistaken for a chart grid
            # unless they carry explicit 4x6 grid provenance.
            app.rois = [ImageROI(0, 0, 4, 4) for _ in range(24)]
            app.roi_grid_bounds = None
            panel.use_roi_var.set(True)
            app.calibration_workspace.ccm_rotation_var.set(180)
            app.calibration_workspace.ccm_exclude_var.set("2")
            panel.ccm_statistic_var.set("Trimmed Mean")

            patches = panel._colorchecker_patches()

            self.assertEqual(len(patches), 24)
            self.assertEqual(
                patches[0].diagnostics["reference_index"], 23
            )
            self.assertFalse(patches[1].diagnostics["valid"])
            self.assertIn(
                "用户排除", patches[1].diagnostics["reasons"]
            )
            self.assertEqual(
                patches[0].diagnostics["statistic"], "Trimmed Mean"
            )
            points = np.asarray(app.calibration_polygons).reshape(-1, 2)
            self.assertGreaterEqual(float(points[:, 0].min()), app.roi.x)
            self.assertGreaterEqual(float(points[:, 1].min()), app.roi.y)
            self.assertLessEqual(float(points[:, 0].max()), app.roi.x2)
            self.assertLessEqual(float(points[:, 1].max()), app.roi.y2)
        finally:
            if root.winfo_exists():
                app.close()

    def test_ccm_has_explicit_calculate_and_apply_controls(self):
        from isp_tool.ui.app import ISPApplication

        root = self._root()
        app = ISPApplication(root)
        try:
            self._wait(root, lambda: bool(app.results))
            app.open_calibration_workspace()
            panel = app.calibration_workspace.auto_panel
            panel.select_module("CCM")
            root.update_idletasks()
            self.assertIn("CCM", panel.analyze_button.cget("text"))
            self.assertTrue(panel.ccm_setup_frame.winfo_manager())
            self.assertEqual(
                str(panel.ccm_apply_button.cget("state")), "disabled"
            )
        finally:
            if root.winfo_exists():
                app.close()


class VersionTests(unittest.TestCase):
    def test_version_is_at_least_v0437(self):
        self.assertGreaterEqual(
            tuple(map(int, __version__.split("."))),
            (0, 4, 37),
        )


if __name__ == "__main__":
    unittest.main()
