import time
import tkinter as tk
import unittest
from types import SimpleNamespace

import numpy as np

from isp_tool import __version__
from isp_tool.bayer import channel_positions
from isp_tool.models import ImageROI, RawMetadata, StageDataState
from isp_tool.sampling import (
    ImageCoordinateMapper,
    PixelSamplingService,
    format_pixel_status,
)
from isp_tool.ui.app import ISPApplication
from isp_tool.yuv import YUVFrame, YUVMetadata


class ImageCoordinateMapperTests(unittest.TestCase):
    def test_canvas_display_and_source_round_trip(self):
        transform = (10.0, 20.0, 2.0, 100, 80)
        display = ImageCoordinateMapper.canvas_to_display(
            30, 50, transform
        )
        self.assertEqual(display, (10, 15))
        source = ImageCoordinateMapper.display_to_source(
            display, (80, 100), (160, 200)
        )
        self.assertEqual(source, (20, 30))
        self.assertEqual(
            ImageCoordinateMapper.source_to_display(
                source, (80, 100), (160, 200)
            ),
            display,
        )
        self.assertIsNone(
            ImageCoordinateMapper.canvas_to_display(0, 0, transform)
        )

    def test_roi_mapping_preserves_source_offset(self):
        roi = ImageROI(40, 24, 20, 16)
        source = ImageCoordinateMapper.display_to_source(
            (3, 5), (16, 20), (100, 120), roi
        )
        self.assertEqual(source, (43, 29))
        self.assertEqual(
            ImageCoordinateMapper.source_to_display(
                source, (16, 20), (100, 120), roi
            ),
            (3, 5),
        )
        self.assertIsNone(
            ImageCoordinateMapper.source_to_display(
                (10, 10), (16, 20), (100, 120), roi
            )
        )


class PixelSamplingServiceTests(unittest.TestCase):
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

    def test_bayer_sample_uses_source_phase_and_absolute_codes(self):
        image = np.arange(64, dtype=np.float32).reshape(8, 8) / 64.0
        state = StageDataState(
            "bayer",
            "Bayer Linear Normalized",
            0.0,
            1.0,
            True,
            True,
            12,
            (64.0, 64.0, 64.0, 64.0),
            4095.0,
        )
        sample = self.service.sample(
            image,
            "bayer",
            self.metadata,
            (3, 2),
            (13, 22),
            data_state=state,
            neighborhood_size=5,
        )
        expected_channel = next(
            name
            for name, position in channel_positions("RGGB").items()
            if position == (22 % 2, 13 % 2)
        )
        self.assertEqual(sample.center_channel, expected_channel)
        self.assertEqual(
            sample.absolute_values[expected_channel],
            round(float(image[2, 3]) * 4095),
        )
        self.assertEqual(
            sum(item.count for item in sample.statistics.values()), 25
        )
        self.assertIn(expected_channel, sample.grid[2][2])

    def test_rgb_sample_retains_negative_compute_codes_and_clips_display(self):
        image = np.zeros((5, 5, 3), np.float32)
        image[2, 2] = (-0.1, 0.5, 1.2)
        state = StageDataState.for_input("rgb", self.metadata)
        sample = self.service.sample(
            image,
            "rgb",
            self.metadata,
            (2, 2),
            data_state=state,
            neighborhood_size=5,
        )
        self.assertLess(sample.absolute_values["R"], 0)
        self.assertGreater(sample.absolute_values["B"], 4095)
        self.assertEqual(sample.display_values["R"], 0)
        self.assertEqual(sample.display_values["B"], 4095)
        self.assertIn("RGB裁剪前≈", format_pixel_status(sample))

    def test_yuv_sample_reports_native_three_channel_statistics(self):
        metadata = YUVMetadata(4, 2, "YUV444P")
        frame = YUVFrame(
            np.array([[16, 32, 64, 128], [20, 40, 80, 160]], np.uint8),
            np.full((2, 4), 100, np.uint8),
            np.full((2, 4), 150, np.uint8),
            metadata,
        )
        rgb = np.full((2, 4, 3), 0.5, np.float32)
        sample = self.service.sample(
            rgb,
            "yuv_rgb",
            RawMetadata(width=4, height=2, bit_depth=8),
            (2, 1),
            (2, 1),
            neighborhood_size=5,
            yuv_frame=frame,
            yuv_rgb=rgb,
        )
        self.assertEqual(sample.domain, "yuv")
        self.assertEqual(tuple(sample.statistics), ("Y", "U", "V"))
        self.assertEqual(sample.absolute_values["Y"], 80)
        self.assertEqual(sample.extra["rgb_absolute"], (128, 128, 128))
        self.assertIn("YUV=(80, 100, 150)", format_pixel_status(sample))


class HiddenTkPixelInspectorTests(unittest.TestCase):
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

    def test_inspector_is_singleton_and_hover_does_not_process(self):
        generation = self.app.generation
        pending_after = self.app.pending_after
        self.app.open_pixel_inspector()
        window = self.app.pixel_inspector_window
        self.app.open_pixel_inspector()
        self.assertIs(self.app.pixel_inspector_window, window)

        self.root.update_idletasks()
        origin_x, origin_y, zoom, width, height = self.app.display_transform
        event = SimpleNamespace(
            x=int(origin_x + width * zoom * 0.5),
            y=int(origin_y + height * zoom * 0.5),
        )
        self.app._last_mouse_status_at = 0.0
        self.app._on_canvas_motion(event)
        self.assertIsNotNone(window.current_sample)
        self.assertEqual(self.app.generation, generation)
        self.assertEqual(self.app.pending_after, pending_after)

        window.size_var.set("7×7")
        window.refresh_from_app()
        self.assertEqual(window.current_sample.neighborhood_size, 7)
        self.app.language_controller.set_language(
            "en_US", persist=False
        )
        self.app.language_var.set("en_US")
        self.app._refresh_language()
        self.assertEqual(window.follow_button.cget("text"), "Follow Cursor")
        self.assertEqual(self.app.generation, generation)
        self.assertEqual(self.app.pending_after, pending_after)
        self.app.language_controller.set_language(
            "zh_CN", persist=False
        )
        self.app.language_var.set("zh_CN")
        self.app._refresh_language()

        window.pin_current()
        self.assertEqual(len(window.pins), 1)
        self.app.render_current(schedule_analysis=False)
        self.assertEqual(len(window.pins_tree.get_children()), 1)

    def test_preview_dropdown_exposes_pixel_inspector(self):
        labels = [
            self.app.preview_menu.menu.entrycget(index, "label")
            for index in range(
                int(self.app.preview_menu.menu.index("end")) + 1
            )
        ]
        self.assertIn("Pixel Inspector…", labels)


class VersionTests(unittest.TestCase):
    def test_version_is_at_least_v0428(self):
        self.assertGreaterEqual(
            tuple(map(int, __version__.split("."))), (0, 4, 28)
        )


if __name__ == "__main__":
    unittest.main()
