import copy
import tkinter as tk
import unittest

import cv2
import numpy as np

from isp_tool import __version__
from isp_tool.bayer import (
    bayer_to_rgb_bilinear,
    bayer_to_rgb_opencv_bilinear,
    channel_positions,
)
from isp_tool.models import CalibrationSession, ImageROI, RawMetadata
from isp_tool.modules import DefectivePixelCorrection, Demosaic
from isp_tool.raw_io import synthetic_bayer
from isp_tool.ui.app import (
    ISPApplication,
    PREVIEW_QUALITY_CHOICES,
)
from isp_tool.workspace import ImageWorkItem


def reference_dpc(module, image, metadata):
    src = np.asarray(image, dtype=np.float32)
    kernel = 3 if module.parameters["neighborhood"] == "3×3" else 5
    static_map = module.defect_map
    corrected = src.copy()
    hot_full = np.zeros(src.shape, dtype=bool)
    dark_full = np.zeros(src.shape, dtype=bool)
    mode = module.parameters.get("mode", "Dynamic")
    for y in range(2):
        for x in range(2):
            plane = src[y::2, x::2]
            median = cv2.medianBlur(plane, kernel)
            delta = plane - median
            hot = np.zeros_like(plane, dtype=bool)
            dark = np.zeros_like(plane, dtype=bool)
            if module.parameters["detect_hot"]:
                hot = delta > float(module.parameters["threshold"])
            if module.parameters["detect_dark"]:
                dark = delta < -float(module.parameters["threshold"])
            if mode == "Static Map":
                hot[:] = False
                dark[:] = False
            if static_map is not None and mode in {"Static Map", "Hybrid"}:
                static_plane = static_map[y::2, x::2]
                hot |= static_plane == 1
                dark |= static_plane == 2
            mask = hot | dark
            corrected[y::2, x::2][mask] = median[mask]
            hot_full[y::2, x::2] = hot
            dark_full[y::2, x::2] = dark
    defect = hot_full.astype(np.uint8) + dark_full.astype(np.uint8) * 2
    return corrected, defect, int(hot_full.sum()), int(dark_full.sum())


class DPCOpenCVMaskParityTests(unittest.TestCase):
    def test_dynamic_and_hybrid_outputs_match_previous_numpy_path(self):
        source = np.random.default_rng(47).random(
            (65, 97), dtype=np.float32
        )
        metadata = RawMetadata(width=97, height=65)
        static_map = np.zeros(source.shape, np.uint8)
        static_map[12, 20] = 1
        static_map[31, 43] = 2
        for mode in ("Dynamic", "Static Map", "Hybrid"):
            for neighborhood in ("3×3", "5×5"):
                with self.subTest(mode=mode, neighborhood=neighborhood):
                    module = DefectivePixelCorrection()
                    module.parameters.update(
                        {
                            "mode": mode,
                            "neighborhood": neighborhood,
                            "threshold": 0.11,
                        }
                    )
                    module.set_defect_map(static_map)
                    expected = reference_dpc(module, source, metadata)
                    actual = module.process(source, "bayer", metadata)
                    np.testing.assert_array_equal(actual[0], expected[0])
                    np.testing.assert_array_equal(
                        actual[3]["Defect Mask"], expected[1]
                    )
                    self.assertEqual(actual[2]["亮坏点"], expected[2])
                    self.assertEqual(actual[2]["暗坏点"], expected[3])

    def test_empty_static_mode_is_a_true_fast_bypass(self):
        source = np.ones((32, 48), np.float32)
        module = DefectivePixelCorrection()
        module.parameters["mode"] = "Static Map"
        output, _, diagnostics, artifacts = module.process(
            source, "bayer", RawMetadata(width=48, height=32)
        )
        self.assertTrue(np.shares_memory(output, source))
        self.assertEqual(diagnostics["坏点数量"], 0)
        self.assertFalse(np.any(artifacts["Defect Mask"]))


