from __future__ import annotations

from typing import Dict

import numpy as np

from ..analysis.histogram import (
    compute_histogram_details,
    histogram_payload_from_curves,
)
from .metadata import YUVFrame


def compute_yuv_histogram(
    frame: YUVFrame,
    rgb: np.ndarray,
    bins: int = 256,
) -> Dict[str, np.ndarray]:
    """Histogram native Y/U/V planes without reconstructing them from RGB."""
    maximum = float((1 << frame.metadata.bit_depth) - 1)
    output = {
        "Y": np.histogram(frame.y, bins=bins, range=(0, maximum))[0],
        "U": np.histogram(frame.u, bins=bins, range=(0, maximum))[0],
        "V": np.histogram(frame.v, bins=bins, range=(0, maximum))[0],
    }
    values = np.asarray(rgb, dtype=np.float32)
    for index, name in enumerate(("R", "G", "B")):
        output[name] = np.histogram(
            values[..., index], bins=bins, range=(0.0, 1.0)
        )[0]
    return output


def compute_yuv_histogram_details(
    frame: YUVFrame,
    rgb: np.ndarray,
    *,
    mode: str = "YUV 原始",
    bins: int = 256,
    roi=None,
) -> Dict[str, object]:
    """Compute native YUV or converted RGB histograms with ROI support."""

    rgb_values = np.asarray(rgb, dtype=np.float32)
    rgb_h, rgb_w = rgb_values.shape[:2]
    source_h, source_w = frame.y.shape
    if roi is not None:
        x, y, width, height = (int(value) for value in roi)
        x0 = max(0, min(rgb_w, x))
        y0 = max(0, min(rgb_h, y))
        x1 = max(x0 + 1, min(rgb_w, x + width))
        y1 = max(y0 + 1, min(rgb_h, y + height))
        rgb_values = rgb_values[y0:y1, x0:x1]
        sx0 = int(np.floor(x0 * source_w / max(rgb_w, 1)))
        sy0 = int(np.floor(y0 * source_h / max(rgb_h, 1)))
        sx1 = int(np.ceil(x1 * source_w / max(rgb_w, 1)))
        sy1 = int(np.ceil(y1 * source_h / max(rgb_h, 1)))
        sx1 = max(sx0 + 1, min(source_w, sx1))
        sy1 = max(sy0 + 1, min(source_h, sy1))
    else:
        sx0 = sy0 = 0
        sx1, sy1 = source_w, source_h

    if mode != "YUV 原始":
        return compute_histogram_details(
            rgb_values,
            "rgb",
            frame.metadata,
            mode=mode,
            bins=bins,
        )

    def crop_plane(plane):
        plane_h, plane_w = plane.shape
        px0 = int(np.floor(sx0 * plane_w / max(source_w, 1)))
        py0 = int(np.floor(sy0 * plane_h / max(source_h, 1)))
        px1 = int(np.ceil(sx1 * plane_w / max(source_w, 1)))
        py1 = int(np.ceil(sy1 * plane_h / max(source_h, 1)))
        px1 = max(px0 + 1, min(plane_w, px1))
        py1 = max(py0 + 1, min(plane_h, py1))
        return plane[py0:py1, px0:px1]

    y_values = crop_plane(frame.y)
    u_values = crop_plane(frame.u)
    v_values = crop_plane(frame.v)
    code_max = (1 << frame.metadata.bit_depth) - 1
    legal_ranges = {}
    if frame.metadata.color_range == "Limited":
        scale = 1 << max(frame.metadata.bit_depth - 8, 0)
        legal_ranges = {
            "Y": (16 * scale, 235 * scale),
            "U": (16 * scale, 240 * scale),
            "V": (16 * scale, 240 * scale),
        }
    return histogram_payload_from_curves(
        {"Y": y_values, "U": u_values, "V": v_values},
        code_max,
        mode=mode,
        bins=bins,
        exposure_reference=y_values,
        legal_ranges=legal_ranges,
    )
