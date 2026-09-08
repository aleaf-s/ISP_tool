import time
import tkinter as tk
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from isp_tool import __version__
from isp_tool.calibration.colorchecker import colorchecker_reference
from isp_tool.calibration.colorchecker_detection import (
    ColorCheckerDetectionResult,
    detect_colorchecker,
)
from isp_tool.models import ISPError, ImageROI


def _chart_image(rotate_clockwise=False):
    _names, reference = colorchecker_reference(illuminant="D65")
    camera_matrix = np.array([
        [1.18, -0.12, -0.06],
        [-0.08, 1.16, -0.08],
        [-0.05, -0.13, 1.18],
    ])
    measured = reference @ np.linalg.inv(camera_matrix).T
    chart = np.full((400, 600, 3), 0.025, np.float32)
    for index, color in enumerate(measured):
        row, column = divmod(index, 6)
        cv2.rectangle(
            chart,
            (column * 100 + 14, row * 100 + 14),
            ((column + 1) * 100 - 14, (row + 1) * 100 - 14),
            tuple(map(float, color)),
            -1,
        )
    if rotate_clockwise:
        chart = cv2.rotate(chart, cv2.ROTATE_90_CLOCKWISE)
    return chart


def _place_chart(chart, canvas_shape, destination):
    height, width = canvas_shape
    canvas = np.full((height, width, 3), 0.18, np.float32)
    source = np.float32([
        (0, 0),
        (chart.shape[1] - 1, 0),
        (chart.shape[1] - 1, chart.shape[0] - 1),
        (0, chart.shape[0] - 1),
    ])
    transform = cv2.getPerspectiveTransform(source, np.float32(destination))
    warped = cv2.warpPerspective(chart, transform, (width, height))
    mask = cv2.warpPerspective(
        np.ones(chart.shape[:2], np.uint8), transform, (width, height)
    )
    canvas[mask > 0] = warped[mask > 0]
    return canvas


class ColorCheckerDetectionTests(unittest.TestCase):
    def test_perspective_chart_is_located(self):
        destination = np.float32([
            (180, 130), (800, 90), (830, 590), (130, 620)
        ])
        image = _place_chart(_chart_image(), (720, 960), destination)

        result = detect_colorchecker(image)

        self.assertGreater(result.confidence, 0.75)
        np.testing.assert_allclose(result.corners, destination, atol=4.0)
        self.assertEqual(result.source, "full_image")
        self.assertEqual(result.patch_rgb.shape, (24, 3))

    def test_portrait_rotation_is_canonicalised(self):
        destination = np.float32([
            (220, 80), (600, 100), (650, 720), (180, 690)
        ])
        image = _place_chart(
            _chart_image(rotate_clockwise=True), (800, 800), destination
        )

        result = detect_colorchecker(image)

        neutral_luma = result.patch_rgb[18:24] @ np.array(
            (0.2126, 0.7152, 0.0722)
        )
        self.assertTrue(np.all(np.diff(neutral_luma) < 0.0))
        self.assertGreater(result.confidence, 0.75)

    def test_roi_search_returns_global_coordinates(self):
        destination = np.float32([
            (210, 160), (740, 145), (760, 520), (190, 540)
        ])
        image = _place_chart(_chart_image(), (700, 900), destination)
        roi = ImageROI(150, 110, 650, 480)

        result = detect_colorchecker(image, search_roi=roi)

        self.assertEqual(result.source, "current_roi")
        np.testing.assert_allclose(result.corners, destination, atol=5.0)

    def test_non_chart_image_is_rejected(self):
        image = np.random.default_rng(438).random(
            (480, 640, 3), dtype=np.float32
        )
        with self.assertRaises(ISPError):
            detect_colorchecker(image)


class HiddenTkDetectionWorkflowTests(unittest.TestCase):
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

    def test_detection_proposes_overlay_without_applying_ccm(self):
        from isp_tool.ui.app import ISPApplication

        root = self._root()
        app = ISPApplication(root)
        try:
            self._wait(root, lambda: bool(app.results))
            app.open_calibration_workspace()
            panel = app.calibration_workspace.auto_panel
            panel.select_module("CCM")
            module = app.pipeline.module_by_id("color_correction_matrix")
            original = dict(module.parameters)
            corners = np.float32([
                (8, 6), (86, 5), (88, 57), (6, 58)
            ])
            proposal = ColorCheckerDetectionResult(
                corners=corners,
                confidence=0.91,
                score=0.82,
                patch_rgb=np.zeros((24, 3), np.float32),
                source="full_image",
                diagnostics={},
            )

            with patch(
                "isp_tool.ui.auto_calibration_panel.detect_colorchecker",
                return_value=proposal,
            ):
                panel._detect_ccm_chart()
                self._wait(
                    root,
                    lambda: panel.ccm_region_source == "detected",
                )

            self.assertEqual(len(app.calibration_polygons), 24)
            self.assertEqual(
                app.calibration_workspace.ccm_rotation_var.get(), 0
            )
            self.assertFalse(
                app.calibration_workspace.ccm_flip_var.get()
            )
            self.assertIn(
                "91.0%", panel.ccm_source_status_var.get()
            )
            self.assertEqual(module.parameters, original)
        finally:
            if root.winfo_exists():
                app.close()


class VersionTests(unittest.TestCase):
    def test_version_is_at_least_v0438(self):
        self.assertGreaterEqual(
            tuple(map(int, __version__.split("."))),
            (0, 4, 38),
        )


if __name__ == "__main__":
    unittest.main()
