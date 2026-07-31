import time
import tkinter as tk
import unittest

from isp_tool import __version__
from isp_tool.ui.app import ISPApplication


class ViewportMathTests(unittest.TestCase):
    def test_high_zoom_bounds_cover_only_visible_source_pixels(self):
        bounds = ISPApplication._visible_source_bounds(
            image_width=1500,
            image_height=1000,
            canvas_width=900,
            canvas_height=600,
            origin_x=-5550,
            origin_y=-3700,
            zoom=8.0,
        )
        x0, y0, x1, y1 = bounds
        self.assertLessEqual(x1 - x0, 118)
        self.assertLessEqual(y1 - y0, 80)
        self.assertGreater(x1, x0)
        self.assertGreater(y1, y0)

    def test_16x_viewport_raster_is_far_smaller_than_full_zoom(self):
        zoom = 16.0
        image_width, image_height = 1500, 1000
        canvas_width, canvas_height = 1000, 700
        bounds = ISPApplication._visible_source_bounds(
            image_width,
            image_height,
            canvas_width,
            canvas_height,
            origin_x=-11500,
            origin_y=-7650,
            zoom=zoom,
        )
        x0, y0, x1, y1 = bounds
        viewport_pixels = (
            round((x1 - x0) * zoom)
            * round((y1 - y0) * zoom)
        )
        old_full_pixels = (
            round(image_width * zoom)
            * round(image_height * zoom)
        )
        self.assertLess(viewport_pixels, old_full_pixels * 0.01)


class HiddenTkViewportTests(unittest.TestCase):
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

    def test_16x_render_allocates_only_a_viewport_sized_photo(self):
        root = self._root()
        app = ISPApplication(root)
        try:
            self._wait(root, lambda: bool(app.results))
            image_h, image_w = app.display_array.shape[:2]
            canvas_w = max(app.image_canvas.winfo_width(), 10)
            canvas_h = max(app.image_canvas.winfo_height(), 10)
            app.fit_mode = False
            app.zoom = 16.0
            app.canvas_origin = [
                canvas_w / 2 - image_w * app.zoom / 2,
                canvas_h / 2 - image_h * app.zoom / 2,
            ]
            app._render_canvas_image()
            self.assertLessEqual(
                app.photo.width(), canvas_w + 6 * app.zoom + 4
            )
            self.assertLessEqual(
                app.photo.height(), canvas_h + 6 * app.zoom + 4
            )
            self.assertLess(
                app.photo.width(), image_w * app.zoom * 0.2
            )
        finally:
            if root.winfo_exists():
                app.close()

    def test_version_is_v0414(self):
        self.assertGreaterEqual(
            tuple(map(int, __version__.split("."))),
            (0, 4, 14),
        )


if __name__ == "__main__":
    unittest.main()
