import time
import tkinter as tk
import unittest

import numpy as np

from isp_tool import __version__
from isp_tool.calibration.ccm_solver import solve_ccm
from isp_tool.calibration.colorchecker import colorchecker_reference
from isp_tool.calibration.delta_e import delta_lch_components
from isp_tool.ui.controllers import (
    CanvasGestureCoordinator,
    GESTURE_COLORCHECKER,
    GESTURE_COMPARE,
)


class LCHAndCCMSolverTests(unittest.TestCase):
    def test_hue_difference_wraps_at_zero_degrees(self):
        chroma = 30.0
        measured = np.array([[
            50.0,
            chroma * np.cos(np.radians(1.0)),
            chroma * np.sin(np.radians(1.0)),
        ]])
        reference = np.array([[
            50.0,
            chroma * np.cos(np.radians(359.0)),
            chroma * np.sin(np.radians(359.0)),
        ]])

        result = delta_lch_components(measured, reference)

        self.assertAlmostEqual(float(result["delta_h_degrees"][0]), 2.0, places=6)
        self.assertTrue(bool(result["hue_defined"][0]))

    def test_exposure_mismatch_is_not_baked_into_ccm(self):
        _names, reference = colorchecker_reference()
        expected = np.array([
            [1.30, -0.20, -0.10],
            [-0.10, 1.25, -0.15],
            [-0.05, -0.25, 1.30],
        ])
        measured = reference @ np.linalg.inv(expected).T

        result = solve_ccm(
            measured * 0.75,
            reference,
            include_offset=False,
            ridge=0.015,
            white_constraint=True,
            row_sum_regularization=0.25,
            perceptual_weight=0.80,
            structure_prior=True,
            normalize_exposure=True,
        )

        np.testing.assert_allclose(result.matrix, expected, atol=0.035)
        self.assertAlmostEqual(
            float(result.diagnostics["exposure_normalization_gain"]),
            4.0 / 3.0,
            delta=0.03,
        )
        self.assertLess(
            result.diagnostics["delta_lch_after"]["delta_l"]["mean_abs"],
            0.5,
        )
        self.assertLess(
            result.diagnostics["delta_e_exposure_normalized_after"]["mean"],
            0.2,
        )

    def test_structure_prior_is_soft_and_lch_metrics_are_reported(self):
        rng = np.random.default_rng(439)
        measured = rng.uniform(0.08, 0.80, (24, 3))
        atypical = np.array([
            [0.90, 0.08, 0.02],
            [0.05, 0.90, 0.05],
            [0.02, 0.08, 0.90],
        ])
        reference = measured @ atypical.T

        result = solve_ccm(
            measured,
            reference,
            include_offset=False,
            ridge=0.0,
            row_sum_regularization=0.0,
            perceptual_weight=0.25,
            structure_prior=True,
            sign_regularization=0.001,
            normalize_exposure=False,
        )

        self.assertLess(float(np.min(np.diag(result.matrix))), 0.99)
        self.assertGreater(float(result.matrix[0, 1]), 0.04)
        self.assertIn("delta_lch_before", result.diagnostics)
        self.assertIn("delta_lch_after", result.diagnostics)


class ColorCheckerGestureTests(unittest.TestCase):
    def test_compare_divider_precedes_chart_and_chart_precedes_roi(self):
        coordinator = CanvasGestureCoordinator()
        gesture = coordinator.begin(
            (10, 10),
            compare_divider_hit=True,
            colorchecker_hit=True,
            roi_enabled=True,
            compare_enabled=True,
        )
        self.assertEqual(gesture, GESTURE_COMPARE)
        coordinator.finish()

        gesture = coordinator.begin(
            (10, 10),
            compare_divider_hit=False,
            colorchecker_hit=True,
            roi_enabled=True,
            compare_enabled=True,
        )
        self.assertEqual(gesture, GESTURE_COLORCHECKER)


