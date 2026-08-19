from __future__ import annotations

from typing import Tuple

import cv2
import numpy as np

from ..models import ISPError, RawMetadata, StageDataState
from ..preview import bayer_cell_rgb, display_rgb


def vectorscope_coordinates(
    rgb: np.ndarray,
    mode: str = "YCbCr",
) -> Tuple[np.ndarray, np.ndarray, Tuple[float, float]]:
    values = np.asarray(rgb, dtype=np.float32)
    if values.ndim < 2 or values.shape[-1] < 3:
        raise ISPError("Vectorscope 输入必须是 RGB")
    values = np.clip(values[..., :3], 0, 1)
    if mode == "YCbCr":
        r, g, b = values[..., 0], values[..., 1], values[..., 2]
        y = 0.2126 * r + 0.7152 * g + 0.0722 * b
        cb = (b - y) / 1.8556
        cr = (r - y) / 1.5748
        return np.clip(cb + 0.5, 0, 1), np.clip(cr + 0.5, 0, 1), (0.5, 0.5)
    if mode == "CIE 1976 u'v'":
        matrix = np.array([
            [0.4124564, 0.3575761, 0.1804375],
            [0.2126729, 0.7151522, 0.0721750],
            [0.0193339, 0.1191920, 0.9503041],
        ], np.float32)
        xyz = np.einsum("...c,dc->...d", values, matrix)
        denominator = xyz[..., 0] + 15 * xyz[..., 1] + 3 * xyz[..., 2]
        u = 4 * xyz[..., 0] / np.maximum(denominator, 1e-8)
        v = 9 * xyz[..., 1] / np.maximum(denominator, 1e-8)
        # The useful u'v' gamut occupies roughly [0, .65]².
        return np.clip(u / 0.65, 0, 1), np.clip(v / 0.65, 0, 1), (
            0.19783 / 0.65,
            0.46832 / 0.65,
        )
    raise ISPError(f"未知 Vectorscope 模式：{mode}")


def compute_vectorscope(
    image: np.ndarray,
    domain: str,
    metadata: RawMetadata,
    mode: str = "YCbCr",
    size: int = 256,
    saturation_scale: float = 1.0,
    max_samples: int = 200000,
    data_state: StageDataState | None = None,
) -> np.ndarray:
    size = max(96, int(size))
    rgb = (
        bayer_cell_rgb(
            image, metadata,
            already_normalized=(
                data_state.normalized if data_state is not None else None
            ),
        )
        if domain == "bayer"
        else display_rgb(image, domain, metadata, data_state=data_state)
    )
    flat = rgb.reshape(-1, 3)
    if len(flat) > max_samples:
        step = int(np.ceil(len(flat) / max_samples))
        flat = flat[::step]
    x, y, center = vectorscope_coordinates(flat, mode)
    scale = max(float(saturation_scale), 0.1)
    x = center[0] + (x - center[0]) * scale
    y = center[1] + (y - center[1]) * scale
    px = np.clip(np.round(x * (size - 1)).astype(int), 0, size - 1)
    py = np.clip(np.round((1 - y) * (size - 1)).astype(int), 0, size - 1)
    density = np.zeros((size, size), np.float32)
    np.add.at(density, (py, px), 1.0)
    density = np.log1p(density)
    density /= max(float(density.max(initial=1.0)), 1e-8)
    output = np.zeros((size, size, 3), np.float32)
    output[..., 0] = density * 0.25
    output[..., 1] = density * 0.95
    output[..., 2] = density

    canvas = np.round(output * 255).astype(np.uint8)
    center_px = (int(center[0] * (size - 1)), int((1 - center[1]) * (size - 1)))
    cv2.line(canvas, (center_px[0], 0), (center_px[0], size - 1), (45, 45, 45), 1)
    cv2.line(canvas, (0, center_px[1]), (size - 1, center_px[1]), (45, 45, 45), 1)
    cv2.circle(canvas, center_px, max(2, size // 64), (200, 200, 200), 1)

    # Target directions are computed through the same coordinate transform.
    target_rgb = np.array([
        [1, 0, 0], [0, 1, 0], [0, 0, 1],
        [0, 1, 1], [1, 0, 1], [1, 1, 0],
    ], np.float32)
    labels = ("R", "G", "B", "C", "M", "Y")
    tx, ty, _ = vectorscope_coordinates(target_rgb, mode)
    for label, target_x, target_y in zip(labels, tx, ty):
        point = (
            int(np.clip(target_x, 0, 1) * (size - 1)),
            int((1 - np.clip(target_y, 0, 1)) * (size - 1)),
        )
        cv2.circle(canvas, point, max(3, size // 48), (100, 100, 100), 1)
        cv2.putText(
            canvas, label, (point[0] + 3, point[1] - 3),
            cv2.FONT_HERSHEY_SIMPLEX, 0.3, (180, 180, 180), 1, cv2.LINE_AA,
        )
    # Approximate skin-tone direction in YCbCr; in u'v' draw toward warm skin.
    skin_rgb = np.array([[0.76, 0.50, 0.38]], np.float32)
    sx, sy, _ = vectorscope_coordinates(skin_rgb, mode)
    skin_point = (int(sx[0] * (size - 1)), int((1 - sy[0]) * (size - 1)))
    cv2.line(canvas, center_px, skin_point, (80, 110, 180), 1, cv2.LINE_AA)
    return canvas.astype(np.float32) / 255.0
