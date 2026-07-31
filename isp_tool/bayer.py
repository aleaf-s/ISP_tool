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
    positions = channel_positions(pattern)
    kernels = {
        "R": np.array([[1, 2, 1], [2, 4, 2], [1, 2, 1]], np.float32),
        "G": np.array([[0, 1, 0], [1, 4, 1], [0, 1, 0]], np.float32),
        "B": np.array([[1, 2, 1], [2, 4, 2], [1, 2, 1]], np.float32),
    }
    rgb_channels = []
    for channel in ("R", "G", "B"):
        sampled = np.zeros_like(src)
        if channel == "G":
            for green in ("Gr", "Gb"):
                y, x = positions[green]
                sampled[y::2, x::2] = src[y::2, x::2]
        else:
            y, x = positions[channel]
            sampled[y::2, x::2] = src[y::2, x::2]
        kernel = kernels[channel]
        # For a 2x2 Bayer lattice these interpolation kernels, together with
        # REFLECT_101 borders, have a constant normalization denominator of 4.
        # Avoid rebuilding masks and filtering three invariant denominator
        # images on every preview refresh.
        numerator = cv2.filter2D(
            sampled, -1, kernel, borderType=cv2.BORDER_REFLECT_101
        )
        rgb_channels.append(numerator * 0.25)
    return np.stack(rgb_channels, axis=-1).astype(np.float32, copy=False)


def _nearest_lattice_plane(
    src: np.ndarray,
    position: Tuple[int, int],
) -> tuple[np.ndarray, np.ndarray]:
    """Expand one CFA lattice to full resolution with nearest-neighbour lookup."""
    height, width = src.shape
    y0, x0 = position
    rows = np.arange(y0, height, 2)
    columns = np.arange(x0, width, 2)
    if rows.size == 0 or columns.size == 0:
        empty = np.zeros_like(src, dtype=np.float32)
        distance = np.full(src.shape, np.inf, dtype=np.float32)
        return empty, distance

    y_index = np.floor(
        (np.arange(height, dtype=np.float32) - y0) * 0.5 + 0.5
    ).astype(np.intp)
    x_index = np.floor(
        (np.arange(width, dtype=np.float32) - x0) * 0.5 + 0.5
    ).astype(np.intp)
    np.clip(y_index, 0, rows.size - 1, out=y_index)
    np.clip(x_index, 0, columns.size - 1, out=x_index)
    nearest_rows = rows[y_index]
    nearest_columns = columns[x_index]
    plane = src[np.ix_(nearest_rows, nearest_columns)]
    distance = (
        (np.arange(height) - nearest_rows)[:, None] ** 2
        + (np.arange(width) - nearest_columns)[None, :] ** 2
    )
    return (
        np.asarray(plane, dtype=np.float32),
        np.asarray(distance, dtype=np.float32),
    )


def bayer_to_rgb_nearest(image: np.ndarray, pattern: str) -> np.ndarray:
    """Nearest-neighbour demosaic that preserves every measured CFA sample."""
    src = np.asarray(image, dtype=np.float32)
    positions = channel_positions(pattern)
    red, _ = _nearest_lattice_plane(src, positions["R"])
    blue, _ = _nearest_lattice_plane(src, positions["B"])
    green_r, distance_r = _nearest_lattice_plane(src, positions["Gr"])
    green_b, distance_b = _nearest_lattice_plane(src, positions["Gb"])
    green = np.where(
        distance_r < distance_b,
        green_r,
        np.where(distance_b < distance_r, green_b, 0.5 * (green_r + green_b)),
    )
    return np.stack((red, green, blue), axis=-1).astype(
        np.float32, copy=False
    )