class HiddenTkCCMInteractionTests(unittest.TestCase):
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

    def test_selecting_ccm_creates_editable_overlay_and_persists_it(self):
        from isp_tool.ui.app import ISPApplication

        root = self._root()
        app = ISPApplication(root)
        try:
            self._wait(root, lambda: bool(app.results))
            index = next(
                i for i, module in enumerate(app.pipeline.modules)
                if module.module_id == "color_correction_matrix"
            )
            app.pipeline_list.selection_clear(0, "end")
            app.pipeline_list.selection_set(index)
            app._on_module_select()
            root.update_idletasks()

            self.assertTrue(app.colorchecker_edit_active)
            self.assertEqual(len(app.colorchecker_corners), 4)
            self.assertEqual(len(app.calibration_polygons), 24)
            height, width = app.preview_image.shape[:2]
            center = np.mean(np.asarray(app.colorchecker_corners), axis=0)
            self.assertAlmostEqual(float(center[0]), width / 2.0, delta=2.0)
            self.assertAlmostEqual(float(center[1]), height / 2.0, delta=2.0)

            shifted = np.asarray(app.colorchecker_corners) + (3.0, 2.0)
            app._set_colorchecker_corners(shifted, source="corners")
            app._store_current_work_item()
            stored = app.work_items[0].colorchecker_state
            self.assertEqual(stored["source"], "corners")
            self.assertEqual(len(stored["corners"]), 4)
        finally:
            if root.winfo_exists():
                app.close()

    def test_analysis_window_links_table_and_ab_plot(self):
        from isp_tool.ui.ccm_analysis_window import CCMAnalysisWindow

        root = self._root()
        selected = []
        toggled = []
        window = CCMAnalysisWindow(
            root,
            on_patch_selected=selected.append,
            on_toggle_patch=toggled.append,
        )
        try:
            window.withdraw()
            measurements = {
                "valid_patch_count": 1,
                "condition_number": 2.0,
                "delta_e_before": {"mean": 5.0, "max": 5.0},
                "delta_e_after": {"mean": 1.0, "max": 1.0},
                "delta_lch_before": {
                    key: {"mean_abs": 3.0} for key in ("delta_l", "delta_c", "delta_h")
                },
                "delta_lch_after": {
                    key: {"mean_abs": 0.5} for key in ("delta_l", "delta_c", "delta_h")
                },
                "patches": [{
                    "patch_id": 1,
                    "diagnostics": {
                        "valid": True,
                        "input_lab": [50, 12, 18],
                        "reference_lab": [52, 10, 15],
                        "corrected_lab": [51, 10.5, 15.5],
                        "input_lch": [50, 21.63, 56.31],
                        "reference_lch": [52, 18.03, 56.31],
                        "corrected_lch": [51, 18.72, 55.89],
                        "delta_e_before": 5.0,
                        "delta_e_after": 1.0,
                        "delta_l_before": -2.0,
                        "delta_c_before": 3.6,
                        "delta_h_before": 0.0,
                        "delta_l_after": -1.0,
                        "delta_c_after": 0.7,
                        "delta_h_after": -0.1,
                        "inlier_ratio": 0.95,
                    },
                }],
            }
            window.set_result(measurements)
            root.update_idletasks()

            self.assertTrue(window.tree.exists("patch-1"))
            self.assertEqual(len(window._plot_points()), 2)
            window.focus_patch(1, notify=True)
            self.assertEqual(selected, [1])
            window._toggle_selected()
            self.assertEqual(toggled, [1])
        finally:
            if window.winfo_exists():
                window.destroy()
            if root.winfo_exists():
                root.destroy()


class VersionTests(unittest.TestCase):
    def test_version_is_at_least_v0439(self):
        self.assertGreaterEqual(
            tuple(map(int, __version__.split("."))),
            (0, 4, 39),
        )


if __name__ == "__main__":
    unittest.main()
