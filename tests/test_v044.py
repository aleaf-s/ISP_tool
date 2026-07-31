import copy
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from isp_tool import __version__
from isp_tool.bayer import channel_positions
from isp_tool.calibration.awb import estimate_awb
from isp_tool.models import CalibrationSession, ImageROI, RawMetadata
from isp_tool.pipeline import ISPPipeline
from isp_tool.raw_io import synthetic_bayer
from isp_tool.roi_tools import generate_grid_rois
from isp_tool.ui.app import ISPApplication
from isp_tool.workspace import (
    ImageWorkItem,
    snapshot_for_image,
    transfer_module_settings,
)


class WorkspaceAndBrushTests(unittest.TestCase):
    def test_snapshot_is_per_image_and_transfer_copies_module_state(self):
        pipeline = ISPPipeline()
        first = synthetic_bayer(160, 120)
        second = synthetic_bayer(160, 120, "BGGR")
        second.metadata.black_level = [10, 11, 12, 13]
        source = snapshot_for_image(pipeline.snapshot(), first)
        target = snapshot_for_image(pipeline.snapshot(), second)
        blc = next(
            item
            for item in source
            if item["id"] == "black_level_correction"
        )
        blc["parameters"]["r"] = 77.0
        transferred = transfer_module_settings(
            source, target, ("black_level_correction",)
        )
        target_blc = next(
            item
            for item in transferred
            if item["id"] == "black_level_correction"
        )
        self.assertEqual(target_blc["parameters"]["r"], 77.0)
        blc["parameters"]["r"] = 88.0
        self.assertEqual(target_blc["parameters"]["r"], 77.0)


class MultiROITests(unittest.TestCase):
    def test_colorchecker_grid_generates_24_inset_boxes(self):
        bounds = ImageROI(20, 10, 600, 400)
        rois = generate_grid_rois(
            bounds, (480, 640), rows=4, cols=6,
            bayer_aligned=True,
        )
        self.assertEqual(len(rois), 24)
        for roi in rois:
            roi.validate((480, 640))
            self.assertGreaterEqual(roi.x, bounds.x)
            self.assertGreaterEqual(roi.y, bounds.y)
            self.assertLessEqual(roi.x2, bounds.x2)
            self.assertLessEqual(roi.y2, bounds.y2)
            self.assertEqual(roi.x % 2, 0)
            self.assertEqual(roi.y % 2, 0)


class RobustAWBTests(unittest.TestCase):
    def test_robust_neutral_rejects_large_colored_patch(self):
        height, width = 120, 160
        metadata = RawMetadata(
            width=width,
            height=height,
            black_level=[0] * 4,
            white_level=1,
        )
        image = np.zeros((height, width), np.float32)
        neutral = {"R": 0.35, "Gr": 0.70, "Gb": 0.70, "B": 0.28}
        for name, (y, x) in channel_positions("RGGB").items():
            image[y::2, x::2] = neutral[name]
        colored = {"R": 0.92, "Gr": 0.18, "Gb": 0.18, "B": 0.08}
        for name, (y, x) in channel_positions("RGGB").items():
            image[y:60:2, x:80:2] = colored[name]
        result = estimate_awb(image, metadata, "Robust Neutral")
        self.assertAlmostEqual(result.r_gain, 2.0, delta=0.08)
        self.assertAlmostEqual(result.b_gain, 2.5, delta=0.10)
        self.assertGreater(result.diagnostics["spatial_coverage"], 0.4)
        self.assertIn("AWB Selected Pixel Mask", result.artifacts)

    def test_dn_input_uses_four_independent_black_levels(self):
        height, width = 60, 80
        metadata = RawMetadata(
            width=width,
            height=height,
            black_level=[64, 68, 72, 76],
            white_level=4095,
        )
        normalized = {
            "R": 0.2, "Gr": 0.4, "Gb": 0.4, "B": 0.1
        }
        black = dict(zip(
            ("R", "Gr", "Gb", "B"), metadata.black_level
        ))
        image = np.zeros((height, width), np.float32)
        for name, (y, x) in channel_positions("RGGB").items():
            image[y::2, x::2] = (
                black[name]
                + normalized[name]
                * (metadata.white_level - black[name])
            )
        result = estimate_awb(
            image, metadata, "ROI Neutral"
        )
        self.assertAlmostEqual(result.r_gain, 2.0, places=4)
        self.assertAlmostEqual(result.b_gain, 4.0, places=4)


