import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from isp_tool import __version__
from isp_tool.analysis import compute_histogram_details
from isp_tool.models import CalibrationSession, RawMetadata
from isp_tool.ui.app import ISPApplication
from isp_tool.workspace import ImageWorkItem, snapshot_for_image
from isp_tool.yuv import (
    YUVFrame,
    YUVMetadata,
    compute_yuv_histogram_details,
)


class AbsoluteHistogramModelTests(unittest.TestCase):
    def test_bayer_histogram_has_four_cfa_channels_and_dn_axis(self):
        metadata = RawMetadata(
            width=4,
            height=4,
            bit_depth=12,
            bayer_pattern="RGGB",
            black_level=[0, 0, 0, 0],
            white_level=4095,
        )
        image = np.zeros((4, 4), np.float32)
        image[0::2, 0::2] = 100
        image[0::2, 1::2] = 200
        image[1::2, 0::2] = 300
        image[1::2, 1::2] = 400
        payload = compute_histogram_details(
            image, "bayer", metadata, bins=256
        )
        self.assertEqual(
            set(payload["curves"]), {"R", "Gr", "Gb", "B"}
        )
        self.assertEqual(payload["code_max"], 4095)
        self.assertEqual(payload["curve_sizes"]["Gr"], 4)
        self.assertEqual(payload["stats"]["minimum"], 100.0)
        self.assertEqual(payload["stats"]["maximum"], 400.0)

    def test_rgb_histogram_reports_absolute_out_of_range_values(self):
        metadata = RawMetadata(
            width=2,
            height=1,
            bit_depth=10,
            black_level=[0, 0, 0, 0],
            white_level=1023,
        )
        image = np.array(
            [[[-0.1, 0.5, 0.5], [1.2, 1.0, 0.0]]],
            np.float32,
        )
        payload = compute_histogram_details(
            image, "rgb", metadata, mode="RGB Overlay"
        )
        self.assertEqual(payload["code_max"], 1023)
        self.assertGreater(payload["stats"]["overflow_ratio"], 0.0)

    def test_yuv_native_histogram_uses_roi_and_limited_markers(self):
        metadata = YUVMetadata(
            4, 4, "NV12", bit_depth=8, color_range="Limited"
        )
        frame = YUVFrame(
            np.arange(16, dtype=np.uint8).reshape(4, 4) + 16,
            np.full((2, 2), 128, np.uint8),
            np.full((2, 2), 129, np.uint8),
            metadata,
        )
        payload = compute_yuv_histogram_details(
            frame,
            np.zeros((4, 4, 3), np.float32),
            mode="YUV 原始",
            roi=(0, 0, 2, 2),
        )
        self.assertEqual(payload["curve_sizes"]["Y"], 4)
        self.assertEqual(payload["curve_sizes"]["U"], 1)
        self.assertEqual(payload["legal_ranges"]["Y"], (16, 235))


class HiddenTkHistogramToolTests(unittest.TestCase):
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

    def test_histogram_has_direct_button_and_domain_controls(self):
        root = self._root()
        app = ISPApplication(root)
        try:
            self._wait(root, lambda: bool(app.results))
            self.assertTrue(app.analysis_collapsed)
            self.assertTrue(app.histogram_button.winfo_manager())
            app.open_histogram_window()
            window = app.histogram_window
            root.update_idletasks()
            self.assertIsNotNone(window)
            self.assertTrue(window.winfo_exists())
            self.assertTrue(app.analysis_collapsed)
            self.assertEqual(
                str(app.histogram_button.cget("style")),
                "Primary.TButton",
            )
            self._wait(
                root,
                lambda: window.last_payload is not None,
            )
            self.assertEqual(
                tuple(window.channel_vars), ("R", "Gr", "Gb", "B")
            )
            self.assertEqual(window.current_domain, "bayer")
            self.assertEqual(
                window._module_result_index(), app.selected_module_index + 1
            )
            self.assertFalse(hasattr(window, "source_combo"))
            self.assertFalse(hasattr(app, "histogram_source_combo"))

            app.open_histogram_window()
            self.assertIs(app.histogram_window, window)

            demosaic_index = next(
                index for index, module in enumerate(app.pipeline.modules)
                if module.module_id == "demosaic"
            )
            app.pipeline_list.selection_clear(0, "end")
            app.pipeline_list.selection_set(demosaic_index)
            app._on_module_select()
            self._wait(root, lambda: window.current_domain == "rgb")
            self.assertEqual(tuple(window.channel_vars), ("R", "G", "B"))
            self.assertIn(app.results[demosaic_index + 1].name, window.title_var.get())
        finally:
            if root.winfo_exists():
                app.close()

    def test_histogram_render_exposes_summary_and_hover_bin(self):
        root = self._root()
        app = ISPApplication(root)
        try:
            self._wait(root, lambda: bool(app.results))
            app.open_histogram_window()
            window = app.histogram_window
            self._wait(root, lambda: window.last_payload is not None)
            self.assertIn("暗部", window.summary_var.get())
            left, top, right, bottom = window.plot_bounds
            window._on_motion(
                SimpleNamespace(
                    x=int((left + right) / 2),
                    y=int((top + bottom) / 2),
                )
            )
            self.assertIn("码值", window.hover_var.get())
            self.assertIn("R", window.hover_var.get())

            for variable in window.channel_vars.values():
                variable.set(False)
            window._channel_changed("B")
            self.assertEqual(window._enabled_channels(), ("B",))

            generation = window.generation
            window.refresh(1000)
            self.assertGreater(window.generation, generation)
            window.close()
            self.assertIsNone(app.histogram_window)
        finally:
            if root.winfo_exists():
                app.close()

    def test_yuv_window_exposes_only_native_yuv_channels(self):
        root = self._root()
        app = ISPApplication(root)
        temporary = tempfile.TemporaryDirectory()
        try:
            path = Path(temporary.name) / "4x2_nv12.yuv"
            y = np.arange(8, dtype=np.uint8).reshape(2, 4) + 16
            uv = np.array([[128, 128, 128, 128]], np.uint8)
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
            self._wait(root, lambda: app.loaded.yuv_conversion is not None)
            app.open_histogram_window()
            window = app.histogram_window
            self._wait(root, lambda: window.last_payload is not None)
            self.assertEqual(window.current_domain, "yuv")
            self.assertEqual(tuple(window.channel_vars), ("Y", "U", "V"))
            self.assertEqual(set(window.last_payload["curves"]), {"Y", "U", "V"})
            self.assertNotIn("R", window.channel_vars)
        finally:
            temporary.cleanup()
            if root.winfo_exists():
                app.close()


class VersionTests(unittest.TestCase):
    def test_version_is_at_least_v0423(self):
        self.assertGreaterEqual(
            tuple(map(int, __version__.split("."))),
            (0, 4, 23),
        )


if __name__ == "__main__":
    unittest.main()
