from __future__ import annotations

from typing import Dict, Tuple

import numpy as np

from ..models import ISPError

try:
    import colour
except ImportError:  # pragma: no cover
    colour = None


SRGB_TO_XYZ = np.array([
    [0.4124564, 0.3575761, 0.1804375],
    [0.2126729, 0.7151522, 0.0721750],
    [0.0193339, 0.1191920, 0.9503041],
], dtype=np.float64)
D65_XY = np.array([0.3127, 0.3290], dtype=np.float64)


def linear_srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    if colour is None:
        raise ISPError("缺少 colour-science，无法计算 Lab/ΔE")
    values = np.asarray(rgb, dtype=np.float64)
    xyz = np.einsum("...c,dc->...d", values, SRGB_TO_XYZ)
    return np.asarray(colour.XYZ_to_Lab(xyz, illuminant=D65_XY), dtype=np.float64)


def delta_e_values(
    measured_linear_rgb: np.ndarray,
    reference_linear_rgb: np.ndarray,
    method: str = "CIE 2000",
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    if colour is None:
        raise ISPError("缺少 colour-science，无法计算 ΔE")
    measured_lab = linear_srgb_to_lab(measured_linear_rgb)
    reference_lab = linear_srgb_to_lab(reference_linear_rgb)
    delta = np.asarray(
        colour.delta_E(measured_lab, reference_lab, method=method),
        dtype=np.float64,
    )
    return delta, measured_lab, reference_lab


def summarize_delta_e(values: np.ndarray) -> Dict[str, float]:
    delta = np.asarray(values, dtype=np.float64)
    if delta.size == 0:
        return {"mean": 0.0, "median": 0.0, "max": 0.0, "p90": 0.0}
    return {
        "mean": float(np.mean(delta)),
        "median": float(np.median(delta)),
        "max": float(np.max(delta)),
        "p90": float(np.percentile(delta, 90)),
    }

