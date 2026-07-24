from __future__ import annotations

import cv2
import numpy as np

from ..models import RawMetadata
from ..preview import display_rgb


def _density(channel: np.ndarray, width: int, height: int) -> np.ndarray:
    src = np.asarray(channel, dtype=np.float32)
    if src.shape[1] != width:
        new_height = max(1, int(src.shape[0] * width / max(src.shape[1], 1)))
        src = cv2.resize(src, (width, new_height), interpolation=cv2.INTER_AREA)
    if src.shape[0] > 720:
        src = cv2.resize(src, (width, 720), interpolation=cv2.INTER_AREA)
    bins = np.clip(np.round(src * (height - 1)).astype(np.int32), 0, height - 1)
    output = np.zeros((height, width), np.float32)
    x_indices = np.broadcast_to(np.arange(width, dtype=np.int32), bins.shape)
    np.add.at(output, (height - 1 - bins.ravel(), x_indices.ravel()), 1.0)
    output = np.log1p(output)
    maximum = float(output.max(initial=1.0))
    return output / max(maximum, 1e-9)


def compute_waveform(
    image: np.ndarray,
    domain: str,
    metadata: RawMetadata,
    mode: str = "RGB Overlay",
    width: int = 512,
    height: int = 256,
) -> np.ndarray:
    """Return a display-ready float RGB waveform image in [0, 1]."""
    width = max(48, int(width))
    height = max(32, int(height))
    rgb = display_rgb(image, domain, metadata)
    if mode == "Luma":
        y = np.sum(rgb * np.array([0.2126, 0.7152, 0.0722], np.float32), axis=2)
        density = _density(y, width, height)
        return np.repeat(density[:, :, None], 3, axis=2)
    if mode == "RGB Parade":
        output = np.zeros((height, width, 3), np.float32)
        bounds = (0, width // 3, (2 * width) // 3, width)
        for index in range(3):
            segment = bounds[index + 1] - bounds[index]
            output[:, bounds[index]:bounds[index + 1], index] = _density(
                rgb[:, :, index], segment, height
            )
        return output
    output = np.zeros((height, width, 3), np.float32)
    for index in range(3):
        output[:, :, index] = _density(rgb[:, :, index], width, height)
    return np.clip(output, 0, 1)
