import copy
import time
import tkinter as tk
import unittest

import numpy as np

from isp_tool.calibration.ccm_solver import apply_ccm, solve_ccm
from isp_tool.calibration.colorchecker import (
    generate_colorchecker_grid,
    sample_colorchecker,
)
from isp_tool.models import ParameterRecommendation
from isp_tool.preview import encode_display_rgb
from isp_tool.ui.calibration_state import CalibrationUIState


class DisplayTransformTests(unittest.TestCase):
    def test_srgb_and_preview_ev_are_display_only_math(self):
        linear = np.array([[[0.18, 0.18, 0.18]]], np.float32)
        default = encode_display_rgb(linear)
        brighter = encode_display_rgb(linear, 1.0)
        self.assertAlmostEqual(float(default[0, 0, 0]), 0.461, places=3)
        self.assertGreater(float(brighter[0, 0, 0]), float(default[0, 0, 0]))
        np.testing.assert_array_equal(linear, np.full_like(linear, 0.18))


class RobustCCMTests(unittest.TestCase):
    def test_constrained_fit_improves_delta_e_and_is_stable(self):
        rng = np.random.default_rng(19)
        measured = rng.uniform(0.06, 0.82, (24, 3))
        expected = np.array([
            [1.12, -0.07, -0.03],
            [-0.04, 1.08, -0.02],
            [0.01, -0.10, 1.12],
        ])
        reference = apply_ccm(
            measured, expected, np.array([0.005, -0.003, 0.008])
        )
        result = solve_ccm(
            measured,
            reference,
            include_offset=True,
            ridge=0.015,
            white_constraint=True,
            row_sum_regularization=0.25,
            perceptual_weight=0.08,
        )
        self.assertLess(
            result.delta_e_after["mean"],
            result.delta_e_before["mean"] * 0.2,
        )
        self.assertTrue(np.all(np.diag(result.matrix) > 0))
        self.assertLess(result.condition_number, 10)
        np.testing.assert_allclose(
            result.matrix.sum(axis=1),
            np.ones(3),
            atol=0.08,
        )
        self.assertTrue(result.diagnostics["safe_to_apply"])

    def test_sampling_marks_clipped_patch_invalid(self):
        image = np.full((400, 600, 3), 0.25, np.float32)
        polygons = generate_colorchecker_grid(
            [(0, 0), (599, 0), (599, 399), (0, 399)]
        )
        first = np.asarray(polygons[0], np.int32)
        import cv2

        cv2.fillConvexPoly(image, first, (1.0, 1.0, 1.0))
        references = np.full((24, 3), 0.25, np.float32)
        patches = sample_colorchecker(
            image,
            polygons,
            references,
            [f"P{index + 1}" for index in range(24)],
        )
        self.assertFalse(patches[0].diagnostics["valid"])
        self.assertIn("过曝像素过多", patches[0].diagnostics["reasons"])
        self.assertTrue(patches[1].diagnostics["valid"])


class HiddenTkV0412Tests(unittest.TestCase):
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

    def test_manual_auto_are_embedded_and_preview_ev_preserves_data(self):
        from isp_tool.ui.app import ISPApplication

        root = self._root()
        app = ISPApplication(root)
        try:
            self._wait(root, lambda: bool(app.results))
            result_before = app.results[-1].image.copy()
            app.render_current()
            linear_before = app.display_linear_array.copy()
            top_levels_before = [
                child for child in root.winfo_children()
                if isinstance(child, tk.Toplevel)
            ]
            app.open_calibration_workspace()
            root.update()
            top_levels_after = [
                child for child in root.winfo_children()
                if isinstance(child, tk.Toplevel)
            ]
            self.assertEqual(top_levels_before, top_levels_after)
            self.assertEqual(app.adjustment_mode, "auto")
            self.assertTrue(app.auto_mode_frame.winfo_manager())
            self.assertFalse(app.manual_card.winfo_manager())
            app._adjust_preview_brightness(1.0)
            np.testing.assert_array_equal(
                app.results[-1].image, result_before
            )
            np.testing.assert_array_equal(
                app.display_linear_array, linear_before
            )
            self.assertEqual(app.preview_exposure_ev, 1.0)
            app._set_adjustment_mode("manual")
            self.assertTrue(app.manual_card.winfo_manager())
        finally:
            if root.winfo_exists():
                app.close()

    def test_unsafe_ccm_direct_result_is_not_applied(self):
        from isp_tool.ui.app import ISPApplication

        root = self._root()
        app = ISPApplication(root)
        try:
            app.open_calibration_workspace()
            root.update()
            panel = app.calibration_workspace.auto_panel
            panel.select_module("CCM")
            module = app.pipeline.module_by_id(
                "color_correction_matrix"
            )
            original = copy.deepcopy(module.parameters)
            machine = panel.states["CCM"]
            machine.start(original)
            panel.direct_apply_after_analysis = "CCM"
            result = ParameterRecommendation(
                module_id="colorchecker_ccm",
                target_module_id="color_correction_matrix",
                current_parameters=copy.deepcopy(original),
                suggested_parameters={
                    **copy.deepcopy(original),
                    "m00": 2.5,
                },
                measurements={
                    "safe_to_apply": False,
                    "rejection_reasons": ["平均 ΔE 未明显降低"],
                    "matrix": np.eye(3).tolist(),
                    "initial_matrix": np.eye(3).tolist(),
                    "offset": [0, 0, 0],
                    "delta_e_before": {"mean": 4, "max": 8},
                    "delta_e_initial": {"mean": 4, "max": 8},
                    "delta_e_after": {"mean": 4, "max": 8},
                    "row_sums": [1, 1, 1],
                    "condition_number": 1,
                    "patches": [],
                },
                confidence=0.0,
            )
            panel._analysis_finished((True, result))
            self.assertEqual(machine.state, CalibrationUIState.FAILED)
            self.assertEqual(module.parameters, original)
            self.assertFalse(result.applied)
        finally:
            if root.winfo_exists():
                app.close()


if __name__ == "__main__":
    unittest.main()
