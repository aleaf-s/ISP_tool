import tkinter as tk
import time
import unittest

import numpy as np

from isp_tool import __version__
from isp_tool.models import ImageROI
from isp_tool.raw_io import synthetic_bayer
from isp_tool.roi_tools import generate_grid_rois
from isp_tool.ui.app import ISPApplication
from isp_tool.ui.final_preview import (
    compute_impact_metrics,
    impact_heatmap,
)
from isp_tool.ui.roi_editor import MAX_ROI_COUNT


class CustomROIGridTests(unittest.TestCase):
    def test_custom_grid_count_and_bounds(self):
        bounds = ImageROI(37, 29, 511, 307)
        rois = generate_grid_rois(
            bounds,
            (480, 640),
            rows=3,
            cols=7,
            inset_fraction=0.2,
            bayer_aligned=True,
        )
        self.assertEqual(len(rois), 21)
        self.assertLessEqual(len(rois), MAX_ROI_COUNT)
        for roi in rois:
            self.assertGreaterEqual(roi.x, bounds.x)
            self.assertGreaterEqual(roi.y, bounds.y)
            self.assertLessEqual(roi.x2, bounds.x2)
            self.assertLessEqual(roi.y2, bounds.y2)
            self.assertEqual(roi.x % 2, 0)
            self.assertEqual(roi.y % 2, 0)
            self.assertEqual(roi.width % 2, 0)
            self.assertEqual(roi.height % 2, 0)


class FinalImpactModelTests(unittest.TestCase):
    def test_metrics_and_heatmap_measure_visible_change(self):
        final = np.zeros((20, 30, 3), np.float32)
        bypass = np.full_like(final, 0.1)
        metrics = compute_impact_metrics(final, bypass)
        self.assertAlmostEqual(metrics["mean_abs"], 0.1, places=6)
        self.assertAlmostEqual(metrics["p95_abs"], 0.1, places=6)
        self.assertAlmostEqual(metrics["changed_ratio"], 1.0)
        heatmap = impact_heatmap(final, bypass)
        self.assertEqual(heatmap.shape, final.shape)
        self.assertTrue(np.all(np.isfinite(heatmap)))


class HiddenTkV045Tests(unittest.TestCase):
    def _root(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        root.withdraw()
        return root

    def test_grid_is_generated_inside_selected_roi(self):
        root = self._root()
        app = ISPApplication(root)
        try:
            bounds = ImageROI(100, 80, 600, 360)
            app.rois = [bounds]
            app.active_roi_index = 0
            app.roi = bounds
            app.generate_24_rois(
                rows=3, cols=5, inset_fraction=0.1
            )
            self.assertEqual(len(app.rois), 15)
            self.assertEqual(app.roi_grid_bounds, bounds)
            self.assertEqual(
                (app.roi_grid_rows, app.roi_grid_cols), (3, 5)
            )
            for roi in app.rois:
                self.assertGreaterEqual(roi.x, bounds.x)
                self.assertGreaterEqual(roi.y, bounds.y)
                self.assertLessEqual(roi.x2, bounds.x2)
                self.assertLessEqual(roi.y2, bounds.y2)
        finally:
            if root.winfo_exists():
                app.close()

    def test_final_impact_page_lists_all_modules(self):
        root = self._root()
        app = ISPApplication(root)
        try:
            app.loaded = synthetic_bayer(320, 240)
            app._prepare_preview()
            app.results = []
            app.pipeline_cache = {}
            app.open_final_preview()
            window = app.final_preview_window
            deadline = time.time() + 10.0
            while (
                not window.status_var.get().startswith("Ready")
                and time.time() < deadline
            ):
                root.update()
                time.sleep(0.01)
            self.assertIsNotNone(window)
            self.assertEqual(
                window.module_list.size(), len(app.pipeline.modules)
            )
            self.assertEqual(len(window.notebook.tabs()), 2)
            self.assertTrue(app.preview_menu.winfo_manager())
            self.assertTrue(window.cache)
        finally:
            if root.winfo_exists():
                app.close()

    def test_calibration_no_longer_builds_hidden_legacy_tabs(self):
        root = self._root()
        app = ISPApplication(root)
        try:
            app.open_calibration_workspace()
            root.update()
            workspace = app.calibration_workspace
            self.assertFalse(hasattr(workspace, "legacy_host"))
            self.assertTrue(hasattr(workspace, "mesh_rows_var"))
            self.assertTrue(hasattr(workspace, "ccm_rotation_var"))
            self.assertEqual(
                len(workspace.auto_panel.workspace_paned.panes()), 2
            )
        finally:
            if root.winfo_exists():
                root.update()
                app.close()


class VersionTests(unittest.TestCase):
    def test_version_is_v045(self):
        self.assertEqual(__version__, "0.4.5")


if __name__ == "__main__":
    unittest.main()
