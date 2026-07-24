from __future__ import annotations

from typing import Dict, Tuple

import cv2
import numpy as np

from .models import ISPError


PATTERNS = {"RGGB", "GRBG", "GBRG", "BGGR"}


def channel_positions(pattern: str) -> Dict[str, Tuple[int, int]]:
    pattern = pattern.upper()
    if pattern not in PATTERNS:
        raise ISPError(f"未知 Bayer Pattern：{pattern}")
    chars = ((pattern[0], pattern[1]), (pattern[2], pattern[3]))
    green_positions = [(y, x) for y in range(2) for x in range(2) if chars[y][x] == "G"]
    # Gr is the green on the red row, Gb is the green on the blue row.
    r_pos = next((y, x) for y in range(2) for x in range(2) if chars[y][x] == "R")
    b_pos = next((y, x) for y in range(2) for x in range(2) if chars[y][x] == "B")
    gr = next(pos for pos in green_positions if pos[0] == r_pos[0])
    gb = next(pos for pos in green_positions if pos[0] == b_pos[0])
    return {"R": r_pos, "Gr": gr, "Gb": gb, "B": b_pos}


def masks(shape: Tuple[int, int], pattern: str) -> Dict[str, np.ndarray]:
    output: Dict[str, np.ndarray] = {}
    for name, (y, x) in channel_positions(pattern).items():
        mask = np.zeros(shape, dtype=bool)
        mask[y::2, x::2] = True
        output[name] = mask
    return output


def apply_per_channel(image: np.ndarray, pattern: str, values: Dict[str, float]) -> np.ndarray:
    output = np.asarray(image, dtype=np.float32).copy()
    for name, (y, x) in channel_positions(pattern).items():
        output[y::2, x::2] *= float(values[name])
    return output


def split_planes(image: np.ndarray, pattern: str) -> Dict[str, np.ndarray]:
    return {
        name: image[y::2, x::2]
        for name, (y, x) in channel_positions(pattern).items()
    }


def merge_planes(planes: Dict[str, np.ndarray], pattern: str) -> np.ndarray:
    first = next(iter(planes.values()))
    height, width = first.shape[:2]
    output = np.zeros((height * 2, width * 2), dtype=np.float32)
    for name, (y, x) in channel_positions(pattern).items():
        output[y::2, x::2] = planes[name]
    return output


def resize_bayer_preview(image: np.ndarray, pattern: str, max_side: int = 1400) -> np.ndarray:
    """Resize each CFA plane independently, preserving the 2x2 mosaic layout."""
    height, width = image.shape
    if max(height, width) <= max_side:
        return np.asarray(image, dtype=np.float32).copy()
    scale = max_side / max(height, width)
    target_h = max(2, (int(height * scale) // 2) * 2)
    target_w = max(2, (int(width * scale) // 2) * 2)
    plane_h, plane_w = target_h // 2, target_w // 2
    resized = {
        name: cv2.resize(
            np.asarray(plane, dtype=np.float32),
            (plane_w, plane_h),
            interpolation=cv2.INTER_AREA,
        )
        for name, plane in split_planes(image, pattern).items()
    }
    return merge_planes(resized, pattern)


def bayer_to_rgb_bilinear(image: np.ndarray, pattern: str) -> np.ndarray:
    """Normalized-convolution bilinear demosaic; output is RGB float32."""
    src = np.asarray(image, dtype=np.float32)
    cfa_masks = masks(src.shape, pattern)
    kernels = {
        "R": np.array([[1, 2, 1], [2, 4, 2], [1, 2, 1]], np.float32),
        "G": np.array([[0, 1, 0], [1, 4, 1], [0, 1, 0]], np.float32),
        "B": np.array([[1, 2, 1], [2, 4, 2], [1, 2, 1]], np.float32),
    }
    rgb_channels = []
    for channel in ("R", "G", "B"):
        if channel == "G":
            mask = cfa_masks["Gr"] | cfa_masks["Gb"]
        else:
            mask = cfa_masks[channel]
        weights = mask.astype(np.float32)
        kernel = kernels[channel]
        numerator = cv2.filter2D(src * weights, -1, kernel, borderType=cv2.BORDER_REFLECT_101)
        denominator = cv2.filter2D(weights, -1, kernel, borderType=cv2.BORDER_REFLECT_101)
        rgb_channels.append(numerator / np.maximum(denominator, 1e-8))
    return np.stack(rgb_channels, axis=-1).astype(np.float32)


def bayer_to_rgb_edge_aware(image: np.ndarray, pattern: str) -> np.ndarray:
    src16 = np.clip(np.asarray(image) * 65535.0, 0, 65535).astype(np.uint16)
    # OpenCV's Bayer*2BGR constants produce channel order R,G,B for a mosaic
    # whose pattern is named from the top-left pixel. Verify this explicitly in
    # tests because the constant naming is otherwise easy to misinterpret.
    codes = {
        "RGGB": cv2.COLOR_BayerRG2BGR_EA,
        "GRBG": cv2.COLOR_BayerGR2BGR_EA,
        "GBRG": cv2.COLOR_BayerGB2BGR_EA,
        "BGGR": cv2.COLOR_BayerBG2BGR_EA,
    }
    return cv2.cvtColor(src16, codes[pattern]).astype(np.float32) / 65535.0
