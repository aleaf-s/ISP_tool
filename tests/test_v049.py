import unittest

import numpy as np

from isp_tool import __version__
from isp_tool.backends import (
    NativeBackend,
    OpenCVBackend,
    select_backend,
)
from isp_tool.bayer import bayer_to_rgb_bilinear
from isp_tool.models import RawMetadata
from isp_tool.modules import DefectivePixelCorrection, Demosaic
from isp_tool.pipeline import ISPPipeline
from isp_tool.raw_io import synthetic_bayer


class FakeNativeModule:
    ISP_BACKEND_ABI = 1

    def __init__(self):
        self.demosaic_calls = 0
        self.dpc_calls = 0

    @staticmethod
    def backend_info():
        return {"version": "test-native", "abi": 1}

    def demosaic_bilinear(self, image, pattern):
        self.demosaic_calls += 1
        return bayer_to_rgb_bilinear(image, pattern)

    def dpc_correct(
        self,
        image,
        kernel,
        threshold,
        detect_hot,
        detect_dark,
        static_map,
        dynamic_enabled,
        static_enabled,
    ):
        self.dpc_calls += 1
        value = OpenCVBackend().correct_defective_pixels(
            image,
            kernel=kernel,
            threshold=threshold,
            detect_hot=detect_hot,
            detect_dark=detect_dark,
            static_map=static_map if static_map.size else None,
            dynamic_enabled=dynamic_enabled,
            static_enabled=static_enabled,
        )
        return (
            value.corrected,
            value.defect_mask,
            value.hot_count,
            value.dark_count,
            value.corrected_count,
        )


class BackendRegistryTests(unittest.TestCase):
    def test_explicit_native_request_falls_back_cleanly_when_unavailable(self):
        selection = select_backend(
            "Native C++", native_module=None
        )
        self.assertIsInstance(selection.backend, OpenCVBackend)
        self.assertFalse(selection.native.available)
        self.assertTrue(selection.fallback_reason)

    def test_auto_selects_a_compatible_native_module(self):
        native = FakeNativeModule()
        selection = select_backend("Auto", native_module=native)
        self.assertIsInstance(selection.backend, NativeBackend)
        self.assertEqual(selection.backend.cache_key.split(":")[0], "native")

    def test_incompatible_native_abi_is_rejected(self):
        native = FakeNativeModule()
        native.ISP_BACKEND_ABI = 99
        selection = select_backend(
            "Native C++", native_module=native
        )
        self.assertIsInstance(selection.backend, OpenCVBackend)
        self.assertIn("ABI", selection.fallback_reason)


class NativeDispatchTests(unittest.TestCase):
    def test_demosaic_module_dispatches_exact_bilinear_to_native(self):
        native = FakeNativeModule()
        backend = NativeBackend(native)
        module = Demosaic()
        module.processing_backend = backend
        loaded = synthetic_bayer(96, 64)
        output, _, diagnostics = module.process(
            loaded.image, loaded.domain, loaded.metadata
        )
        expected = bayer_to_rgb_bilinear(
            loaded.image, loaded.metadata.bayer_pattern
        )
        np.testing.assert_array_equal(output, expected)
        self.assertEqual(native.demosaic_calls, 1)
        self.assertEqual(diagnostics["Backend"], "native")

    def test_unsupported_native_demosaic_mode_uses_reference_fallback(self):
        native = FakeNativeModule()
        backend = NativeBackend(native)
        result = backend.demosaic(
            synthetic_bayer(64, 48).image,
            "RGGB",
            "Adaptive Interpolation",
        )
        self.assertEqual(native.demosaic_calls, 0)
        self.assertEqual(result.implementation, "opencv")

    def test_dpc_module_dispatches_to_native_contract(self):
        native = FakeNativeModule()
        module = DefectivePixelCorrection()
        module.processing_backend = NativeBackend(native)
        source = np.random.default_rng(49).random(
            (48, 64), dtype=np.float32
        )
        output = module.process(
            source,
            "bayer",
            RawMetadata(width=64, height=48),
        )
        self.assertEqual(native.dpc_calls, 1)
        self.assertEqual(output[2]["Backend"], "native")
        self.assertEqual(output[0].shape, source.shape)


class TaggedOpenCVBackend(OpenCVBackend):
    def __init__(self, tag):
        self.tag = str(tag)

    @property
    def cache_key(self):
        return f"opencv-test:{self.tag}"


class BackendCacheSafetyTests(unittest.TestCase):
    def test_pipeline_cache_is_invalidated_by_backend_cache_key(self):
        loaded = synthetic_bayer(96, 64)
        pipeline = ISPPipeline(backend=TaggedOpenCVBackend("first"))
        snapshot = pipeline.snapshot()
        cache = {}
        pipeline.process_cached(
            loaded.image,
            loaded.domain,
            loaded.metadata,
            snapshot,
            cache,
            input_revision=1,
        )
        self.assertEqual(
            cache["backend_cache_key"], "opencv-test:first"
        )

        pipeline.set_backend(TaggedOpenCVBackend("second"))
        pipeline.process_cached(
            loaded.image,
            loaded.domain,
            loaded.metadata,
            snapshot,
            cache,
            input_revision=1,
        )
        self.assertEqual(
            cache["backend_cache_key"], "opencv-test:second"
        )
        self.assertEqual(cache["last_metrics"]["cache_hits"], 0)
        self.assertEqual(
            cache["last_metrics"]["recomputed"],
            len(pipeline.modules),
        )


class VersionTests(unittest.TestCase):
    def test_version_is_at_least_v049(self):
        self.assertGreaterEqual(
            tuple(map(int, __version__.split("."))), (0, 4, 9)
        )


if __name__ == "__main__":
    unittest.main()
