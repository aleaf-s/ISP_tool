import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from isp_tool import __version__
from isp_tool.models import CalibrationSession
from isp_tool.raw_io import synthetic_bayer
from isp_tool.ui.app import ISPApplication
from isp_tool.workspace import ImageWorkItem, snapshot_for_image
from isp_tool.yuv import YUVMetadata


class HiddenTkYUVIntegrationTests(unittest.TestCase):
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

    @staticmethod
    def _event_for_pixel(app, x=1, y=1):
        return SimpleNamespace(
            x=int(app.canvas_origin[0] + (x + 0.5) * app.zoom),
            y=int(app.canvas_origin[1] + (y + 0.5) * app.zoom),
        )

    def test_yuv_uses_isolated_pipeline_and_frame_navigation(self):
        root = self._root()
        app = ISPApplication(root)
        temporary = tempfile.TemporaryDirectory()
        try:
            path = Path(temporary.name) / "4x2_nv12.yuv"
            uv = np.array([[128, 128, 128, 128]], np.uint8)
            frame0 = np.full((2, 4), 16, np.uint8).tobytes() + uv.tobytes()
            frame1 = np.full((2, 4), 235, np.uint8).tobytes() + uv.tobytes()
            path.write_bytes(frame0 + frame1)
            metadata = YUVMetadata(4, 2, "NV12", frame_count=2)
            loaded = app._read_work_items(
                [str(path)],
                None,
                app.pipeline.snapshot(),
                metadata,
                1500,
            )[0][0].loaded
            item = ImageWorkItem(
                loaded,
                snapshot_for_image(app.pipeline.snapshot(), loaded),
                CalibrationSession(raw_metadata=loaded.metadata),
            )
            app.work_items = [item]
            app.current_image_index = -1
            app._activate_work_item(0)
            self._wait(
                root,
                lambda: len(app.results) == 4
                and app.results[-1].module_id == "display_preview",
            )

            self.assertEqual(app.loaded.domain, "yuv")
            self.assertEqual(
                [result.module_id for result in app.results],
                [
                    "yuv_input",
                    "chroma_upsampling",
                    "yuv_to_rgb",
                    "display_preview",
                ],
            )
            self.assertFalse(app.mode_switch.winfo_manager())
            self.assertEqual(str(app.auto_calibration_button["state"]), "disabled")
            self.assertIn("RAW ISP 未执行", app.module_state_var.get())
            self.assertEqual(
                app.pipeline_cache["last_metrics"]["yuv_cache_key"][1],
                0,
            )

            app.render_current()
            app._last_mouse_status_at = 0.0
            app._on_canvas_motion(self._event_for_pixel(app))
            status = app.status_var.get()
            self.assertIn("YUV=(16, 128, 128)", status)
            self.assertIn("BT.709", status)

            app._step_yuv_frame(1)
            self._wait(
                root,
                lambda: app.loaded.yuv_metadata.frame_index == 1
                and app.pipeline_cache.get("last_metrics", {})
                .get("yuv_cache_key", (None, None))[1] == 1,
            )
            self.assertEqual(app.loaded.yuv_frame.sample(0, 0)[0], 235)

            app._step_yuv_frame(-1)
            self._wait(
                root,
                lambda: app.pipeline_cache.get("last_metrics", {})
                .get("cache_hits") == 1,
            )
            self.assertEqual(app.loaded.yuv_frame.sample(0, 0)[0], 16)

            app.yuv_vars["color_matrix"].set("BT.601")
            app._apply_yuv_panel_settings()
            self._wait(
                root,
                lambda: app.pipeline_cache.get("last_metrics", {})
                .get("yuv_cache_key", (None,) * 4)[3] == "BT.601",
            )
            self.assertEqual(
                app.pipeline_cache["last_metrics"]["recomputed"], 3
            )
            self.assertEqual(app.results[0].elapsed_ms, 0.0)
            self.assertTrue(
                app.loaded.yuv_frame.diagnostics.get("reused_planes")
            )

            raw = synthetic_bayer(64, 48)
            app.work_items.append(
                ImageWorkItem(
                    raw,
                    snapshot_for_image(app.pipeline.snapshot(), raw),
                    CalibrationSession(raw_metadata=raw.metadata),
                )
            )
            app._activate_work_item(1)
            self._wait(
                root,
                lambda: app.loaded.domain == "bayer"
                and len(app.results) == len(app.pipeline.modules) + 1,
            )
            self.assertEqual(
                str(app.auto_calibration_button["state"]), "normal"
            )
            self.assertEqual(app.pipeline_list.size(), len(app.pipeline.modules))
        finally:
            temporary.cleanup()
            if root.winfo_exists():
                app.close()

    def test_zoom_does_not_start_a_new_yuv_conversion(self):
        root = self._root()
        app = ISPApplication(root)
        try:
            self._wait(root, lambda: bool(app.results))
            app.loaded.domain = "yuv"
            app.display_array = np.zeros((16, 16, 3), np.float32)
            app.display_linear_array = app.display_array
            app.display_is_encoded_rgb = True
            generation = app.generation
            app._zoom_at(4, 4, 1.15)
            self.assertEqual(app.generation, generation)
        finally:
            if root.winfo_exists():
                app.close()


class VersionTests(unittest.TestCase):
    def test_version_is_at_least_v0418(self):
        self.assertGreaterEqual(
            tuple(map(int, __version__.split("."))),
            (0, 4, 18),
        )


if __name__ == "__main__":
    unittest.main()