class FastDemosaicTests(unittest.TestCase):
    def test_fast_bilinear_keeps_channel_order_and_highlight_range(self):
        values = {"R": 0.4, "Gr": 0.8, "Gb": 0.8, "B": 1.6}
        for pattern in ("RGGB", "GRBG", "GBRG", "BGGR"):
            with self.subTest(pattern=pattern):
                source = np.zeros((48, 64), np.float32)
                for name, (y, x) in channel_positions(pattern).items():
                    source[y::2, x::2] = values[name]
                output = bayer_to_rgb_opencv_bilinear(source, pattern)
                center = output[3:-3, 3:-3].mean(axis=(0, 1))
                np.testing.assert_allclose(
                    center, [0.4, 0.8, 1.6], atol=4e-5
                )
                self.assertGreater(float(output.max()), 1.0)

    def test_fast_bilinear_matches_exact_path_away_from_border(self):
        source = np.random.default_rng(3).random(
            (63, 95), dtype=np.float32
        )
        exact = bayer_to_rgb_bilinear(source, "RGGB")
        fast = bayer_to_rgb_opencv_bilinear(source, "RGGB")
        np.testing.assert_allclose(
            fast[3:-3, 3:-3],
            exact[3:-3, 3:-3],
            atol=2e-5,
            rtol=2e-5,
        )

    def test_module_exposes_only_the_four_product_algorithms(self):
        module = Demosaic()
        self.assertEqual(
            module.specs["algorithm"].choices,
            (
                "Nearest Neighbor",
                "Bilinear",
                "Adaptive Interpolation",
                "Constant Color Difference",
            ),
        )
        source = synthetic_bayer(96, 64)
        for algorithm in module.specs["algorithm"].choices:
            with self.subTest(algorithm=algorithm):
                module.parameters["algorithm"] = algorithm
                output = module.process(
                    source.image, source.domain, source.metadata
                )[0]
                self.assertEqual(output.shape, (64, 96, 3))


class HiddenTkPreviewQualityTests(unittest.TestCase):
    def _root(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        root.withdraw()
        return root

    def test_quality_change_resizes_preview_and_existing_rois(self):
        root = self._root()
        app = ISPApplication(root)
        root.update_idletasks()
        try:
            app.loaded = synthetic_bayer(1800, 1200)
            app.work_items[0].loaded = app.loaded
            app._prepare_preview()
            old_shape = app.preview_image.shape
            app.rois = [ImageROI(150, 100, 600, 400)]
            app.active_roi_index = 0
            app.roi = app.rois[0]
            app.roi_grid_bounds = app.roi
            app.preview_quality_var.set("快速 · 900 px")
            app._apply_preview_quality_from_menu()
            self.assertEqual(max(app.preview_image.shape), 900)
            self.assertEqual(app.preview_max_side, 900)
            self.assertEqual(
                app.work_items[0].preview_shape,
                app.preview_image.shape[:2],
            )
            scale_x = app.preview_image.shape[1] / old_shape[1]
            scale_y = app.preview_image.shape[0] / old_shape[0]
            self.assertAlmostEqual(app.roi.x, 150 * scale_x, delta=2)
            self.assertAlmostEqual(app.roi.y, 100 * scale_y, delta=2)
            self.assertEqual(app.roi.x % 2, 0)
            self.assertEqual(app.roi.y % 2, 0)
        finally:
            if root.winfo_exists():
                root.update_idletasks()
                app.close()

    def test_inactive_image_rois_rescale_when_it_is_activated(self):
        root = self._root()
        app = ISPApplication(root)
        root.update_idletasks()
        try:
            loaded = synthetic_bayer(1800, 1200)
            item = ImageWorkItem(
                loaded,
                copy.deepcopy(app.pipeline.snapshot()),
                CalibrationSession(raw_metadata=loaded.metadata),
                rois=[ImageROI(150, 100, 600, 400)],
                active_roi_index=0,
                preview_shape=(1000, 1500),
            )
            app.work_items.append(item)
            app.preview_quality_var.set("快速 · 900 px")
            app.preview_max_side = PREVIEW_QUALITY_CHOICES[
                app.preview_quality_var.get()
            ]
            app._activate_work_item(1)
            self.assertEqual(max(app.preview_image.shape), 900)
            self.assertAlmostEqual(app.roi.x, 90, delta=2)
            self.assertAlmostEqual(app.roi.y, 60, delta=2)
            self.assertEqual(
                item.preview_shape, app.preview_image.shape[:2]
            )
        finally:
            if root.winfo_exists():
                root.update_idletasks()
                app.close()


class VersionTests(unittest.TestCase):
    def test_version_is_at_least_v047(self):
        self.assertGreaterEqual(
            tuple(map(int, __version__.split("."))), (0, 4, 7)
        )


if __name__ == "__main__":
    unittest.main()
