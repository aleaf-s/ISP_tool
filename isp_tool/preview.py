from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

import cv2
import numpy as np

from .bayer import channel_positions
from .models import RawMetadata, StageDataState

try:
    import tifffile
except ImportError:  # pragma: no cover
    tifffile = None

_DISPLAY_LUT_SIZE = 4096
_DISPLAY_LUT_INPUT = np.linspace(
    0.0, 1.0, _DISPLAY_LUT_SIZE, dtype=np.float32
)
_DISPLAY_LUT_UINT8 = np.round(
    np.where(
        _DISPLAY_LUT_INPUT <= 0.0031308,
        _DISPLAY_LUT_INPUT * 12.92,
        1.055
        * np.power(_DISPLAY_LUT_INPUT, 1.0 / 2.4)
        - 0.055,
    )
    * 255.0
).astype(np.uint8)


def _normalize_bayer_for_display(
    image: np.ndarray,
    metadata: RawMetadata,
    already_normalized: Optional[bool] = None,
) -> np.ndarray:
    src = np.asarray(image, dtype=np.float32)
    if already_normalized is None:
        high_value = (
            float(np.percentile(src, 99.9)) if src.size else 0.0
        )
        already_normalized = not (
            metadata.white_level > 8.0 and high_value > 8.0
        )
    if already_normalized:
        return np.clip(src, 0.0, 1.0)
    # RAW Input is the uncorrected sensor signal.  Its display transform must
    # not silently subtract metadata black levels before the BLC stage, or a
    # BLC configured with zero black would appear to change brightness merely
    # because the before/after previews used different normalization rules.
    normalized = src / max(float(metadata.white_level), 1.0)
    return np.clip(normalized, 0.0, 1.0)


def bayer_mosaic_rgb(
    image: np.ndarray,
    metadata: RawMetadata,
    already_normalized: Optional[bool] = None,
) -> np.ndarray:
    """Render a strict CFA mosaic: one source pixel, one colour channel.

    Despite the historic function name, this performs no interpolation,
    blur, channel spreading, or demosaic.  A Bayer frame therefore naturally
    contains twice as many green pixels as red or blue pixels.
    """
    src = _normalize_bayer_for_display(
        image, metadata, already_normalized
    )
    rgb = np.zeros((*src.shape, 3), np.float32)
    positions = channel_positions(metadata.bayer_pattern)
    for name, (y, x) in positions.items():
        channel = {"R": 0, "Gr": 1, "Gb": 1, "B": 2}[name]
        rgb[y::2, x::2, channel] = src[y::2, x::2]
    return np.clip(rgb, 0.0, 1.0)


def bayer_false_color(
    image: np.ndarray,
    metadata: RawMetadata,
    already_normalized: Optional[bool] = None,
) -> np.ndarray:
    """Backward-compatible alias for the strict Bayer mosaic renderer."""
    return bayer_mosaic_rgb(
        image, metadata, already_normalized
    )


def bayer_cell_rgb(
    image: np.ndarray,
    metadata: RawMetadata,
    already_normalized: Optional[bool] = None,
) -> np.ndarray:
    """Return one RGB analysis sample per native 2×2 CFA cell.

    This is not spatial demosaic: R, Gr, Gb and B are read only from their
    original sensor sites.  It avoids filling histograms/scopes with the zero
    channels intentionally present in the strict mosaic preview.
    """
    src = _normalize_bayer_for_display(
        image, metadata, already_normalized
    )
    positions = channel_positions(metadata.bayer_pattern)
    red_y, red_x = positions["R"]
    gr_y, gr_x = positions["Gr"]
    gb_y, gb_x = positions["Gb"]
    blue_y, blue_x = positions["B"]
    red = src[red_y::2, red_x::2]
    green = 0.5 * (
        src[gr_y::2, gr_x::2]
        + src[gb_y::2, gb_x::2]
    )
    blue = src[blue_y::2, blue_x::2]
    height = min(red.shape[0], green.shape[0], blue.shape[0])
    width = min(red.shape[1], green.shape[1], blue.shape[1])
    return np.stack(
        (
            red[:height, :width],
            green[:height, :width],
            blue[:height, :width],
        ),
        axis=-1,
    ).astype(np.float32, copy=False)


