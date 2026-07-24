import copy
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from isp_tool.config import load_config, save_config
from isp_tool.models import ImageROI, ParameterRecommendation, RawMetadata
from isp_tool.pipeline import ISPPipeline
from isp_tool.ui.calibration_state import (
    CalibrationStateMachine,
    CalibrationUIState,
    InvalidCalibrationTransition,
)
from isp_tool.ui.widgets import (
    CalibrationFileItem,
    ROIItem,
    artifact_to_display_rgb,
    validate_file_metadata,
)


class CalibrationStateTests(unittest.TestCase):
    def test_legal_state_transitions_and_button_rules(self):
        machine = CalibrationStateMachine()
        self.assertTrue(machine.can_analyze)
        self.assertFalse(machine.can_preview)
        machine.start({"gain": 1.0})
        self.assertFalse(machine.can_analyze)
        machine.transition(CalibrationUIState.SUGGESTED)
        self.assertTrue(machine.can_preview)
        self.assertFalse(machine.can_apply)
        machine.transition(CalibrationUIState.PREVIEWING)
        self.assertTrue(machine.can_apply)
        self.assertTrue(machine.can_revert)
        machine.transition(CalibrationUIState.APPLIED)
        machine.transition(CalibrationUIState.STALE)
        self.assertTrue(machine.can_analyze)
        self.assertFalse(machine.can_apply)
        machine.start({"gain": 2.0})

    def test_illegal_state_transition_has_clear_error(self):
        machine = CalibrationStateMachine()
        with self.assertRaisesRegex(
            InvalidCalibrationTransition, "NOT_ANALYZED.*APPLIED"
        ):
            machine.transition(CalibrationUIState.APPLIED)
        machine.start({})
        machine.transition(CalibrationUIState.SUGGESTED)
        with self.assertRaises(InvalidCalibrationTransition):
            machine.transition(CalibrationUIState.RUNNING)

    def test_recommendation_becomes_stale_after_parameter_change(self):
        machine = CalibrationStateMachine()
        machine.start({"gain": 1.0, "enabled": True})
        machine.transition(CalibrationUIState.SUGGESTED)
        self.assertFalse(
            machine.mark_stale_if_changed({"gain": 1.0, "enabled": True})
        )
        self.assertTrue(
            machine.mark_stale_if_changed({"gain": 1.1, "enabled": True})
        )
        self.assertEqual(machine.state, CalibrationUIState.STALE)


class ReusableWidgetModelTests(unittest.TestCase):
    def test_file_list_metadata_validation(self):
        reference = RawMetadata(
            width=1920, height=1080, bit_depth=12,
            bayer_pattern="RGGB",
        )
        valid = CalibrationFileItem(
            "dark.raw", 1920, 1080, 12, "RGGB"
        )
        invalid = CalibrationFileItem(
            "flat.raw", 1920, 1080, 10, "BGGR"
        )
        self.assertEqual(validate_file_metadata(valid, reference), "Valid")
        result = validate_file_metadata(invalid, reference)
        self.assertIn("Bit depth", result)
        self.assertIn("Bayer", result)

    def test_roi_status_exposes_acceptance_and_rejection_reason(self):
        roi = ImageROI(2, 4, 20, 18)
        self.assertEqual(ROIItem(roi, accepted=True).status, "Accepted")
        rejected = ROIItem(roi, accepted=False, reason="Texture too high")
        self.assertEqual(rejected.status_tag, "rejected")
        self.assertIn("Texture too high", rejected.status)

    def test_artifact_conversion_handles_gray_mask_and_rgb(self):
        gray = np.linspace(0, 1, 12, dtype=np.float32).reshape(3, 4)
        gray_rgb = artifact_to_display_rgb("Gain Map", gray)
        self.assertEqual(gray_rgb.shape, (3, 4, 3))
        mask = np.zeros((3, 4), np.uint8)
        mask[1, 2] = 1
        hot = artifact_to_display_rgb("Hot Pixel Mask", mask)
        np.testing.assert_allclose(hot[1, 2], (1.0, 0.1, 0.05))
        rgb = np.zeros((3, 4, 3), np.float32)
        rgb[:, :, 1] = 0.5
        np.testing.assert_allclose(
            artifact_to_display_rgb("RGB Preview", rgb), rgb
        )