def bayer_to_rgb_adaptive(image: np.ndarray, pattern: str) -> np.ndarray:
    """Directional adaptive interpolation.

    Red and blue start from bilinear interpolation. Green values at red/blue
    sites select the smoother of the horizontal and vertical directions using
    first- and second-order Bayer gradients.
    """
    src = np.asarray(image, dtype=np.float32)
    output = bayer_to_rgb_bilinear(src, pattern)
    padded = np.pad(src, 2, mode="reflect")
    center = padded[2:-2, 2:-2]
    left = padded[2:-2, 1:-3]
    right = padded[2:-2, 3:-1]
    up = padded[1:-3, 2:-2]
    down = padded[3:-1, 2:-2]
    left2 = padded[2:-2, :-4]
    right2 = padded[2:-2, 4:]
    up2 = padded[:-4, 2:-2]
    down2 = padded[4:, 2:-2]

    horizontal = 0.5 * (left + right)
    vertical = 0.5 * (up + down)
    horizontal_gradient = (
        np.abs(left - right)
        + np.abs(2.0 * center - left2 - right2)
    )
    vertical_gradient = (
        np.abs(up - down)
        + np.abs(2.0 * center - up2 - down2)
    )
    adaptive_green = np.where(
        horizontal_gradient < vertical_gradient,
        horizontal,
        np.where(
            vertical_gradient < horizontal_gradient,
            vertical,
            0.5 * (horizontal + vertical),
        ),
    )
    cfa_masks = masks(src.shape, pattern)
    red_or_blue = cfa_masks["R"] | cfa_masks["B"]
    output[..., 1][red_or_blue] = adaptive_green[red_or_blue]
    return output.astype(np.float32, copy=False)


def bayer_to_rgb_constant_color_difference(
    image: np.ndarray,
    pattern: str,
) -> np.ndarray:
    """Demosaic using locally smooth R-G and B-G color differences."""
    src = np.asarray(image, dtype=np.float32)
    output = bayer_to_rgb_adaptive(src, pattern)
    green = output[..., 1]
    positions = channel_positions(pattern)
    kernel = np.array(
        [[1, 2, 1], [2, 4, 2], [1, 2, 1]],
        dtype=np.float32,
    )
    for output_index, channel in ((0, "R"), (2, "B")):
        sampled_difference = np.zeros_like(src, dtype=np.float32)
        y, x = positions[channel]
        sampled_difference[y::2, x::2] = (
            src[y::2, x::2] - green[y::2, x::2]
        )
        difference = cv2.filter2D(
            sampled_difference,
            -1,
            kernel,
            borderType=cv2.BORDER_REFLECT_101,
        ) * 0.25
        output[..., output_index] = green + difference
        output[y::2, x::2, output_index] = src[y::2, x::2]
    return output.astype(np.float32, copy=False)


def bayer_to_rgb_opencv_bilinear(image: np.ndarray, pattern: str) -> np.ndarray:
    """Fast OpenCV bilinear demosaic with adaptive uint16 scaling.

    This path is intended for interactive preview. It preserves values above
    one by scaling against the current Bayer maximum before uint16 conversion.
    The outermost border follows OpenCV's interpolation convention and may
    differ from the exact normalized-convolution implementation above.
    """
    src = np.asarray(image, dtype=np.float32)
    scale = max(float(src.max(initial=1.0)), 1.0)
    src16 = np.round(
        np.clip(src, 0.0, scale) * (65535.0 / scale)
    ).astype(np.uint16)
    codes = {
        "RGGB": cv2.COLOR_BayerRG2BGR,
        "GRBG": cv2.COLOR_BayerGR2BGR,
        "GBRG": cv2.COLOR_BayerGB2BGR,
        "BGGR": cv2.COLOR_BayerBG2BGR,
    }
    return (
        cv2.cvtColor(src16, codes[pattern]).astype(np.float32)
        * (scale / 65535.0)
    )


def bayer_to_rgb_edge_aware(image: np.ndarray, pattern: str) -> np.ndarray:
    """Deprecated compatibility alias for adaptive interpolation."""
    return bayer_to_rgb_adaptive(image, pattern)
