from __future__ import annotations

from typing import Any, Dict

import numpy as np

from ..bayer import split_planes
from ..models import RawMetadata, StageDataState
from ..preview import display_rgb


def _describe(values: np.ndarray) -> Dict[str, float]:
    finite = np.asarray(values, dtype=np.float32)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return {
            "mean": 0.0, "median": 0.0, "std": 0.0,
            "min": 0.0, "max": 0.0,
        }
    return {
        "mean": float(np.mean(finite)),
        "median": float(np.median(finite)),
        "std": float(np.std(finite)),
        "min": float(np.min(finite)),
        "max": float(np.max(finite)),
    }


def compute_statistics(
    image: np.ndarray,
    domain: str,
    metadata: RawMetadata,
    data_state: StageDataState | None = None,
) -> Dict[str, Any]:
    src = np.asarray(image, dtype=np.float32)
    if domain == "bayer":
        channels = {
            name: _describe(plane)
            for name, plane in split_planes(src, metadata.bayer_pattern).items()
        }
        maximum = (
            data_state.display_divisor
            if data_state is not None
            else max(float(metadata.white_level), 1.0)
            if src.max(initial=0.0) > 2 else 1.0
        )
        normalized = np.clip(src / maximum, 0, 1)
    else:
        rgb = display_rgb(src, domain, metadata, data_state=data_state)
        channels = {
            name: _describe(rgb[:, :, index])
            for index, name in enumerate(("R", "G", "B"))
        }
        normalized = rgb
    return {
        "domain": domain,
        "channels": channels,
        "clipped_high": float(np.mean(normalized >= 0.999)),
        "clipped_low": float(np.mean(normalized <= 0.001)),
        "range_usage": float(np.max(normalized) - np.min(normalized)),
        "shape": tuple(src.shape),
    }
