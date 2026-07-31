import importlib
import unittest

import numpy as np

from isp_tool import __version__
from isp_tool.backends import NativeBackend, OpenCVBackend, select_backend
from isp_tool.bayer import bayer_to_rgb_bilinear
from isp_tool.pipeline import ISPPipeline
from isp_tool.raw_io import synthetic_bayer


class QualifiedFakeNative:
    ISP_BACKEND_ABI = 1

    def __init__(self):
        self.demosaic_calls = 0
        self.dpc_calls = 0

    @staticmethod
    def backend_info():
        return {
            "version": "qualified-test",
            "abi": 1,
            "kernels": ("demosaic_bilinear", "dpc_correct"),
            "qualified_kernels": ("demosaic_bilinear",),
        }

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


class KernelQualificationTests(unittest.TestCase):
    def test_auto_enables_only_performance_qualified_native_kernels(self):
        module = QualifiedFakeNative()
        selection = select_backend("Auto", native_module=module)
        backend = selection.backend
        self.assertEqual(
            backend.native_kernels, ("demosaic_bilinear",)
        )
        self.assertEqual(
            backend.disabled_native_kernels, ("dpc_correct",)
        )
        source = synthetic_bayer(96, 64).image
        result = backend.correct_defective_pixels(
            source,
            kernel=3,
            threshold=0.08,
            detect_hot=True,
            detect_dark=True,
            static_map=None,
            dynamic_enabled=True,
            static_enabled=False,
        )
        self.assertEqual(result.implementation, "opencv")
        self.assertEqual(module.dpc_calls, 0)

    def test_explicit_native_mode_can_force_experimental_kernel(self):
        module = QualifiedFakeNative()
        selection = select_backend(
            "Native C++", native_module=module
        )
        backend = selection.backend
        self.assertIn("dpc_correct", backend.native_kernels)
        source = synthetic_bayer(96, 64).image
        result = backend.correct_defective_pixels(
            source,
            kernel=3,
            threshold=0.08,
            detect_hot=True,
            detect_dark=True,
            static_map=None,
            dynamic_enabled=True,
            static_enabled=False,
        )
        self.assertEqual(result.implementation, "native")
        self.assertEqual(module.dpc_calls, 1)

    def test_auto_and_forced_native_have_distinct_cache_keys(self):
        module = QualifiedFakeNative()
        automatic = select_backend(
            "Auto", native_module=module
        ).backend
        forced = select_backend(
            "Native C++", native_module=module
        ).backend
        self.assertNotEqual(automatic.cache_key, forced.cache_key)

    def test_pipeline_diagnostics_report_mixed_kernel_execution(self):
        module = QualifiedFakeNative()
        backend = select_backend(
            "Auto", native_module=module
        ).backend
        pipeline = ISPPipeline(backend=backend)
        loaded = synthetic_bayer(96, 64)
        results = pipeline.process(
            loaded.image, loaded.domain, loaded.metadata
        )
        demosaic = next(
            result
            for result in results
            if result.module_id == "demosaic"
        )
        self.assertEqual(demosaic.diagnostics["Backend"], "native")


class CompiledNativeContractTests(unittest.TestCase):
    def test_compiled_extension_matches_reference_when_present(self):
        try:
            module = importlib.import_module("isp_tool._native")
        except (ImportError, OSError) as exc:
            self.skipTest(f"compiled native extension unavailable: {exc}")
        backend = NativeBackend(module, force_all_native=True)
        reference = OpenCVBackend()
        source = np.random.default_rng(410).random(
            (65, 97), dtype=np.float32
        )
        np.testing.assert_allclose(
            backend.demosaic(source, "RGGB", "Bilinear").image,
            reference.demosaic(source, "RGGB", "Bilinear").image,
            rtol=1e-6,
            atol=2e-7,
        )
        options = {
            "kernel": 3,
            "threshold": 0.1,
            "detect_hot": True,
            "detect_dark": True,
            "static_map": None,
            "dynamic_enabled": True,
            "static_enabled": False,
        }
        expected = reference.correct_defective_pixels(
            source, **options
        )
        actual = backend.correct_defective_pixels(
            source, **options
        )
        np.testing.assert_array_equal(actual.corrected, expected.corrected)
        np.testing.assert_array_equal(
            actual.defect_mask, expected.defect_mask
        )


class VersionTests(unittest.TestCase):
    def test_version_is_v0410(self):
        self.assertGreaterEqual(
            tuple(map(int, __version__.split("."))), (0, 4, 10)
        )


if __name__ == "__main__":
    unittest.main()
