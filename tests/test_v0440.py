import time
import tkinter as tk
import unittest
from unittest import mock

import numpy as np

from isp_tool import __version__
from isp_tool.calibration.ccm_solver import (
    estimate_global_exposure_gain,
    solve_ccm,
)
from isp_tool.calibration.colorchecker import colorchecker_reference
from isp_tool.models import RawMetadata
from isp_tool.modules import ColorCorrectionMatrix
from isp_tool.ui.theme import FONTS, configure_theme


class CCMChromaticityFitTests(unittest.TestCase):
    def test_global_exposure_is_estimated_separately_from_ccm(self):
        _names, reference = colorchecker_reference()
        gain, diagnostics = estimate_global_exposure_gain(
            reference * 0.32, reference
        )

        self.assertAlmostEqual(gain, 3.125, delta=0.03)
        self.assertTrue(diagnostics["used_neutral_patches"])
        self.assertGreaterEqual(diagnostics["sample_count"], 3)

    def test_solver_optimises_ab_after_exposure_match(self):
        _names, reference = colorchecker_reference()
        expected = np.array([
            [1.65, -0.40, -0.25],
            [-0.18, 1.42, -0.24],
            [-0.10, -0.32, 1.42],
        ])
        measured = (reference @ np.linalg.inv(expected).T) * 0.40

        result = solve_ccm(
            measured,
            reference,
            include_offset=False,
            ridge=0.01,
            white_constraint=True,
            row_sum_regularization=0.20,
            perceptual_weight=0.8,
            structure_prior=True,
            lightness_weight=0.0,
            normalize_exposure=True,
        )

        self.assertAlmostEqual(
            result.diagnostics["pre_ccm_exposure_gain"], 2.5, delta=0.04
        )
        self.assertEqual(
            result.diagnostics["optimisation_target"],
            "CIE Lab a*b* (L* guard only)",
        )
        self.assertLess(
            result.diagnostics["delta_lch_after"]["delta_c"]["mean_abs"],
            0.4,
        )
        self.assertLess(
            result.diagnostics["delta_lch_after"]["delta_h"]["mean_abs"],
            0.4,
        )
        self.assertLess(result.delta_e_after["mean"], 0.8)

    def test_ccm_module_applies_pre_ccm_exposure_as_separate_scalar(self):
        module = ColorCorrectionMatrix()
        module.parameters["input_gain"] = 2.0
        source = np.full((3, 4, 3), 0.2, np.float32)

        output = module.process(source, "rgb", RawMetadata())[0]

        np.testing.assert_allclose(output, 0.4, atol=1e-7)


class CCMResponsiveWindowTests(unittest.TestCase):
    def _root(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        configure_theme(root, 1.25)
        root.geometry("360x240")
        root.update()
        return root

    def test_analysis_table_row_height_and_panes_follow_dpi(self):
        from tkinter import ttk

        from isp_tool.ui.ccm_analysis_window import CCMAnalysisWindow

        root = self._root()
        window = CCMAnalysisWindow(root)
        try:
            deadline = time.time() + 1.0
            while time.time() < deadline:
                root.update()
                if window.ab_canvas.winfo_width() > 400:
                    break
                time.sleep(0.01)
            style = ttk.Style(root)
            row_height = int(style.lookup("CCMAnalysis.Treeview", "rowheight"))
            font_height = int(root.tk.call(
                "font", "metrics", FONTS["body"], "-linespace"
            ))
            self.assertGreaterEqual(row_height, font_height + 8)
            self.assertGreater(window.ab_canvas.winfo_width(), 400)
        finally:
            window.destroy()
            root.destroy()

    def test_thumbnail_applies_ccm_only_after_downsampling(self):
        from isp_tool.ui.auto_calibration_panel import AutoCalibrationPanel

        root = self._root()
        panel = object.__new__(AutoCalibrationPanel)
        panel.app = type("App", (), {"preview_exposure_ev": 0.0})()
        source = np.zeros((900, 1400, 3), np.float32)
        seen_shapes = []

        def fake_apply(values, matrix, offset):
            seen_shapes.append(values.shape)
            return values

        try:
            with mock.patch(
                "isp_tool.ui.auto_calibration_panel.apply_ccm",
                side_effect=fake_apply,
            ):
                photo = panel._thumbnail_photo(
                    source, matrix=np.eye(3), offset=np.zeros(3), input_gain=2.0
                )
            self.assertIsNotNone(photo)
            self.assertEqual(len(seen_shapes), 1)
            self.assertLessEqual(seen_shapes[0][0], 110)
            self.assertLessEqual(seen_shapes[0][1], 170)
        finally:
            root.destroy()


class VersionTests(unittest.TestCase):
    def test_version_is_at_least_v0440(self):
        self.assertGreaterEqual(
            tuple(map(int, __version__.split("."))), (0, 4, 40)
        )


if __name__ == "__main__":
    unittest.main()
