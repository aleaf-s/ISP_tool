import tkinter as tk
import unittest

from isp_tool import __version__
from isp_tool.models import CalibrationSession, ImageROI
from isp_tool.raw_io import synthetic_bayer
from isp_tool.ui.app import ISPApplication
from isp_tool.workspace import ImageWorkItem
from isp_tool.workspace_state import WorkspaceItemStateController


class WorkspaceItemStateControllerTests(unittest.TestCase):
    def setUp(self):
        self.loaded = synthetic_bayer(16, 12)
        self.session = CalibrationSession(
            raw_metadata=self.loaded.metadata
        )
        self.controller = WorkspaceItemStateController()

    def _state(self, active=0):
        return self.controller.capture(
            loaded=self.loaded,
            pipeline_snapshot=[{"id": "ccm", "parameters": {"x": 1}}],
            calibration_session=self.session,
            rois=[ImageROI(0, 0, 4, 4)],
            active_roi_index=active,
            roi_grid_bounds=ImageROI(0, 0, 8, 8),
            roi_grid_rows=4,
            roi_grid_cols=6,
            roi_grid_inset=0.12,
            manual_parameter_snapshots={"ccm": {"x": 1}},
            manual_dirty_modules=("wb", "ccm", "wb"),
            preview_shape=(12, 16),
            input_revision=3,
        )

    def test_capture_normalizes_active_index_and_dirty_modules(self):
        state = self._state(active=9)
        self.assertEqual(state.active_roi_index, -1)
        self.assertIsNone(state.active_roi)
        self.assertEqual(state.manual_dirty_modules, ("ccm", "wb"))

    def test_store_preserves_runtime_cache_and_copies_editable_data(self):
        item = ImageWorkItem(self.loaded, [], self.session)
        runtime = object()
        item.runtime_preview = runtime
        state = self._state()
        self.controller.store(item, state)
        self.assertIs(item.runtime_preview, runtime)
        self.assertEqual(item.active_roi_index, 0)
        state.pipeline_snapshot[0]["parameters"]["x"] = 7
        self.assertEqual(item.pipeline_snapshot[0]["parameters"]["x"], 1)

    def test_activation_payload_is_isolated_from_item(self):
        item = ImageWorkItem(self.loaded, [], self.session)
        self.controller.store(item, self._state())
        activated = self.controller.activation(item)
        activated.manual_parameter_snapshots["ccm"]["x"] = 9
        activated.pipeline_snapshot[0]["parameters"]["x"] = 8
        self.assertEqual(item.manual_parameter_snapshots["ccm"]["x"], 1)
        self.assertEqual(item.pipeline_snapshot[0]["parameters"]["x"], 1)


class HiddenTkWorkspaceStateTests(unittest.TestCase):
    def test_application_store_uses_controller_and_keeps_runtime_entry(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        root.withdraw()
        app = ISPApplication(root)
        try:
            runtime = object()
            app.work_items[0].runtime_preview = runtime
            app._store_current_work_item()
            self.assertIs(app.work_items[0].runtime_preview, runtime)
            self.assertEqual(
                app.work_items[0].input_revision, app.input_revision
            )
        finally:
            app.close()


class VersionTests(unittest.TestCase):
    def test_version_is_at_least_v0432(self):
        self.assertGreaterEqual(
            tuple(map(int, __version__.split("."))), (0, 4, 32)
        )


if __name__ == "__main__":
    unittest.main()
