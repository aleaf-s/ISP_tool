from __future__ import annotations

from typing import Any, Dict, Tuple

import cv2
import numpy as np

from ..bayer import split_planes
from ..models import ISPError, LSCMesh, RawMetadata


def _trimmed_mean(values: np.ndarray, trim_fraction: float) -> float:
    flattened = np.sort(np.asarray(values, dtype=np.float32).ravel())
    trim = int(flattened.size * np.clip(trim_fraction, 0, 0.4))
    if trim and flattened.size > trim * 2:
        flattened = flattened[trim:-trim]
    return float(np.mean(flattened))


def _grid_measurements(
    plane: np.ndarray,
    rows: int,
    cols: int,
    statistic: str,
    trim_fraction: float,
) -> np.ndarray:
    height, width = plane.shape
    y_edges = np.linspace(0, height, rows + 1).astype(int)
    x_edges = np.linspace(0, width, cols + 1).astype(int)
    measured = np.empty((rows, cols), np.float32)
    for row in range(rows):
        for col in range(cols):
            cell = plane[y_edges[row]:y_edges[row + 1], x_edges[col]:x_edges[col + 1]]
            if cell.size < 4:
                raise ISPError("平场图尺寸相对于 Mesh 网格过小")
            measured[row, col] = (
                np.median(cell)
                if statistic == "Median"
                else _trimmed_mean(cell, trim_fraction)
            )
    return measured


def generate_lsc_mesh(
    bayer_image: np.ndarray,
    metadata: RawMetadata,
    rows: int = 13,
    cols: int = 17,
    statistic: str = "Median",
    reference: str = "Center",
    trim_fraction: float = 0.05,
    smoothing: float = 0.7,
    gain_limit: float = 4.0,
) -> Tuple[LSCMesh, Dict[str, Any], Dict[str, np.ndarray]]:
    src = np.asarray(bayer_image, dtype=np.float32)
    if src.ndim != 2:
        raise ISPError("LSC 平场校准需要 Bayer 单通道图像")
    if not np.all(np.isfinite(src)):
        raise ISPError("平场图包含 NaN 或 Infinity")
    if float(np.mean(src >= 0.995)) > 0.02:
        raise ISPError("平场图过曝像素超过 2%")
    if float(np.median(src)) < 0.02:
        raise ISPError("平场图亮度过低")
    if rows < 2 or cols < 2:
        raise ISPError("Mesh 网格至少为 2×2")

    measured_channels = {}
    gain_channels = {}
    before_cv = {}
    after_cv = {}
    for name, plane in split_planes(src, metadata.bayer_pattern).items():
        measured = _grid_measurements(
            plane, rows, cols, statistic, trim_fraction
        )
        if np.any(measured <= 1e-8):
            raise ISPError(f"平场图 {name} 包含接近零亮度的网格")
        if reference == "Maximum":
            reference_value = float(np.percentile(measured, 95))
        else:
            y0, x0 = rows // 2, cols // 2
            reference_value = float(measured[y0, x0])
        gain = reference_value / measured
        if smoothing > 0:
            smoothed = cv2.GaussianBlur(gain, (0, 0), float(smoothing))
            gain = 0.25 * gain + 0.75 * smoothed
        gain = np.clip(gain, 1.0 / gain_limit, gain_limit).astype(np.float32)
        corrected = measured * gain
        measured_channels[name] = measured
        gain_channels[name] = gain
        before_cv[name] = float(np.std(measured) / max(np.mean(measured), 1e-8))
        after_cv[name] = float(np.std(corrected) / max(np.mean(corrected), 1e-8))

    mesh = LSCMesh(
        rows,
        cols,
        gain_channels["R"],
        gain_channels["Gr"],
        gain_channels["Gb"],
        gain_channels["B"],
        center_normalized=(reference == "Center"),
        source="flat_field",
        metadata={
            "statistic": statistic,
            "reference": reference,
            "smoothing": smoothing,
        },
    )
    diagnostics = {
        "uniformity_cv_before": before_cv,
        "uniformity_cv_after": after_cv,
        "mean_cv_before": float(np.mean(list(before_cv.values()))),
        "mean_cv_after": float(np.mean(list(after_cv.values()))),
    }
    artifacts = {
        f"{name} Illumination Mesh": value
        for name, value in measured_channels.items()
    }
    return mesh, diagnostics, artifacts

