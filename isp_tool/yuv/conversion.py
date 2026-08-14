from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import cv2
import numpy as np

from .metadata import YUVFrame, YUVMetadata


_COEFFICIENTS = {
    "BT.601": (0.2990, 0.1140),
    "BT.709": (0.2126, 0.0722),
    "BT.2020": (0.2627, 0.0593),
}


@dataclass(frozen=True)
class YUVConversionResult:
    rgb: np.ndarray
    y_normalized: np.ndarray
    u_normalized: np.ndarray
    v_normalized: np.ndarray
    diagnostics: Dict[str, float]


def normalize_yuv_sample(
    y: float,
    u: float,
    v: float,
    metadata: YUVMetadata,
) -> Tuple[float, float, float]:
    scale = float(1 << max(metadata.bit_depth - 8, 0))
    if metadata.color_range == "Limited":
        yn = (float(y) - 16.0 * scale) / (219.0 * scale)
        un = (float(u) - 128.0 * scale) / (224.0 * scale)
        vn = (float(v) - 128.0 * scale) / (224.0 * scale)
    else:
        maximum = float((1 << metadata.bit_depth) - 1)
        midpoint = float(1 << (metadata.bit_depth - 1))
        yn = float(y) / maximum
        un = (float(u) - midpoint) / maximum
        vn = (float(v) - midpoint) / maximum
    return yn, un, vn


def upsample_planes(
    frame: YUVFrame,
    target_size: Optional[Tuple[int, int]] = None,
):
    width = frame.metadata.width
    height = frame.metadata.height
    target_width, target_height = target_size or (width, height)
    interpolation = (
        cv2.INTER_NEAREST
        if frame.metadata.chroma_upsampling == "Nearest"
        else cv2.INTER_LINEAR
    )
    y_interp = cv2.INTER_AREA if (
        target_width < width or target_height < height
    ) else cv2.INTER_LINEAR
    y = (
        frame.y.astype(np.float32, copy=False)
        if frame.y.shape == (target_height, target_width)
        else cv2.resize(
            frame.y.astype(np.float32),
            (target_width, target_height),
            interpolation=y_interp,
        )
    )
    def resize_chroma(plane):
        source = plane.astype(np.float32)
        if frame.metadata.chroma_siting == "Center":
            return cv2.resize(
                source,
                (target_width, target_height),
                interpolation=interpolation,
            )
        source_height, source_width = source.shape
        scale_x = width / source_width
        scale_y = height / source_height
        x_original = (
            (np.arange(target_width, dtype=np.float32) + 0.5)
            * (width / target_width)
            - 0.5
        )
        y_original = (
            (np.arange(target_height, dtype=np.float32) + 0.5)
            * (height / target_height)
            - 0.5
        )
        x_offset = 0.0
        y_offset = (
            0.0
            if frame.metadata.chroma_siting == "Top-left"
            else (scale_y - 1.0) * 0.5
        )
        map_x = np.broadcast_to(
            ((x_original - x_offset) / scale_x)[None, :],
            (target_height, target_width),
        ).astype(np.float32, copy=False)
        map_y = np.broadcast_to(
            ((y_original - y_offset) / scale_y)[:, None],
            (target_height, target_width),
        ).astype(np.float32, copy=False)
        return cv2.remap(
            source,
            map_x,
            map_y,
            interpolation,
            borderMode=cv2.BORDER_REPLICATE,
        )

    u = resize_chroma(frame.u)
    v = resize_chroma(frame.v)
    return y, u, v


def yuv_to_rgb(
    frame: YUVFrame,
    *,
    target_size: Optional[Tuple[int, int]] = None,
    clip: bool = False,
) -> YUVConversionResult:
    y, u, v = upsample_planes(frame, target_size)
    metadata = frame.metadata
    scale = np.float32(1 << max(metadata.bit_depth - 8, 0))
    if metadata.color_range == "Limited":
        yn = (y - 16.0 * scale) / (219.0 * scale)
        un = (u - 128.0 * scale) / (224.0 * scale)
        vn = (v - 128.0 * scale) / (224.0 * scale)
    else:
        maximum = np.float32((1 << metadata.bit_depth) - 1)
        midpoint = np.float32(1 << (metadata.bit_depth - 1))
        yn = y / maximum
        un = (u - midpoint) / maximum
        vn = (v - midpoint) / maximum
    kr, kb = _COEFFICIENTS[metadata.color_matrix]
    kg = 1.0 - kr - kb
    red = yn + (2.0 * (1.0 - kr)) * vn
    blue = yn + (2.0 * (1.0 - kb)) * un
    green = (
        yn
        - (2.0 * kb * (1.0 - kb) / kg) * un
        - (2.0 * kr * (1.0 - kr) / kg) * vn
    )
    rgb = np.stack((red, green, blue), axis=-1).astype(np.float32)
    diagnostics = {
        "negative_ratio": float(np.mean(rgb < 0.0)),
        "overflow_ratio": float(np.mean(rgb > 1.0)),
        "y_below_ratio": float(np.mean(yn < 0.0)),
        "y_above_ratio": float(np.mean(yn > 1.0)),
    }
    if clip:
        rgb = np.clip(rgb, 0.0, 1.0)
    return YUVConversionResult(
        rgb,
        yn.astype(np.float32, copy=False),
        un.astype(np.float32, copy=False),
        vn.astype(np.float32, copy=False),
        diagnostics,
    )
