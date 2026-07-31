from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np


BACKEND_ABI_VERSION = 1


@dataclass(frozen=True)
class DemosaicKernelResult:
    image: np.ndarray
    implementation: str


@dataclass(frozen=True)
class DPCKernelResult:
    corrected: np.ndarray
    defect_mask: np.ndarray
    hot_count: int
    dark_count: int
    corrected_count: int
    implementation: str


class ProcessingBackend:
    """UI-independent execution backend used by hot ISP kernels."""

    backend_id = "base"
    name = "Base"
    is_native = False

    @property
    def cache_key(self) -> str:
        """Stable key used to keep pipeline caches backend-safe."""

        return self.backend_id

    @property
    def capabilities(self):
        return ()

    def demosaic(
        self, image: np.ndarray, pattern: str, algorithm: str
    ) -> DemosaicKernelResult:
        raise NotImplementedError

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
        raise NotImplementedError
