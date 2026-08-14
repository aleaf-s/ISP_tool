import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from isp_tool import __version__
from isp_tool.models import CalibrationSession
from isp_tool.raw_io import synthetic_bayer
from isp_tool.ui.app import ISPApplication
from isp_tool.workspace import ImageWorkItem, snapshot_for_image


class HiddenTkSimpleDualWorkspaceTests(unittest.TestCase):
    def _root(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        root.withdraw()
        return root

    def test_toolbar_exposes_workspace_switch_and_full_image_name(self):
        root = self._root()
        app = ISPApplication(root)
        try:
            root.update_idletasks()
            self.assertTrue(app.isp_workspace_button.winfo_manager())
            self.assertTrue(app.yuv_workspace_button.winfo_manager())
            self.assertEqual(
                str(app.isp_workspace_button.cget("style")),
                "Primary.TButton",
            )
            self.assertEqual(
                str(app.yuv_workspace_button.cget("style")),
                "Secondary.TButton",
            )

            long_name = "sensor_capture_with_a_complete_long_file_name.raw"
            app.work_items[0].loaded.source_path = Path(long_name)
            app._refresh_image_selector()
            self.assertIn(long_name, app.image_combo.get())
            self.assertGreaterEqual(int(app.image_combo.cget("width")), 32)
        finally:
            if root.winfo_exists():
                app.close()

    def test_switch_to_empty_yuv_workspace_opens_yuv_import(self):
        root = self._root()
        app = ISPApplication(root)
        try:
            with patch.object(app, "open_yuv_files") as open_yuv:
                app._switch_workspace("yuv")
                open_yuv.assert_called_once_with()
        finally:
            if root.winfo_exists():
                app.close()

    def test_remove_current_image_never_deletes_source_file(self):
        root = self._root()
        app = ISPApplication(root)
        temporary = tempfile.TemporaryDirectory()
        try:
            source = Path(temporary.name) / "keep_me.raw"
            source.write_bytes(b"source must remain")
            first = synthetic_bayer(64, 48)
            first.source_path = source
            second = synthetic_bayer(64, 48)
            second.description = "Second image"
            app.work_items = [
                ImageWorkItem(
                    first,
                    snapshot_for_image(app.pipeline.snapshot(), first),
                    CalibrationSession(raw_metadata=first.metadata),
                ),
                ImageWorkItem(
                    second,
                    snapshot_for_image(app.pipeline.snapshot(), second),
                    CalibrationSession(raw_metadata=second.metadata),
                ),
            ]
            app.current_image_index = -1
            app._activate_work_item(0)
            app.remove_current_image()

            self.assertTrue(source.exists())
            self.assertEqual(len(app.work_items), 1)
            self.assertEqual(app.work_items[0].label, "Second image")
        finally:
            temporary.cleanup()
            if root.winfo_exists():
                app.close()

    def test_expert_mode_and_rare_preview_entries_are_removed(self):
        root = self._root()
        app = ISPApplication(root)
        try:
            app.expert_mode_var.set(True)
            app._apply_expert_mode()
            self.assertFalse(app.expert_mode)
            self.assertFalse(app.expert_mode_var.get())
            self.assertFalse(app.stage_selector.winfo_manager())

            end = app.preview_menu.menu.index("end")
            labels = [
                app.preview_menu.menu.entrycget(index, "label")
                for index in range(int(end) + 1)
            ]
            self.assertNotIn("专家模式", labels)
            self.assertNotIn("Performance Details", labels)
            self.assertNotIn("计算后端", labels)
            advanced_end = app.advanced_tools_menu.index("end")
            advanced_labels = [
                app.advanced_tools_menu.entrycget(index, "label")
                for index in range(int(advanced_end) + 1)
            ]
            self.assertIn("计算后端", advanced_labels)
            self.assertIn("性能详情…", advanced_labels)
        finally:
            if root.winfo_exists():
                app.close()


class VersionTests(unittest.TestCase):
    def test_version_is_at_least_v0419(self):
        self.assertGreaterEqual(
            tuple(map(int, __version__.split("."))),
            (0, 4, 19),
        )


if __name__ == "__main__":
    unittest.main()
