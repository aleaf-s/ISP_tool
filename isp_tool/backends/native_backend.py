from __future__ import annotations

from typing import Optional

import numpy as np

from .base import DPCKernelResult, DemosaicKernelResult
from .opencv_backend import OpenCVBackend


class NativeBackend(OpenCVBackend):
    """Optional native extension with per-kernel OpenCV fallback."""

    backend_id = "native"
    name = "Native C++"
    is_native = True

    def __init__(self, native_module, force_all_native=False) -> None:
        self.native_module = native_module
        info = {}
        if callable(getattr(native_module, "backend_info", None)):
            value = native_module.backend_info()
            if isinstance(value, dict):
                info = dict(value)
        self.version = str(info.get("version", "unknown"))
        self.force_all_native = bool(force_all_native)
        self._declared_qualified_kernels = info.get(
            "qualified_kernels"
        )

    @property
    def cache_key(self) -> str:
        kernels = ",".join(self.native_kernels) or "fallback"
        return f"{self.backend_id}:{self.version}:{kernels}"

    @property
    def native_kernels(self):
        available = self.available_native_kernels
        if self.force_all_native:
            return available
        declared = self._declared_qualified_kernels
        if declared is None:
            return available
        qualified = {str(item) for item in declared}
        return tuple(
            name for name in available if name in qualified
        )

    @property
    def available_native_kernels(self):
        kernels = []
        if callable(
            getattr(self.native_module, "demosaic_bilinear", None)
        ):
            kernels.append("demosaic_bilinear")
        if callable(getattr(self.native_module, "dpc_correct", None)):
            kernels.append("dpc_correct")
        return tuple(kernels)

    @property
    def disabled_native_kernels(self):
        enabled = set(self.native_kernels)
        return tuple(
            name for name in self.available_native_kernels
            if name not in enabled
        )

    @property
    def capabilities(self):
        native = tuple(f"{name} (native)" for name in self.native_kernels)
        disabled = tuple(
            f"{name} (OpenCV fallback · not performance-qualified)"
            for name in self.disabled_native_kernels
        )
        return native + disabled + (
            "Unsupported native kernels fall back to OpenCV / NumPy",
        )

    def demosaic(
        self, image: np.ndarray, pattern: str, algorithm: str
    ) -> DemosaicKernelResult:
        function = getattr(
            self.native_module, "demosaic_bilinear", None
        )
        if (
            algorithm != "Bilinear"
            or "demosaic_bilinear" not in self.native_kernels
            or not callable(function)
        ):
            return super().demosaic(image, pattern, algorithm)
        output = np.asarray(
            function(
                np.ascontiguousarray(image, dtype=np.float32),
                str(pattern),
            ),
            dtype=np.float32,
        )
        expected_shape = tuple(image.shape) + (3,)
        if output.shape != expected_shape:
            raise ValueError(
                "Native demosaic returned an invalid image: "
                f"{output.shape}, expected {expected_shape}"
            )
        return DemosaicKernelResult(output, self.backend_id)

    def correct_defective_pixels(
        self,
        image: np.ndarray,
        *,
        kernel: int,
        threshold: float,
        detect_hot: bool,
        detect_dark: bool,
        static_map: Optional[np.ndarray],
        dynamic_enabled: bool,
        static_enabled: bool,
    ) -> DPCKernelResult:
        function = getattr(self.native_module, "dpc_correct", None)
        if (
            "dpc_correct" not in self.native_kernels
            or not callable(function)
        ):
            return super().correct_defective_pixels(
                image,
                kernel=kernel,
                threshold=threshold,
                detect_hot=detect_hot,
                detect_dark=detect_dark,
                static_map=static_map,
                dynamic_enabled=dynamic_enabled,
                static_enabled=static_enabled,
            )
        dense_static_map = (
            np.ascontiguousarray(static_map, dtype=np.uint8)
            if static_enabled and static_map is not None
            else np.zeros((0, 0), dtype=np.uint8)
        )
        value = function(
            np.ascontiguousarray(image, dtype=np.float32),
            int(kernel),
            float(threshold),
            bool(detect_hot),
            bool(detect_dark),
            dense_static_map,
            bool(dynamic_enabled),
            bool(static_enabled),
        )
        if not isinstance(value, tuple) or len(value) != 5:
            raise ValueError("Native DPC returned an invalid result")
        corrected, mask, hot, dark, count = value
        corrected = np.asarray(corrected, dtype=np.float32)
        mask = np.asarray(mask, dtype=np.uint8)
        if corrected.shape != image.shape or mask.shape != image.shape:
            raise ValueError(
                "Native DPC output shape does not match the input"
            )
        # ISPPipeline performs the common finite-value validation once after
        # every module. Avoid scanning a full native image a second time here.
        return DPCKernelResult(
            corrected,
            mask,
            int(hot),
            int(dark),
            int(count),
            self.backend_id,
        )
