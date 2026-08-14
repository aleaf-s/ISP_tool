import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from isp_tool import __version__
from isp_tool.models import CalibrationSession
from isp_tool.ui.app import ISPApplication
from isp_tool.workspace import ImageWorkItem, snapshot_for_image
from isp_tool.yuv import PIXEL_FORMATS, YUVMetadata


class HiddenTkYUVQuickFormatTests(unittest.TestCase):
    def _root(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        root.withdraw()
        return root

    @staticmethod
    def _wait(root, condition, timeout=8.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            root.update()
            if condition():
                return
            time.sleep(0.01)
        raise AssertionError("condition timed out")

    def _load_yuv(self, app, root, directory):
        path = Path(directory) / "4x2_8bit_420sp.yuv"
        y = np.arange(8, dtype=np.uint8).reshape(2, 4) + 16
        u = np.array([[80, 90]], np.uint8)
        v = np.array([[160, 170]], np.uint8)
        uv = np.stack((u, v), axis=-1)
        path.write_bytes(y.tobytes() + uv.tobytes())
        loaded = app._read_work_items(
            [str(path)],
            None,
            app.pipeline.snapshot(),
            YUVMetadata(4, 2, "NV12"),
            1500,
        )[0][0].loaded
        app.work_items = [
            ImageWorkItem(
                loaded,
                snapshot_for_image(app.pipeline.snapshot(), loaded),
                CalibrationSession(raw_metadata=loaded.metadata),
            )
        ]
        app.current_image_index = -1
        app._activate_work_item(0)
        self._wait(
            root,
            lambda: (
                app.loaded.yuv_frame is not None
                and bool(app.results)
                and app.results[-1].module_id == "display_preview"
            ),
        )

    def test_pixel_format_and_related_choices_are_complete(self):
        root = self._root()
        app = ISPApplication(root)
        temporary = tempfile.TemporaryDirectory()
        try:
            self._load_yuv(app, root, temporary.name)
            self.assertEqual(
                tuple(app.yuv_combos["pixel_format"].cget("values")),
                PIXEL_FORMATS,
            )
            self.assertEqual(
                tuple(app.yuv_combos["bit_depth"].cget("values")),
                ("8", "10", "12", "16"),
            )
            self.assertEqual(
                tuple(app.yuv_combos["endianness"].cget("values")),
                ("little", "big"),
            )

            app.yuv_vars["pixel_format"].set("NV21")
            app._apply_yuv_panel_settings()
            self._wait(
                root,
                lambda: (
                    app.loaded.yuv_frame is not None
                    and app.loaded.yuv_frame.metadata.pixel_format == "NV21"
                ),
            )
            self.assertEqual(app.loaded.yuv_metadata.pixel_format, "NV21")
        finally:
            temporary.cleanup()
            if root.winfo_exists():
                app.close()

    def test_yuv_hover_uses_absolute_values_only(self):
        root = self._root()
        app = ISPApplication(root)
        temporary = tempfile.TemporaryDirectory()
        try:
            self._load_yuv(app, root, temporary.name)
            app.render_current()
            event = SimpleNamespace(
                x=int(app.canvas_origin[0] + 0.5 * app.zoom),
                y=int(app.canvas_origin[1] + 0.5 * app.zoom),
            )
            app._last_mouse_status_at = 0.0
            app._on_canvas_motion(event)
            status = app.status_var.get()
            self.assertIn("YUV=(", status)
            self.assertIn("RGB裁剪前≈", status)
            self.assertIn("显示RGB=", status)
            self.assertNotIn("Normalized=", status)
            self.assertNotIn("RGB'=(", status)
        finally:
            temporary.cleanup()
            if root.winfo_exists():
                app.close()

    def test_canvas_toolbar_hides_gray_and_one_to_one_buttons(self):
        root = self._root()
        app = ISPApplication(root)
        try:
            texts = []
            for child in app.canvas_toolbar.winfo_children():
                try:
                    texts.append(str(child.cget("text")))
                except tk.TclError:
                    pass
            self.assertNotIn("Gray", texts)
            self.assertNotIn("1:1", texts)
            self.assertIn("适合窗口", texts)
        finally:
            if root.winfo_exists():
                app.close()


class VersionTests(unittest.TestCase):
    def test_version_is_at_least_v0421(self):
        self.assertGreaterEqual(
            tuple(map(int, __version__.split("."))),
            (0, 4, 21),
        )


if __name__ == "__main__":
    unittest.main()