class HiddenTkV044Tests(unittest.TestCase):
    def _root(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        root.withdraw()
        return root

    def test_manual_ccm_preview_has_apply_and_revert(self):
        root = self._root()
        app = ISPApplication(root)
        try:
            ccm_index = next(
                index
                for index, module in enumerate(app.pipeline.modules)
                if module.module_id == "color_correction_matrix"
            )
            app.pipeline_list.selection_clear(0, "end")
            app.pipeline_list.selection_set(ccm_index)
            app._on_module_select()
            original = app.pipeline.modules[ccm_index].parameters["m00"]
            app.param_vars["m00"].set(str(original + 0.1))
            app._entry_commit("m00")
            root.update_idletasks()
            self.assertTrue(app.manual_apply_button.winfo_manager())
            self.assertTrue(app.manual_revert_button.winfo_manager())
            app.apply_manual_parameters()
            self.assertTrue(app.manual_apply_button.winfo_manager())
            self.assertEqual(
                str(app.manual_apply_button["state"]), "disabled"
            )
            self.assertAlmostEqual(
                app.pipeline.modules[ccm_index].parameters["m00"],
                original + 0.1,
            )
        finally:
            if root.winfo_exists():
                app.close()

    def test_auto_awb_measures_lsc_output_before_white_balance(self):
        root = self._root()
        app = ISPApplication(root)
        try:
            app.open_calibration_workspace()
            root.update()
            panel = app.calibration_workspace.auto_panel
            panel.select_module("AWB")
            _analyzer, stage_index, _options = (
                panel._analysis_request()
            )
            self.assertEqual(stage_index, 2)
        finally:
            if root.winfo_exists():
                root.update()
                app.close()

    def test_brush_updates_other_image_without_switching(self):
        root = self._root()
        app = ISPApplication(root)
        try:
            loaded = synthetic_bayer(192, 128)
            app.work_items.append(
                ImageWorkItem(
                    loaded,
                    snapshot_for_image(
                        app.pipeline.snapshot(), loaded
                    ),
                    CalibrationSession(
                        raw_metadata=copy.deepcopy(loaded.metadata)
                    ),
                )
            )
            app._refresh_image_selector()
            module = app.pipeline.module_by_id(
                "black_level_correction"
            )
            module.parameters["r"] = 123.0
            app._mark_manual_parameter_state(module)
            app.apply_calibration_brush(
                ("black_level_correction",)
            )
            target = next(
                item
                for item in app.work_items[1].pipeline_snapshot
                if item["id"] == "black_level_correction"
            )
            self.assertEqual(target["parameters"]["r"], 123.0)
            self.assertEqual(app.current_image_index, 0)
        finally:
            if root.winfo_exists():
                app.close()

    def test_batch_import_builds_switchable_image_workset(self):
        root = self._root()
        app = ISPApplication(root)
        try:
            with tempfile.TemporaryDirectory() as folder:
                paths = []
                for index, color in enumerate(
                    ((40, 80, 120), (120, 70, 30))
                ):
                    path = Path(folder) / f"frame_{index}.png"
                    Image.new("RGB", (64, 48), color).save(path)
                    paths.append(str(path))
                app._load_paths(paths)
                deadline = time.time() + 5.0
                while (
                    len(app.work_items) != 2
                    and time.time() < deadline
                ):
                    root.update()
                    time.sleep(0.01)
            self.assertEqual(len(app.work_items), 2)
            self.assertEqual(len(app.image_combo["values"]), 2)
            module = app.pipeline.module_by_id(
                "black_level_correction"
            )
            original = module.parameters["global_offset"]
            module.parameters["global_offset"] = original + 3.0
            app._mark_manual_parameter_state(module)
            app._activate_work_item(1)
            self.assertEqual(app.current_image_index, 1)
            self.assertEqual(app.loaded.source_path.name, "frame_1.png")
            app._activate_work_item(0)
            self.assertIn(
                "black_level_correction",
                app.manual_dirty_modules,
            )
            self.assertTrue(app.manual_apply_button.winfo_manager())
            app.revert_manual_parameters()
            self.assertEqual(
                app.pipeline.module_by_id(
                    "black_level_correction"
                ).parameters["global_offset"],
                original,
            )
        finally:
            if root.winfo_exists():
                app.close()


class VersionTests(unittest.TestCase):
    def test_version_is_v044(self):
        self.assertGreaterEqual(
            tuple(map(int, __version__.split("."))), (0, 4, 4)
        )


if __name__ == "__main__":
    unittest.main()
