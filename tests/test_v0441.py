import copy
import time
import tkinter as tk
import unittest
from unittest import mock

import numpy as np

from isp_tool.calibration.ccm_analysis import evaluate_matrix, lab_errors
from isp_tool.calibration.colorchecker import colorchecker_reference
from isp_tool.models import ColorCheckerPatch, ParameterRecommendation


def chart_measurements():
    names, reference = colorchecker_reference()
    patches = [ColorCheckerPatch(
        patch_id=i + 1, name=name, polygon=[], measured_rgb=(rgb * 0.8).tolist(),
        reference_rgb=rgb.tolist(), diagnostics={"valid": True},
    ) for i, (name, rgb) in enumerate(zip(names, reference))]
    return evaluate_matrix({"patches": [p.to_dict() for p in patches]}, np.eye(3), 1.25)


class CCMMeasurementTests(unittest.TestCase):
    def test_signed_lab_differences_and_ab_distance(self):
        errors = lab_errors([52, 13, 24], [50, 10, 20])
        self.assertAlmostEqual(float(errors["deab"]), np.sqrt(29))
        self.assertAlmostEqual(float(errors["dcab"]), 5)
        self.assertEqual([float(errors[k]) for k in ("dl", "da", "db")], [2, 3, 4])
        self.assertTrue(np.isnan(lab_errors([50, 0, 0], [50, 0, 0])["dh"]))

    def test_manual_matrix_evaluated_exactly_without_mutating_source(self):
        original = chart_measurements()
        snapshot = copy.deepcopy(original)
        matrix = np.array([[1.1, -.07, -.03], [-.02, 1.06, -.04], [-.03, -.05, 1.08]])
        result = evaluate_matrix(original, matrix, 1.25)
        self.assertEqual(original, snapshot)
        np.testing.assert_array_equal(result["matrix"], matrix)
        for patch in result["patches"]:
            np.testing.assert_allclose(patch["diagnostics"]["corrected_rgb"],
                                       matrix @ (np.array(patch["measured_rgb"]) * 1.25))
        self.assertGreater(result["delta_e_after"]["mean"], original["delta_e_after"]["mean"])
        for bad in (np.zeros((3, 3)), np.eye(3) * np.nan, np.eye(3) * 5):
            with self.assertRaises(ValueError):
                evaluate_matrix(original, bad)


class CCMInteractionTests(unittest.TestCase):
    def setUp(self):
        from isp_tool.ui.theme import configure_theme
        self.root = tk.Tk()
        self.root.withdraw()
        configure_theme(self.root, 1.25)
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)

    def tearDown(self):
        try:
            if self.root.winfo_exists():
                self.root.destroy()
        except tk.TclError:
            pass
        self.assertFalse(self.errors, str(self.errors))

    def pump(self, seconds=.15):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.root.update()
            time.sleep(.005)

    def test_selection_feedback_settles_and_background_is_cached(self):
        from isp_tool.ui.ccm_analysis_window import CCMAnalysisWindow
        selected = []
        window = CCMAnalysisWindow(self.root)
        window.on_patch_selected = lambda n: (selected.append(n), window.focus_patch(n))
        measurements = chart_measurements()
        window.set_result(measurements)
        window.deiconify()
        self.pump()
        window._draw_ab()
        photo = window._background_photo
        for _ in range(40):
            window.focus_patch(1, notify=True)
        self.pump()
        self.assertEqual(selected, [1])
        self.assertIs(window._background_photo, photo)
        self.assertIsNone(window._draw_after_id)
        self.assertEqual(tuple(window.tree["columns"]), ("id", "deab", "dcab", "dl", "dc", "dh", "da", "db"))
        self.assertEqual(len(window._plot_points()), 48)
        with mock.patch.object(window.tree, "delete") as delete:
            for _ in range(10):
                window.withdraw()
                window.set_result(measurements)
                window.deiconify()
            self.assertFalse(delete.called)
        self.pump()
        self.assertEqual(selected, [1])

    def test_editor_applies_exact_matrix_and_analysis_open_does_not_reprocess(self):
        from isp_tool.ui.app import ISPApplication
        from isp_tool.ui.calibration_state import CalibrationUIState
        app = ISPApplication(self.root)
        try:
            deadline = time.monotonic() + 8
            while not app.results and time.monotonic() < deadline:
                self.pump(.05)
            self.assertTrue(app.results)
            app.open_calibration_workspace()
            panel = app.calibration_workspace.auto_panel
            panel.select_module("CCM")
            module = app.pipeline.module_by_id("color_correction_matrix")
            measurements = chart_measurements()
            panel.result = ParameterRecommendation(
                module_id="colorchecker_ccm", target_module_id=module.module_id,
                current_parameters=copy.deepcopy(module.parameters),
                suggested_parameters=copy.deepcopy(module.parameters),
                measurements=measurements, confidence=1.0,
            )
            panel.states["CCM"].state = CalibrationUIState.SUGGESTED
            panel._show_ccm_result(panel.result)
            panel._update_action_states()
            matrix = np.array([[1.1, -.07, -.03], [-.02, 1.06, -.04], [-.03, -.05, 1.08]])
            for v, value in zip(panel.ccm_matrix_vars, matrix.ravel()):
                v.set(str(value))
            patches = [ColorCheckerPatch.from_dict(p) for p in measurements["patches"]]
            with mock.patch.object(panel, "_colorchecker_patches", return_value=patches):
                panel._correct_edited_ccm()
            self.assertEqual(panel.states["CCM"].state, CalibrationUIState.APPLIED)
            np.testing.assert_allclose(module.matrix(), matrix)
            self.assertEqual(module.parameters["input_gain"], 1.25)
            self.assertTrue(panel.result.applied)
            self.assertFalse(panel.ccm_patch_tree.winfo_manager())
            self.assertFalse(panel.ccm_statistic_combo.winfo_manager())
            self.assertFalse(panel.ccm_offset_check.winfo_manager())
            self.pump(.5)
            parameters = copy.deepcopy(module.parameters)
            with mock.patch.object(app, "schedule_process") as process:
                for _ in range(10):
                    panel.open_ccm_analysis()
                    panel.ccm_analysis_window.focus_patch(1, notify=True)
                self.pump()
                self.assertFalse(process.called)
            self.assertEqual(module.parameters, parameters)
            self.assertEqual(panel.states["CCM"].state, CalibrationUIState.APPLIED)
            # Retain a regression for the original second-table feedback loop.
            panel.ccm_patch_tree.insert("", "end", iid="patch-1", values=(1,))
            events = []
            def selected(event):
                events.append(1)
                if len(events) < 10:
                    panel._ccm_patch_tree_selected(event)
            panel.ccm_patch_tree.bind("<<TreeviewSelect>>", selected)
            panel.focus_ccm_patch(1)
            self.pump()
            self.assertEqual(len(events), 1)
            with mock.patch.object(panel, "analyze", return_value=True) as analyze:
                self.assertTrue(panel.calculate_ccm())
                analyze.assert_called_once()
                self.assertEqual(panel.states["CCM"].state, CalibrationUIState.STALE)
            panel.select_module("AWB")
            self.assertTrue(panel.method_combo.winfo_manager())
            panel.select_module("CCM")
            self.assertFalse(panel.method_combo.winfo_manager())
            self.assertFalse(panel.source_label.winfo_manager())
        finally:
            app.close()


if __name__ == "__main__":
    unittest.main()
