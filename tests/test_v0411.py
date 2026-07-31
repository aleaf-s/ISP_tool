import time
import tkinter as tk
import unittest
from types import SimpleNamespace

from isp_tool import __version__
from isp_tool.pipeline import ISPPipeline
from isp_tool.ui.app import ISPApplication
from isp_tool.ui.calibration_state import CalibrationUIState


class FocusedPipelineTests(unittest.TestCase):
    def test_pipeline_contains_only_quick_correction_modules(self):
        self.assertEqual(
            [module.module_id for module in ISPPipeline().modules],
            [
                "black_level_correction",
                "lens_shading_correction",
                "white_balance",
                "demosaic",
                "color_correction_matrix",
            ],
        )


class HiddenTkQuickCorrectionTests(unittest.TestCase):
    def _app(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        root.withdraw()
        app = ISPApplication(root)
        self._wait(
            root,
            lambda: len(app.results) == len(app.pipeline.modules) + 1,
        )
        return root, app

    def _wait(self, root, condition, timeout=8.0):
        deadline = time.time() + timeout
        while not condition() and time.time() < deadline:
            root.update()
            time.sleep(0.01)
        self.assertTrue(condition())

    def test_auto_calibration_is_a_single_focused_pane(self):
        root, app = self._app()
        try:
            app.open_calibration_workspace()
            root.update()
            panel = app.calibration_workspace.auto_panel
            self.assertEqual(len(panel.workspace_paned.panes()), 1)
            self.assertEqual(
                panel.MODULES,
                ("BLC", "LSC", "AWB", "AE", "CCM"),
            )
            self.assertFalse(hasattr(panel, "view"))
            self.assertFalse(hasattr(panel, "advanced_section"))
            self.assertFalse(hasattr(panel, "preview_button"))
            self.assertEqual(
                str(panel.analyze_button["text"]),
                "矫正并应用",
            )
            self.assertFalse(hasattr(app, "module_brush_menu"))
            self.assertFalse(hasattr(app, "auto_more_menu"))
        finally:
            if root.winfo_exists():
                app.close()

    def test_compare_divider_has_priority_over_roi_drawing(self):
        root, app = self._app()
        try:
            app.stage_combo.current(len(app.results) - 1)
            app.compare_var.set(True)
            app.roi_mode_var.set(True)
            app.render_current(schedule_analysis=False)
            root.update()
            origin_x, origin_y, zoom, width, height = (
                app.display_transform
            )
            divider_x = int(
                origin_x + width * app.compare_position * zoom
            )
            divider_y = int(origin_y + height * zoom * 0.5)
            original_rois = list(app.rois)
            app._on_left_press(
                SimpleNamespace(x=divider_x, y=divider_y)
            )
            self.assertTrue(app.compare_dragging)
            self.assertIsNone(app.roi_drag_start)
            app._on_left_drag(
                SimpleNamespace(x=divider_x + 40, y=divider_y)
            )
            app._on_left_release(
                SimpleNamespace(x=divider_x + 40, y=divider_y)
            )
            self.assertFalse(app.compare_dragging)
            self.assertEqual(app.rois, original_rois)
        finally:
            if root.winfo_exists():
                app.close()

    def test_awb_one_click_action_analyzes_and_applies(self):
        root, app = self._app()
        try:
            app.open_calibration_workspace()
            root.update()
            panel = app.calibration_workspace.auto_panel
            panel.select_module("AWB")
            panel.awb_region_var.set("Full Image")
            panel.correct_and_apply_current()
            self._wait(
                root,
                lambda: (
                    panel.states["AWB"].state
                    == CalibrationUIState.APPLIED
                ),
            )
            self.assertTrue(panel.result.applied)
            self.assertIsNotNone(app.calibration_session.awb_result)
            self.assertIn("已矫正并应用", str(panel.message["text"]))
        finally:
            if root.winfo_exists():
                app.close()


class VersionTests(unittest.TestCase):
    def test_version_is_v0411(self):
        self.assertGreaterEqual(
            tuple(map(int, __version__.split("."))),
            (0, 4, 11),
        )


if __name__ == "__main__":
    unittest.main()
