from __future__ import annotations

from typing import Optional

import numpy as np

from ..bayer import split_planes
from ..models import AEResult, ISPError, ImageROI, RawMetadata


def _luminance(
    image: np.ndarray,
    domain: str,
    metadata: RawMetadata,
    roi: Optional[ImageROI],
) -> np.ndarray:
    src = np.asarray(image, dtype=np.float32)
    if roi is not None:
        if domain == "bayer":
            roi = roi.align_for_bayer(src.shape)
        roi.validate(src.shape)
        ys, xs = roi.slices()
        src = src[ys, xs]
    if domain == "bayer":
        if src.max(initial=0.0) > 2.0:
            black = float(np.mean(metadata.black_level))
            src = (src - black) / max(metadata.white_level - black, 1.0)
        planes = split_planes(src, metadata.bayer_pattern)
        return 0.5 * (planes["Gr"] + planes["Gb"])
    if src.ndim != 3 or src.shape[2] < 3:
        raise ISPError("AE 输入必须是 Bayer 或 RGB")
    return np.sum(src[:, :, :3] * np.array([0.2126, 0.7152, 0.0722], np.float32), axis=2)


def estimate_exposure(
    image: np.ndarray,
    domain: str,
    metadata: RawMetadata,
    method: str = "Percentile",
    target_level: float = 0.45,
    measurement_percentile: float = 50.0,
    highlight_percentile: float = 99.5,
    maximum_gain: float = 8.0,
    maximum_allowed_clipping: float = 0.01,
    roi: Optional[ImageROI] = None,
) -> AEResult:
    values = np.asarray(_luminance(image, domain, metadata, roi), np.float32)
    values = values[np.isfinite(values)]
    if values.size < 16:
        raise ISPError("AE 有效亮度样本不足")
    if method == "Mean Luma":
        current = float(np.mean(values))
    elif method == "Median Luma":
        current = float(np.median(values))
    elif method in {"Percentile", "Highlight Protected"}:
        current = float(np.percentile(values, measurement_percentile))
    else:
        raise ISPError(f"未知 AE 方法：{method}")
    if current <= 1e-8:
        raise ISPError("AE 测得亮度接近 0")
    requested_gain = float(target_level) / current
    gain = float(np.clip(requested_gain, 0.0, maximum_gain))
    highlight_value = float(np.percentile(values, highlight_percentile))
    clip_guard_percentile = 100.0 * (1.0 - np.clip(maximum_allowed_clipping, 0, 1))
    clip_guard_value = float(np.percentile(values, clip_guard_percentile))
    protected_gain = 0.999 / max(clip_guard_value, 1e-8)
    highlight_limited = False
    if method == "Highlight Protected" or gain * highlight_value > 1.0:
        if protected_gain < gain:
            gain = max(0.0, protected_gain)
            highlight_limited = True
    predicted_clip = float(np.mean(values * gain >= 1.0))
    return AEResult(
        current,
        float(target_level),
        gain,
        float(np.mean(values >= 1.0)),
        predicted_clip,
        method,
        {
            "requested_gain": requested_gain,
            "highlight_value": highlight_value,
            "highlight_limited": highlight_limited,
            "sample_count": int(values.size),
            "predicted_level": current * gain,
        },
    )
