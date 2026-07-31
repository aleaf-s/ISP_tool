import time
import tkinter as tk
import unittest
from types import SimpleNamespace

from isp_tool import __version__
from isp_tool.ui.app import ISPApplication


class HiddenTkV0415Tests(unittest.TestCase):
    def _root(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        root.withdraw()
        return root

    @staticmethod
    def _wait(root, condition, timeout=5.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            root.update()
            if condition():
                return
            time.sleep(0.01)
        raise AssertionError("condition timed out")

    @staticmethod
    def _event_for_pixel(app, x=4, y=4):
        return SimpleNamespace(
            x=int(app.canvas_origin[0] + (x + 0.5) * app.zoom),
            y=int(app.canvas_origin[1] + (y + 0.5) * app.zoom),
        )

    def test_auto_page_has_no_duplicate_module_header(self):
        root = self._root()
        app = ISPApplication(root)
        try:
            app.open_calibration_workspace()
            root.update()
            panel = app.calibration_workspace.auto_panel
            self.assertFalse(hasattr(panel, "module_combo"))
            self.assertFalse(hasattr(panel, "workflow_var"))
            visible_text = []

            def collect(widget):
                try:
                    if widget.winfo_manager():
                        text = widget.cget("text")
                        if text:
                            visible_text.append(str(text))
                except tk.TclError:
                    pass
                for child in widget.winfo_children():
                    collect(child)

            collect(panel)
            self.assertNotIn("快速自动矫正", visible_text)
            self.assertNotIn("Module", visible_text)
        finally:
            if root.winfo_exists():
                app.close()

    def test_pixel_hover_shows_normalized_and_bit_depth_values(self):
        root = self._root()
        app = ISPApplication(root)
        try:
            self._wait(root, lambda: len(app.results) >= 5)

            app.stage_combo.current(0)
            app.render_current()
            app._last_mouse_status_at = 0.0
            app._on_canvas_motion(self._event_for_pixel(app))
            input_status = app.status_var.get()
            self.assertIn("DN=", input_status)
            self.assertIn("Normalized=", input_status)
            self.assertIn(
                f"{app.loaded.metadata.bit_depth}-bit范围",
                input_status,
            )

            wb_index = next(
                index
                for index, result in enumerate(app.results)
                if result.module_id == "white_balance"
            )
            app.stage_combo.current(wb_index)
            app.render_current()
            app._last_mouse_status_at = 0.0
            app._on_canvas_motion(self._event_for_pixel(app))
            wb_status = app.status_var.get()
            self.assertIn("Linear=", wb_status)
            self.assertIn("bit绝对值≈", wb_status)

            demosaic_index = next(
                index
                for index, result in enumerate(app.results)
                if result.module_id == "demosaic"
            )
            app.stage_combo.current(demosaic_index)
            app.render_current()
            app._last_mouse_status_at = 0.0
            app._on_canvas_motion(self._event_for_pixel(app))
            rgb_status = app.status_var.get()
            self.assertIn("Linear RGB=", rgb_status)
            self.assertIn("bit绝对值≈(", rgb_status)
        finally:
            if root.winfo_exists():
                app.close()

    def test_version_is_at_least_v0415(self):
        self.assertGreaterEqual(
            tuple(map(int, __version__.split("."))),
            (0, 4, 15),
        )


if __name__ == "__main__":
    unittest.main()
