from __future__ import annotations

from pathlib import Path
from typing import Dict

import cv2
import numpy as np

from .bayer import channel_positions
from .models import RawMetadata

try:
    import tifffile
except ImportError:  # pragma: no cover
    tifffile = None


def bayer_false_color(image: np.ndarray, metadata: RawMetadata) -> np.ndarray:
    src = np.asarray(image, dtype=np.float32)
    if src.max(initial=0.0) > 2.0:
        black = min(metadata.black_level)
        src = (src - black) / max(metadata.white_level - black, 1.0)
    rgb = np.zeros((*src.shape, 3), np.float32)
    positions = channel_positions(metadata.bayer_pattern)
    for name, (y, x) in positions.items():
        channel = {"R": 0, "Gr": 1, "Gb": 1, "B": 2}[name]
        rgb[y::2, x::2, channel] = src[y::2, x::2]
    # Enlarge sparse CFA samples only for visual interpretation.
    rgb = cv2.GaussianBlur(rgb, (3, 3), 0) * 4.0
    return np.clip(rgb, 0.0, 1.0)


def display_rgb(image: np.ndarray, domain: str, metadata: RawMetadata) -> np.ndarray:
    src = np.asarray(image, dtype=np.float32)
    if domain == "bayer":
        return bayer_false_color(src, metadata)
    if src.ndim == 2:
        return np.repeat(np.clip(src, 0, 1)[..., None], 3, axis=2)
    return np.clip(src[:, :, :3], 0.0, 1.0)


def to_uint8(image: np.ndarray, domain: str, metadata: RawMetadata) -> np.ndarray:
    return np.round(display_rgb(image, domain, metadata) * 255.0).astype(np.uint8)


def histogram(image: np.ndarray, domain: str, metadata: RawMetadata) -> Dict[str, np.ndarray]:
    # Backward-compatible wrapper; analysis code now lives in its own package.
    from .analysis.histogram import compute_histogram
    return compute_histogram(image, domain, metadata)


def artifact_to_rgb(name: str, artifact: np.ndarray) -> np.ndarray:
    value = np.asarray(artifact)
    if name == "Defect Mask":
        rgb = np.zeros((*value.shape[:2], 3), np.float32)
        rgb[value == 1] = (1.0, 0.12, 0.05)
        rgb[value == 2] = (0.05, 0.35, 1.0)
        rgb[value >= 3] = (1.0, 0.0, 1.0)
        return rgb
    if name == "LSC Gain Map":
        scalar = value.astype(np.float32)
        low, high = float(scalar.min(initial=0.0)), float(scalar.max(initial=1.0))
        normalized = (scalar - low) / max(high - low, 1e-8)
        colored = cv2.applyColorMap(
            np.round(normalized * 255).astype(np.uint8), cv2.COLORMAP_TURBO
        )
        return cv2.cvtColor(colored, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    scalar = value[:, :, 0] if value.ndim == 3 else value
    scalar = scalar.astype(np.float32)
    if scalar.max(initial=0.0) > 1:
        scalar /= max(float(scalar.max()), 1.0)
    return np.repeat(np.clip(scalar, 0, 1)[:, :, None], 3, axis=2)


def export_image(path: str, image: np.ndarray, domain: str, metadata: RawMetadata) -> None:
    rgb = display_rgb(image, domain, metadata)
    suffix = Path(path).suffix.lower()
    if suffix in {".tif", ".tiff"} and tifffile is not None:
        tifffile.imwrite(path, np.round(rgb * 65535.0).astype(np.uint16), photometric="rgb")
    else:
        bgr = cv2.cvtColor(np.round(rgb * 255.0).astype(np.uint8), cv2.COLOR_RGB2BGR)
        if not cv2.imwrite(path, bgr):
            raise RuntimeError(f"无法导出图像：{path}")
