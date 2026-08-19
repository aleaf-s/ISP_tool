import time
import tkinter as tk
import unittest
from types import SimpleNamespace

import numpy as np

from isp_tool import __version__
from isp_tool.models import RawMetadata, StageDataState
from isp_tool.sampling import PixelSamplingService
from isp_tool.ui.app import ISPApplication
from isp_tool.yuv import YUVFrame, YUVMetadata


class LineProfileSamplingTests(unittest.TestCase):
    def setUp(self):
        self.service = PixelSamplingService()
        self.metadata = RawMetadata(
            width=8,
            height=8,
            bit_depth=12,
            bayer_pattern="RGGB",
            black_level=[64.0] * 4,
            white_level=4095.0,
        )

    def test_rgb_line_is_inclusive_and_keeps_out_of_range_codes(self):
        image = np.zeros((4, 6, 3), np.float32)
        image[1, :, 0] = np.linspace(-0.1, 1.2, 6)
        image[1, :, 1] = 0.5
        image[1, :, 2] = 0.25
        profile = self.service.sample_line(
            image,
            "rgb",
            self.metadata,
            (0, 1),
            (5, 1),
            data_state=StageDataState.for_input("rgb", self.metadata),
        )
        self.assertEqual(profile.sample_count, 6)
        self.assertAlmostEqual(profile.length, 5.0)
        self.assertLess(profile.channels["R"][0], 0)
        self.assertGreater(profile.channels["R"][-1], 4095)
        np.testing.assert_allclose(profile.channels["G"], 4095 * 0.5)

    def test_bayer_line_assigns_each_code_to_its_source_cfa_channel(self):
        image = np.arange(64, dtype=np.float32).reshape(8, 8)
        profile = self.service.sample_line(
            image,
            "bayer",
            self.metadata,
            (0, 0),
            (7, 7),
            source_start=(10, 20),
            source_end=(17, 27),
            data_state=StageDataState.for_input("bayer", self.metadata),
        )
        self.assertEqual(profile.sample_count, 8)
        self.assertEqual(np.count_nonzero(np.isfinite(profile.channels["R"])), 4)
        self.assertEqual(np.count_nonzero(np.isfinite(profile.channels["B"])), 4)
        self.assertFalse(np.any(np.isfinite(profile.channels["Gr"])))
        self.assertFalse(np.any(np.isfinite(profile.channels["Gb"])))
        self.assertEqual(profile.channels["R"][0], image[0, 0])
        self.assertEqual(profile.channels["B"][1], image[1, 1])

    def test_yuv_line_uses_native_yuv_codes(self):
        metadata = YUVMetadata(4, 2, "YUV444P")
        frame = YUVFrame(
            np.array([[16, 32, 64, 128], [20, 40, 80, 160]], np.uint8),
            np.full((2, 4), 100, np.uint8),
            np.full((2, 4), 150, np.uint8),
            metadata,
        )
        profile = self.service.sample_line(
            np.zeros((2, 4, 3), np.float32),
            "rgb",
            RawMetadata(width=4, height=2, bit_depth=8),
            (0, 1),
            (3, 1),
            yuv_frame=frame,
        )
        self.assertEqual(profile.domain, "yuv")
        np.testing.assert_array_equal(
            profile.channels["Y"], (20, 40, 80, 160)
        )
        np.testing.assert_array_equal(profile.channels["U"], 100)
        np.testing.assert_array_equal(profile.channels["V"], 150)


class HiddenTkLineProfileTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        self.root.withdraw()
        self.app = ISPApplication(self.root)
        deadline = time.time() + 6.0
        while time.time() < deadline and not self.app.results:
            self.root.update()
            time.sleep(0.01)

    def tearDown(self):
        if hasattr(self, "app") and self.root.winfo_exists():
            self.app.close()

    def _event_at(self, fx, fy):
        origin_x, origin_y, zoom, width, height = self.app.display_transform
        return SimpleNamespace(
            x=int(origin_x + width * zoom * fx),
            y=int(origin_y + height * zoom * fy),
        )

    def test_window_is_singleton_and_line_gesture_does_not_process(self):
        generation = self.app.generation
        pending_after = self.app.pending_after
        self.app.open_line_profile()
        window = self.app.line_profile_window
        self.app.open_line_profile()
        self.assertIs(self.app.line_profile_window, window)

        self.app.roi_mode_var.set(True)
        self.app.arm_line_profile()
        self.assertFalse(self.app.roi_mode_var.get())
        start = self._event_at(0.2, 0.3)
        end = self._event_at(0.8, 0.7)
        self.app._on_left_press(start)
        self.app._on_left_drag(end)
        self.app._on_left_release(end)
        self.root.update()
        self.assertIsNotNone(self.app.line_profile_start)
        self.assertIsNotNone(self.app.line_profile_end)
        self.assertFalse(self.app.line_profile_mode)
        self.assertIn("output", window.profiles)
        self.assertIn("input", window.profiles)
        self.assertEqual(self.app.generation, generation)
        self.assertEqual(self.app.pending_after, pending_after)

    def test_compare_divider_keeps_gesture_priority(self):
        self.app.open_line_profile()
        self.app.compare_var.set(True)
        self.app.render_current(schedule_analysis=False)
        self.app.arm_line_profile()
        origin_x, origin_y, zoom, width, height = self.app.display_transform
        event = SimpleNamespace(
            x=int(origin_x + width * zoom * self.app.compare_position),
            y=int(origin_y + height * zoom * 0.5),
        )
        self.app._on_left_press(event)
        self.assertTrue(self.app.compare_dragging)
        self.assertFalse(self.app.line_profile_dragging)
        self.app._on_left_release(event)
        self.assertTrue(self.app.line_profile_mode)

    def test_clear_and_image_change_remove_measurement(self):
        self.app.open_line_profile()
        self.app.line_profile_start = (1, 1)
        self.app.line_profile_end = (5, 5)
        self.app.line_profile_window.refresh_from_app(0)
        self.root.update()
        self.assertTrue(self.app.line_profile_window.profiles)
        self.app.clear_line_profile()
        self.root.update()
        self.assertIsNone(self.app.line_profile_start)
        self.assertFalse(self.app.line_profile_window.profiles)

    def test_preview_dropdown_exposes_line_profile(self):
        labels = [
            self.app.preview_menu.menu.entrycget(index, "label")
            for index in range(
                int(self.app.preview_menu.menu.index("end")) + 1
            )
        ]
        self.assertIn("Line Profile…", labels)


class VersionTests(unittest.TestCase):
    def test_version_is_at_least_v0429(self):
        self.assertGreaterEqual(
            tuple(map(int, __version__.split("."))), (0, 4, 29)
        )


if __name__ == "__main__":
    unittest.main()
