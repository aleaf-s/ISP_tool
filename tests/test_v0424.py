import itertools
import time
import tkinter as tk
import unittest
from types import SimpleNamespace

import numpy as np

from isp_tool import __version__
from isp_tool.analysis import compute_histogram_details
from isp_tool.calibration.awb import _prepare_bayer
from isp_tool.models import ParameterSpec, RawMetadata, StageDataState
from isp_tool.pipeline import ISPPipeline
from isp_tool.preview import display_rgb
from isp_tool.raw_io import synthetic_bayer
from isp_tool.ui.theme import configure_theme
from isp_tool.ui.widgets import ParameterControl


class PipelineBypassContractTests(unittest.TestCase):
    def test_all_five_module_enable_combinations_are_displayable(self):
        loaded = synthetic_bayer(64, 64)
        pipeline = ISPPipeline(backend_preference="OpenCV / NumPy")
        for enabled in itertools.product((False, True), repeat=5):
            with self.subTest(enabled=enabled):
                snapshot = pipeline.snapshot()
                for item, state in zip(snapshot, enabled):
                    item["enabled"] = state
                results = pipeline.process(
                    loaded.image,
                    "bayer",
                    loaded.metadata,
                    snapshot=snapshot,
                )
                self.assertEqual(len(results), 6)
                for index, result in enumerate(results):
                    self.assertEqual(
                        result.image.shape[:2], loaded.image.shape
                    )
                    self.assertTrue(np.all(np.isfinite(result.image)))
                    self.assertIsNotNone(result.data_state)
                    if index and not enabled[index - 1]:
                        np.testing.assert_array_equal(
                            result.image, results[index - 1].image
                        )
                        self.assertEqual(
                            result.data_state, results[index - 1].data_state
                        )
                final = results[-1]
                preview = display_rgb(
                    final.image,
                    final.domain,
                    loaded.metadata,
                    data_state=final.data_state,
                )
                self.assertEqual(preview.shape, (*loaded.image.shape, 3))
                self.assertGreater(float(preview.mean()), 0.0)
                self.assertLess(float(preview.mean()), 1.0)
                expected_domain = "rgb" if enabled[3] else "bayer"
                self.assertEqual(final.domain, expected_domain)
                self.assertEqual(final.data_state.normalized, enabled[0])

    def test_dn_rgb_preview_and_histogram_use_absolute_scale(self):
        metadata = RawMetadata(
            width=8,
            height=6,
            bit_depth=12,
            black_level=[64.0] * 4,
            white_level=4095.0,
        )
        state = StageDataState.for_input("bayer", metadata).with_domain(
            "rgb"
        )
        rgb_dn = np.full((6, 8, 3), 1024.0, np.float32)
        preview = display_rgb(
            rgb_dn, "rgb", metadata, data_state=state
        )
        np.testing.assert_allclose(preview, 1024.0 / 4095.0)
        histogram = compute_histogram_details(
            rgb_dn, "rgb", metadata, data_state=state
        )
        peak = int(np.argmax(histogram["curves"]["R"]))
        low = histogram["bin_edges"][peak]
        high = histogram["bin_edges"][peak + 1]
        self.assertLessEqual(low, 1024.0)
        self.assertGreaterEqual(high, 1024.0)

    def test_ccm_normalized_offset_is_scaled_for_dn(self):
        metadata = RawMetadata(white_level=4095.0)
        pipeline = ISPPipeline(backend_preference="OpenCV / NumPy")
        ccm = pipeline.module_by_id("color_correction_matrix")
        ccm.parameters["offset_r"] = 0.1
        metadata._stage_data_state = StageDataState.for_input(
            "bayer", metadata
        ).with_domain("rgb")
        source = np.full((4, 6, 3), 1000.0, np.float32)
        output, _, diagnostics = ccm.process(source, "rgb", metadata)
        np.testing.assert_allclose(output[..., 0], 1409.5, atol=1e-4)
        np.testing.assert_allclose(output[..., 1:], 1000.0, atol=1e-6)
        self.assertEqual(diagnostics["Offset Scale"], 4095.0)

    def test_awb_uses_stage_contract_instead_of_pixel_magnitude(self):
        metadata = RawMetadata(
            width=8,
            height=8,
            bit_depth=12,
            black_level=[64.0] * 4,
            white_level=4095.0,
        )
        # Strong linear gains may legitimately produce values above the old
        # magnitude threshold.  Explicit normalized state must preserve them.
        source = np.full((8, 8), 9.0, np.float32)
        state = StageDataState(
            "bayer", "Bayer Linear Normalized", 0.0, 1.0,
            True, True, 12, (64.0, 64.0, 64.0, 64.0), 4095.0,
        )
        prepared = _prepare_bayer(source, metadata, None, state)
        np.testing.assert_array_equal(prepared, source)


class ParameterControlTests(unittest.TestCase):
    def _root(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        root.withdraw()
        configure_theme(root)
        return root

    def test_entry_commit_reset_and_duplicate_commit(self):
        root = self._root()
        calls = []
        spec = ParameterSpec("gain", "Gain", "float", 0.5, 0, 1, 0.1)
        control = ParameterControl(root, spec, 0.3, calls.append)
        try:
            control.entry_var.set("0.96")
            self.assertEqual(calls, [])
            control._entry_commit()
            control._entry_commit()
            self.assertEqual(calls, [True])
            self.assertAlmostEqual(control.value(), 0.96)
            control.reset()
            self.assertEqual(control.entry_var.get(), "0.5")
        finally:
            root.destroy()

    def test_wheel_does_not_change_numeric_entry(self):
        root = self._root()
        control = ParameterControl(root, ParameterSpec("gain", "Gain", "float", .5, 0, 1, .1), .5, lambda _: None)
        try:
            control.entry.event_generate("<MouseWheel>", delta=120, state=4)
            self.assertEqual(control.value(), .5)
            self.assertFalse(control.entry.bind("<MouseWheel>"))
        finally:
            root.destroy()

    def test_slider_removed_and_keyboard_uses_step(self):
        root = self._root()
        control = ParameterControl(root, ParameterSpec("gain", "Gain", "float", .5, 0, 1, .1), .5, lambda _: None)
        try:
            self.assertFalse(hasattr(control, "scale"))
            control._key_step(SimpleNamespace(state=0), 1)
            self.assertEqual(control.value(), .6)
            control.entry_var.set("2")
            control._entry_commit()
            self.assertEqual(control.value(), .6)
            self.assertTrue(control.error_var.get())
        finally:
            root.destroy()

    def test_dark_combobox_and_parameter_scale_styles_are_explicit(self):
        root = self._root()
        try:
            style = configure_theme(root)
            self.assertTrue(style.lookup("TCombobox", "arrowcolor"))
            self.assertTrue(style.lookup("TCombobox", "background"))
            self.assertEqual(
                int(style.lookup("Parameter.Horizontal.TScale", "sliderlength")),
                18,
            )
        finally:
            root.destroy()


class VersionTests(unittest.TestCase):
    def test_version_is_at_least_v0424(self):
        self.assertGreaterEqual(
            tuple(map(int, __version__.split("."))), (0, 4, 24)
        )


if __name__ == "__main__":
    unittest.main()
