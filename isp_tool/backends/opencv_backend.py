from __future__ import annotations

from typing import Optional

import cv2
import numpy as np

from ..bayer import (
    bayer_to_rgb_adaptive,
    bayer_to_rgb_bilinear,
    bayer_to_rgb_constant_color_difference,
    bayer_to_rgb_nearest,
)
from .base import (
    DPCKernelResult,
    DemosaicKernelResult,
    ProcessingBackend,
)


class OpenCVBackend(ProcessingBackend):
    """Reference backend backed by the existing NumPy/OpenCV kernels."""

    backend_id = "opencv"
    name = "OpenCV / NumPy"

    @property
    def cache_key(self) -> str:
        return f"{self.backend_id}:{cv2.__version__}"

    @property
    def capabilities(self):
        return (
            "DPC (OpenCV)",
            "Demosaic Nearest Neighbor",
            "Demosaic Bilinear",
            "Demosaic Adaptive Interpolation",
            "Demosaic Constant Color Difference",
        )

    def demosaic(
        self, image: np.ndarray, pattern: str, algorithm: str
    ) -> DemosaicKernelResult:
        if algorithm == "Nearest Neighbor":
            output = bayer_to_rgb_nearest(image, pattern)
        elif algorithm == "Bilinear":
            output = bayer_to_rgb_bilinear(image, pattern)
        elif algorithm == "Adaptive Interpolation":
            output = bayer_to_rgb_adaptive(image, pattern)
        elif algorithm == "Constant Color Difference":
            output = bayer_to_rgb_constant_color_difference(image, pattern)
        else:
            raise ValueError(f"Unsupported demosaic algorithm: {algorithm}")
        return DemosaicKernelResult(
            np.asarray(output, dtype=np.float32),
            OpenCVBackend.backend_id,
        )

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
        src = np.asarray(image, dtype=np.float32)
        corrected = np.empty_like(src)
        defect_mask = np.empty(src.shape, dtype=np.uint8)
        hot_count = 0
        dark_count = 0
        corrected_count = 0
        for y in range(2):
            for x in range(2):
                plane = src[y::2, x::2]
                median = cv2.medianBlur(plane, int(kernel))
                if dynamic_enabled:
                    delta = plane - median
                    hot_mask = (
                        cv2.compare(delta, threshold, cv2.CMP_GT)
                        if detect_hot
                        else np.zeros(plane.shape, np.uint8)
                    )
                    dark_mask = (
                        cv2.compare(delta, -threshold, cv2.CMP_LT)
                        if detect_dark
                        else np.zeros(plane.shape, np.uint8)
                    )
                else:
                    hot_mask = np.zeros(plane.shape, np.uint8)
                    dark_mask = np.zeros(plane.shape, np.uint8)
                if static_enabled and static_map is not None:
                    static_plane = static_map[y::2, x::2]
                    hot_mask = cv2.bitwise_or(
                        hot_mask,
                        cv2.compare(static_plane, 1, cv2.CMP_EQ),
                    )
                    dark_mask = cv2.bitwise_or(
                        dark_mask,
                        cv2.compare(static_plane, 2, cv2.CMP_EQ),
                    )
                combined = cv2.bitwise_or(hot_mask, dark_mask)
                corrected_plane = plane.copy()
                cv2.copyTo(median, combined, corrected_plane)
                corrected[y::2, x::2] = corrected_plane
                defect_mask[y::2, x::2] = (
                    hot_mask // 255 + (dark_mask // 255) * 2
                )
                hot_count += cv2.countNonZero(hot_mask)
                dark_count += cv2.countNonZero(dark_mask)
                corrected_count += cv2.countNonZero(combined)
        return DPCKernelResult(
            corrected,
            defect_mask,
            int(hot_count),
            int(dark_count),
            int(corrected_count),
            OpenCVBackend.backend_id,
        )
