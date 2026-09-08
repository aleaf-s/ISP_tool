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


def lab_to_lch(lab: np.ndarray) -> np.ndarray:
    """Convert CIE Lab to L*, C*ab and h(ab) in degrees.

    Hue is returned in the closed-open interval [0, 360).  Keeping this
    conversion here gives the solver and UI one shared definition instead of
    letting individual views implement subtly different angle wrapping.
    """

    values = np.asarray(lab, dtype=np.float64)
    if values.shape[-1:] != (3,):
        raise ISPError("Lab 数据最后一维必须包含 L、a、b 三个分量")
    chroma = np.hypot(values[..., 1], values[..., 2])
    hue = np.mod(
        np.degrees(np.arctan2(values[..., 2], values[..., 1])),
        360.0,
    )
    return np.stack((values[..., 0], chroma, hue), axis=-1)


def delta_lch_components(
    measured_lab: np.ndarray,
    reference_lab: np.ndarray,
    hue_chroma_threshold: float = 2.0,
) -> Dict[str, np.ndarray]:
    """Return signed L/C/H differences with correct circular hue handling.

    ``delta_h_degrees`` is the shortest signed angular difference. ``delta_h``
    is the CIE hue-difference component in Lab units and is therefore suitable
    for comparing with ΔL* and ΔC*.  Hue angle is flagged as undefined for very
    low-chroma patches, where a large angle change is visually meaningless.
    """

    measured = np.asarray(measured_lab, dtype=np.float64)
    reference = np.asarray(reference_lab, dtype=np.float64)
    if measured.shape != reference.shape or measured.shape[-1:] != (3,):
        raise ISPError("L/C/H 差异计算需要形状相同的 Lab 数组")
    measured_lch = lab_to_lch(measured)
    reference_lch = lab_to_lch(reference)
    delta_h_degrees = (
        measured_lch[..., 2] - reference_lch[..., 2] + 180.0
    ) % 360.0 - 180.0
    delta_h = (
        2.0
        * np.sqrt(
            np.maximum(measured_lch[..., 1] * reference_lch[..., 1], 0.0)
        )
        * np.sin(np.radians(delta_h_degrees) / 2.0)
    )
    hue_defined = (
        np.minimum(measured_lch[..., 1], reference_lch[..., 1])
        >= max(float(hue_chroma_threshold), 0.0)
    )
    delta_h = np.where(hue_defined, delta_h, 0.0)
    return {
        "measured_lch": measured_lch,
        "reference_lch": reference_lch,
        "delta_l": measured_lch[..., 0] - reference_lch[..., 0],
        "delta_c": measured_lch[..., 1] - reference_lch[..., 1],
        "delta_h": delta_h,
        "delta_h_degrees": delta_h_degrees,
        "hue_defined": hue_defined,
    }


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


def summarize_component(values: np.ndarray) -> Dict[str, float]:
    """Summarise a signed error component without losing its bias."""

    data = np.asarray(values, dtype=np.float64)
    if data.size == 0:
        return {"mean": 0.0, "mean_abs": 0.0, "max_abs": 0.0}
    finite = data[np.isfinite(data)]
    if finite.size == 0:
        return {"mean": 0.0, "mean_abs": 0.0, "max_abs": 0.0}
    return {
        "mean": float(np.mean(finite)),
        "mean_abs": float(np.mean(np.abs(finite))),
        "max_abs": float(np.max(np.abs(finite))),
    }