def resize_bayer_mosaic_preview(
    mosaic_rgb: np.ndarray,
    width: int,
    height: int,
    pattern: str,
) -> np.ndarray:
    """Resize four CFA phases independently and re-interleave them.

    The input is the strict sparse RGB mosaic produced by
    ``bayer_mosaic_rgb``.  No missing colour at any output site is created.
    """
    src = np.asarray(mosaic_rgb, dtype=np.float32)
    if src.ndim != 3 or src.shape[2] != 3:
        raise ValueError("Bayer mosaic preview must be H×W×3")
    target_width = max(2, (int(width) // 2) * 2)
    target_height = max(2, (int(height) // 2) * 2)
    plane_width = target_width // 2
    plane_height = target_height // 2
    output = np.zeros(
        (target_height, target_width, 3), np.float32
    )
    positions = channel_positions(pattern)
    for name, (y, x) in positions.items():
        channel = {
            "R": 0, "Gr": 1, "Gb": 1, "B": 2
        }[name]
        plane = src[y::2, x::2, channel]
        resized = cv2.resize(
            plane,
            (plane_width, plane_height),
            interpolation=cv2.INTER_AREA,
        )
        output[y::2, x::2, channel] = resized
    return output


def display_rgb(
    image: np.ndarray,
    domain: str,
    metadata: RawMetadata,
    bayer_normalized: Optional[bool] = None,
    data_state: Optional[StageDataState] = None,
) -> np.ndarray:
    """Return normalized RGB without a display transfer function.

    This function is deliberately suitable for analysis and export call sites.
    UI-only brightness and sRGB encoding belong in ``encode_display_rgb`` so
    calibration samples never depend on how bright the monitor preview looks.
    """
    src = np.asarray(image, dtype=np.float32)
    if data_state is not None:
        bayer_normalized = bool(data_state.normalized)
    if domain == "bayer":
        return bayer_mosaic_rgb(
            src, metadata, bayer_normalized
        )
    if src.ndim == 2:
        values = src
        if data_state is not None and not data_state.normalized:
            values = values / data_state.display_divisor
        return np.repeat(np.clip(values, 0, 1)[..., None], 3, axis=2)
    values = src[:, :, :3]
    if data_state is not None and not data_state.normalized:
        values = values / data_state.display_divisor
    return np.clip(values, 0.0, 1.0)


def encode_display_rgb(
    linear_rgb: np.ndarray,
    exposure_ev: float = 0.0,
) -> np.ndarray:
    """Encode linear RGB for the monitor with a display-only EV adjustment."""
    values = np.asarray(linear_rgb, dtype=np.float32)
    gain = np.float32(2.0 ** float(np.clip(exposure_ev, -6.0, 6.0)))
    values = np.clip(values * gain, 0.0, 1.0)
    encoded = np.where(
        values <= 0.0031308,
        values * 12.92,
        1.055 * np.power(values, 1.0 / 2.4) - 0.055,
    )
    return np.clip(encoded, 0.0, 1.0).astype(np.float32, copy=False)


def encode_display_uint8(
    linear_rgb: np.ndarray,
    exposure_ev: float = 0.0,
    already_encoded: bool = False,
) -> np.ndarray:
    """Fast preview raster encoding using a 12-bit sRGB lookup table."""
    gain = 2.0 ** float(np.clip(exposure_ev, -6.0, 6.0))
    if already_encoded:
        return np.round(
            np.clip(
                np.asarray(linear_rgb, dtype=np.float32) * gain,
                0.0,
                1.0,
            )
            * 255.0
        ).astype(np.uint8)
    indices = np.clip(
        np.asarray(linear_rgb, dtype=np.float32)
        * (gain * (_DISPLAY_LUT_SIZE - 1)),
        0,
        _DISPLAY_LUT_SIZE - 1,
    ).astype(np.uint16)
    return _DISPLAY_LUT_UINT8[indices]


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


def export_image(
    path: str,
    image: np.ndarray,
    domain: str,
    metadata: RawMetadata,
    data_state: Optional[StageDataState] = None,
) -> None:
    rgb = display_rgb(
        image, domain, metadata, data_state=data_state
    )
    suffix = Path(path).suffix.lower()
    if suffix in {".tif", ".tiff"} and tifffile is not None:
        tifffile.imwrite(path, np.round(rgb * 65535.0).astype(np.uint16), photometric="rgb")
    else:
        bgr = cv2.cvtColor(np.round(rgb * 255.0).astype(np.uint8), cv2.COLOR_RGB2BGR)
        if not cv2.imwrite(path, bgr):
            raise RuntimeError(f"无法导出图像：{path}")
