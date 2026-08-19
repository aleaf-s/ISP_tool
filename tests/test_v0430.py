import time
import tkinter as tk
import unittest
from types import SimpleNamespace

from isp_tool import __version__
from isp_tool.ui.app import ISPApplication
from isp_tool.ui.controllers import (
    CanvasGestureCoordinator,
    GESTURE_COMPARE,
    GESTURE_GRAY_PICK,
    GESTURE_LINE_PROFILE,
    GESTURE_NONE,
    GESTURE_ROI,
)


class CanvasGestureCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.coordinator = CanvasGestureCoordinator()

    def test_gray_picker_has_highest_priority(self):
        self.coordinator.arm(GESTURE_GRAY_PICK)
        selected = self.coordinator.begin(
            (10, 20),
            compare_divider_hit=True,
            roi_enabled=True,
            compare_enabled=True,
        )
        self.assertEqual(selected, GESTURE_GRAY_PICK)
        self.assertEqual(self.coordinator.snapshot.start, (10, 20))
        self.assertEqual(self.coordinator.finish(), GESTURE_GRAY_PICK)
        self.assertEqual(self.coordinator.armed, GESTURE_NONE)

    def test_compare_divider_precedes_armed_measurement_and_preserves_it(self):
        self.coordinator.arm(GESTURE_LINE_PROFILE)
        selected = self.coordinator.begin(
            (5, 6),
            compare_divider_hit=True,
            roi_enabled=True,
            compare_enabled=True,
        )
        self.assertEqual(selected, GESTURE_COMPARE)
        self.assertEqual(self.coordinator.finish(), GESTURE_COMPARE)
        self.assertEqual(
            self.coordinator.armed, GESTURE_LINE_PROFILE
        )

    def test_armed_line_precedes_roi_and_is_one_shot(self):
        self.coordinator.arm(GESTURE_LINE_PROFILE)
        selected = self.coordinator.begin(
            (1, 2),
            compare_divider_hit=False,
            roi_enabled=True,
            compare_enabled=True,
        )
        self.assertEqual(selected, GESTURE_LINE_PROFILE)
        self.coordinator.update((8, 9))
        self.assertEqual(self.coordinator.snapshot.current, (8, 9))
        self.coordinator.finish()
        self.assertEqual(self.coordinator.armed, GESTURE_NONE)

    def test_roi_precedes_compare_body(self):
        selected = self.coordinator.begin(
            (3, 4),
            compare_divider_hit=False,
            roi_enabled=True,
            compare_enabled=True,
        )
        self.assertEqual(selected, GESTURE_ROI)

    def test_cursor_and_cancel_contract(self):
        self.coordinator.arm(GESTURE_LINE_PROFILE)
        self.assertEqual(
            self.coordinator.cursor(
                compare_divider_hit=False, roi_enabled=False
            ),
            "crosshair",
        )
        self.assertEqual(
            self.coordinator.cursor(
                compare_divider_hit=True, roi_enabled=True
            ),
            "sb_h_double_arrow",
        )
        self.coordinator.cancel_all()
        self.assertEqual(self.coordinator.snapshot.active, GESTURE_NONE)
        self.assertEqual(self.coordinator.snapshot.armed, GESTURE_NONE)


class HiddenTkGestureIntegrationTests(unittest.TestCase):
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

    def test_roi_drag_is_owned_and_released_by_coordinator(self):
        self.app.roi_mode_var.set(True)
        start = self._event_at(0.2, 0.2)
        end = self._event_at(0.4, 0.4)
        self.app._on_left_press(start)
        self.assertEqual(
            self.app.canvas_gestures.active, GESTURE_ROI
        )
        self.app._on_left_drag(end)
        self.app._on_left_release(end)
        self.assertEqual(
            self.app.canvas_gestures.active, GESTURE_NONE
        )
        self.assertIsNotNone(self.app.roi)

    def test_legacy_properties_proxy_coordinator_state(self):
        self.app.line_profile_mode = True
        self.assertEqual(
            self.app.canvas_gestures.armed, GESTURE_LINE_PROFILE
        )
        self.app.line_profile_dragging = True
        self.assertTrue(self.app.line_profile_dragging)
        self.app.line_profile_dragging = False
        self.app.line_profile_mode = False
        self.assertEqual(
            self.app.canvas_gestures.snapshot.active, GESTURE_NONE
        )
        self.assertEqual(
            self.app.canvas_gestures.snapshot.armed, GESTURE_NONE
        )


class VersionTests(unittest.TestCase):
    def test_version_is_at_least_v0430(self):
        self.assertGreaterEqual(
            tuple(map(int, __version__.split("."))), (0, 4, 30)
        )


if __name__ == "__main__":
    unittest.main()