class UIStatePersistenceTests(unittest.TestCase):
    def test_v4_ui_state_round_trip_preserves_v041_fields(self):
        metadata = RawMetadata(width=64, height=48)
        pipeline = ISPPipeline()
        ui_state = {
            "window_geometry": "1366x768+10+20",
            "main_sashes": [230, 1010],
            "analysis_collapsed": True,
            "zoom": 1.75,
            "fit_mode": False,
            "last_directory": "D:/RAW",
            "calibration": {
                "selected_module": "Noise Profile",
                "sections": {
                    "basic": True,
                    "data": False,
                    "advanced": True,
                },
                "artifact_mode": "Overlay",
                "artifact_opacity": 0.42,
                "methods": {"Tone": "Natural"},
            },
        }
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "ui_state.json"
            save_config(
                str(path), metadata, pipeline, ui_state=ui_state
            )
            restored = load_config(str(path))["ui_state"]
        self.assertEqual(restored, ui_state)


class HiddenTkSmokeTests(unittest.TestCase):
    def _root(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        root.withdraw()
        return root

    def test_hidden_application_workspace_preview_revert_and_close(self):
        from isp_tool.ui.app import ISPApplication

        root = self._root()
        app = ISPApplication(root)
        try:
            root.update()
            app.open_calibration_workspace()
            root.update()
            panel = app.calibration_workspace.auto_panel
            self.assertEqual(len(panel.MODULES), 9)
            self.assertEqual(
                str(panel.preview_button["state"]), "disabled"
            )

            module = app.pipeline.module_by_id("black_level_correction")
            original = copy.deepcopy(module.parameters)
            suggested = copy.deepcopy(original)
            key = next(iter(suggested))
            suggested[key] = float(suggested[key]) + 1.0
            recommendation = ParameterRecommendation(
                module_id="auto_blc",
                target_module_id="black_level_correction",
                current_parameters=copy.deepcopy(original),
                suggested_parameters=suggested,
                measurements={},
                confidence=0.9,
            )
            panel.result = recommendation
            machine = panel.states["BLC"]
            machine.start(original)
            machine.transition(CalibrationUIState.SUGGESTED)
            machine.parameter_snapshot = copy.deepcopy(original)
            panel._update_action_states()
            panel.preview()
            root.update()
            self.assertTrue(panel.controller.has_preview)
            self.assertTrue(panel.preview_banner.winfo_manager())
            self.assertEqual(machine.state, CalibrationUIState.PREVIEWING)
            self.assertEqual(str(panel.apply_button["state"]), "normal")
            self.assertEqual(str(panel.revert_button["state"]), "normal")

            panel.select_module("DPC")
            root.update()
            self.assertFalse(panel.controller.has_preview)
            self.assertEqual(module.parameters, original)
            self.assertEqual(
                panel.states["BLC"].state,
                CalibrationUIState.SUGGESTED,
            )
            self.assertEqual(str(panel.apply_button["state"]), "disabled")
        finally:
            if root.winfo_exists():
                app.close()

    def test_loading_new_image_reverts_active_preview(self):
        from isp_tool.ui.app import ISPApplication

        root = self._root()
        app = ISPApplication(root)
        try:
            root.update()
            app.open_calibration_workspace()
            root.update()
            panel = app.calibration_workspace.auto_panel
            module = app.pipeline.module_by_id("black_level_correction")
            original = copy.deepcopy(module.parameters)
            suggested = copy.deepcopy(original)
            key = next(iter(suggested))
            suggested[key] = float(suggested[key]) + 1.0
            recommendation = ParameterRecommendation(
                module_id="auto_blc",
                target_module_id="black_level_correction",
                current_parameters=copy.deepcopy(original),
                suggested_parameters=suggested,
                measurements={},
                confidence=0.8,
            )
            panel.result = recommendation
            machine = panel.states["BLC"]
            machine.start(original)
            machine.transition(CalibrationUIState.SUGGESTED)
            machine.parameter_snapshot = copy.deepcopy(original)
            panel._update_action_states()
            panel.preview()
            self.assertTrue(panel.controller.has_preview)

            with tempfile.TemporaryDirectory() as folder:
                image_path = Path(folder) / "next.png"
                Image.new("RGB", (48, 32), (80, 100, 120)).save(image_path)
                with patch(
                    "isp_tool.ui.app.filedialog.askopenfilename",
                    return_value=str(image_path),
                ):
                    app.open_file()
            self.assertFalse(panel.controller.has_preview)
            self.assertNotEqual(module.parameters[key], suggested[key])
            self.assertEqual(
                module.parameters["r"],
                app.loaded.metadata.black_level[0],
            )
            self.assertIsNone(app.calibration_workspace)
        finally:
            if root.winfo_exists():
                app.close()


if __name__ == "__main__":
    unittest.main()
