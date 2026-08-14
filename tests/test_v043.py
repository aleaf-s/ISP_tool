import copy
import tkinter as tk
import unittest

from isp_tool import __version__
from isp_tool.models import ParameterRecommendation
from isp_tool.pipeline import ISPPipeline
from isp_tool.ui.app import BASIC_PARAMETER_KEYS, ISPApplication
from isp_tool.ui.calibration_state import CalibrationUIState


class SimpleWorkspaceModelTests(unittest.TestCase):
    def test_every_pipeline_module_has_a_small_basic_parameter_set(self):
        pipeline = ISPPipeline()
        for module in pipeline.modules:
            basic = BASIC_PARAMETER_KEYS[module.module_id]
            self.assertTrue(basic)
            self.assertTrue(basic.issubset(module.specs))
            self.assertLessEqual(len(basic), 10)


class HiddenTkSimpleWorkspaceTests(unittest.TestCase):
    def _root(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        root.withdraw()
        return root

    def test_workspace_stays_simple_when_old_code_requests_expert_mode(self):
        root = self._root()
        app = ISPApplication(root)
        try:
            root.update()
            self.assertTrue(app.analysis_collapsed)
            self.assertFalse(app.analysis_container.winfo_manager())
            self.assertFalse(app.stage_selector.winfo_manager())
            self.assertFalse(app.expert_diagnostics_label.winfo_manager())
            self.assertFalse(app.performance_status_label.winfo_manager())
            self.assertIsNotNone(app.advanced_params_button)
            self.assertFalse(app.advanced_params_frame.winfo_manager())

            app.expert_mode_var.set(True)
            app._apply_expert_mode()
            root.update_idletasks()
            self.assertFalse(app.expert_mode)
            self.assertFalse(app.expert_mode_var.get())
            self.assertFalse(app.stage_selector.winfo_manager())
            self.assertFalse(app.expert_diagnostics_label.winfo_manager())
            self.assertFalse(app.performance_status_label.winfo_manager())
        finally:
            if root.winfo_exists():
                app.close()

    def test_pipeline_selection_stays_highlighted_after_focus_and_refresh(self):
        root = self._root()
        app = ISPApplication(root)
        try:
            root.update()
            self.assertEqual(
                str(app.pipeline_list.cget("exportselection")), "0"
            )
            target = min(3, len(app.pipeline.modules) - 1)
            app.pipeline_list.selection_clear(0, "end")
            app.pipeline_list.selection_set(target)
            app._on_module_select()

            app._refresh_pipeline_list()
            root.update_idletasks()
            self.assertEqual(app.pipeline_list.curselection(), (target,))
            self.assertEqual(app.pipeline_list.index("active"), target)

            app.pipeline_list.selection_clear(0, "end")
            app._on_module_select()
            self.assertEqual(app.pipeline_list.curselection(), (target,))
        finally:
            if root.winfo_exists():
                app.close()

    def test_scope_drawer_and_auto_strip_are_contextual(self):
        root = self._root()
        app = ISPApplication(root)
        try:
            root.update()
            app._toggle_analysis_panel()
            self.assertFalse(app.analysis_collapsed)
            self.assertTrue(app.analysis_container.winfo_manager())
            app._toggle_analysis_panel()
            self.assertTrue(app.analysis_collapsed)
            self.assertFalse(app.analysis_container.winfo_manager())

            demosaic_index = next(
                index
                for index, module in enumerate(app.pipeline.modules)
                if module.module_id == "demosaic"
            )
            app.pipeline_list.selection_clear(0, "end")
            app.pipeline_list.selection_set(demosaic_index)
            app._on_module_select()
            self.assertFalse(app.auto_mode_frame.winfo_manager())
        finally:
            if root.winfo_exists():
                app.close()

    def test_calibration_uses_single_quick_correction_pane(self):
        root = self._root()
        app = ISPApplication(root)
        try:
            app.open_calibration_workspace()
            root.update()
            panel = app.calibration_workspace.auto_panel
            self.assertEqual(len(panel.workspace_paned.panes()), 1)
            self.assertFalse(hasattr(panel, "module_combo"))
            self.assertFalse(hasattr(panel, "view"))
            self.assertFalse(hasattr(panel, "advanced_section"))
            self.assertTrue(panel.analyze_button.winfo_manager())

            module = app.pipeline.module_by_id(
                "black_level_correction"
            )
            current = copy.deepcopy(module.parameters)
            suggested = copy.deepcopy(current)
            suggested["global_offset"] += 1.0
            panel.result = ParameterRecommendation(
                module_id="auto_blc",
                target_module_id="black_level_correction",
                current_parameters=current,
                suggested_parameters=suggested,
                measurements={},
                confidence=0.9,
            )
            machine = panel.states["BLC"]
            machine.start(current)
            machine.transition(CalibrationUIState.SUGGESTED)
            panel._update_action_states()
            self.assertEqual(
                str(panel.analyze_button["text"]),
                "矫正并应用",
            )
        finally:
            if root.winfo_exists():
                app.close()


class VersionTests(unittest.TestCase):
    def test_version_is_v043(self):
        self.assertGreaterEqual(
            tuple(map(int, __version__.split("."))), (0, 4, 3)
        )


if __name__ == "__main__":
    unittest.main()
