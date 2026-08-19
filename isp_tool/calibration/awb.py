from __future__ import annotations

from typing import Dict, Optional

import numpy as np

from ..bayer import channel_positions, split_planes
from ..models import (
    AWBResult,
    ISPError,
    ImageROI,
    RawMetadata,
    StageDataState,
)


def _prepare_bayer(
    image: np.ndarray,
    metadata: RawMetadata,
    roi: Optional[ImageROI],
    data_state: Optional[StageDataState] = None,
) -> np.ndarray:
    src = np.asarray(image, dtype=np.float32)
    if src.ndim != 2:
        raise ISPError("AWB 校准需要 BLC/LSC 后的 Bayer 图像")
    if roi is not None:
        roi = roi.align_for_bayer(src.shape)
        ys, xs = roi.slices()
        src = src[ys, xs]
    # The active UI always supplies the stage contract.  The conservative
    # percentile fallback is retained only for callers of the legacy public
    # API that do not yet carry StageDataState.
    is_dn = (
        not data_state.normalized
        if data_state is not None
        else (
            metadata.white_level > 8.0
            and (float(np.percentile(src, 99.9)) if src.size else 0.0) > 8.0
        )
    )
    if is_dn:
        normalized = np.empty_like(src)
        black_levels = dict(zip(
            ("R", "Gr", "Gb", "B"), metadata.black_level
        ))
        for name, (y, x) in channel_positions(
            metadata.bayer_pattern
        ).items():
            black = float(black_levels[name])
            normalized[y::2, x::2] = (
                src[y::2, x::2] - black
            ) / max(float(metadata.white_level) - black, 1.0)
        src = normalized
    return src


def estimate_awb(
    bayer_image: np.ndarray,
    metadata: RawMetadata,
    method: str = "Robust Neutral",
    roi: Optional[ImageROI] = None,
    low_percentile: float = 2.0,
    high_percentile: float = 98.0,
    gain_limit: float = 8.0,
    shades_p: float = 6.0,
    neutral_tolerance: float = 0.18,
    data_state: Optional[StageDataState] = None,
) -> AWBResult:
    src = _prepare_bayer(bayer_image, metadata, roi, data_state)
    planes = split_planes(src, metadata.bayer_pattern)
    stacked = np.stack([planes[name] for name in ("R", "Gr", "Gb", "B")], axis=-1)
    green_plane = 0.5 * (stacked[:, :, 1] + stacked[:, :, 2])
    luminance = (stacked[:, :, 0] + 2.0 * green_plane + stacked[:, :, 3]) * 0.25
    low = np.percentile(luminance, low_percentile)
    high = np.percentile(luminance, high_percentile)
    valid = (
        (luminance >= max(low, 0.003))
        & (luminance <= min(high, 0.985))
        & np.all(stacked > 0.001, axis=2)
        & np.all(stacked < 0.995, axis=2)
    )
    # Prefer locally flat blocks. Bayer planes are already aligned to the same
    # 2×2 cell, so this also rejects many color edges and zipper artifacts.
    grad_y, grad_x = np.gradient(luminance)
    gradient = np.hypot(grad_x, grad_y) / np.maximum(luminance, 0.02)
    gradient_limit = (
        float(np.percentile(gradient[valid], 70.0))
        if np.any(valid)
        else 0.0
    )
    flat = gradient <= max(gradient_limit, 0.015)

    log_rg = np.log(np.maximum(stacked[:, :, 0], 1e-6) / np.maximum(green_plane, 1e-6))
    log_bg = np.log(np.maximum(stacked[:, :, 3], 1e-6) / np.maximum(green_plane, 1e-6))
    chroma_center = np.array([
        np.median(log_rg[valid]) if np.any(valid) else 0.0,
        np.median(log_bg[valid]) if np.any(valid) else 0.0,
    ], dtype=np.float32)
    chroma_distance = np.hypot(
        log_rg - chroma_center[0], log_bg - chroma_center[1]
    )
    chroma_limit = (
        float(np.percentile(chroma_distance[valid & flat], 45.0))
        if np.any(valid & flat)
        else float(neutral_tolerance)
    )
    robust_neutral = (
        valid
        & flat
        & (chroma_distance <= max(chroma_limit, neutral_tolerance * 0.35))
    )

    if method == "ROI Neutral":
        sample_mask = valid & flat
        if int(sample_mask.sum()) < 16:
            sample_mask = valid
    elif method == "Robust Neutral":
        sample_mask = robust_neutral
    elif method in {"Gray World", "Shades of Gray"}:
        sample_mask = valid
    elif method == "White Patch":
        brightness = np.mean(stacked, axis=2)
        threshold = np.percentile(brightness[valid], 95) if np.any(valid) else 1.0
        sample_mask = valid & (brightness >= threshold)
    else:
        raise ISPError(f"未知 AWB 方法：{method}")
    sample_count = int(sample_mask.sum())
    if sample_count < 16:
        raise ISPError(f"AWB 有效样本不足：{sample_count}")

    values: Dict[str, float] = {}
    for index, name in enumerate(("R", "Gr", "Gb", "B")):
        samples = stacked[:, :, index][sample_mask]
        if method == "Shades of Gray":
            values[name] = float(np.mean(np.power(samples, shades_p)) ** (1.0 / shades_p))
        elif method == "White Patch":
            values[name] = float(np.percentile(samples, 90))
        elif method == "Gray World":
            # A trimmed mean is less noisy than the old median while avoiding
            # large saturated objects dominating the estimate.
            lower, upper = np.percentile(samples, (10.0, 90.0))
            trimmed = samples[(samples >= lower) & (samples <= upper)]
            values[name] = float(np.mean(trimmed if trimmed.size else samples))
        else:
            values[name] = float(np.median(samples))
    green = 0.5 * (values["Gr"] + values["Gb"])
    raw_gains = {
        "R": green / max(values["R"], 1e-8),
        "Gr": green / max(values["Gr"], 1e-8),
        "Gb": green / max(values["Gb"], 1e-8),
        "B": green / max(values["B"], 1e-8),
    }
    gains = {name: float(np.clip(value, 0.0, gain_limit)) for name, value in raw_gains.items()}
    reached_limit = any(abs(gains[name] - raw_gains[name]) > 1e-6 for name in gains)
    valid_count = max(int(valid.sum()), 1)
    selected_fraction = float(sample_count / valid_count)
    selected_distance = chroma_distance[sample_mask]
    chroma_dispersion = (
        float(np.median(selected_distance)) if selected_distance.size else 1.0
    )
    green_mismatch = abs(values["Gr"] - values["Gb"]) / max(green, 1e-8)
    # Spatial coverage prevents a single neutral-looking object in one corner
    # from reporting unjustifiably high confidence.
    coverage_cells = 0
    grid_rows, grid_cols = 4, 6
    for grid_y in range(grid_rows):
        y0 = sample_mask.shape[0] * grid_y // grid_rows
        y1 = sample_mask.shape[0] * (grid_y + 1) // grid_rows
        for grid_x in range(grid_cols):
            x0 = sample_mask.shape[1] * grid_x // grid_cols
            x1 = sample_mask.shape[1] * (grid_x + 1) // grid_cols
            if np.any(sample_mask[y0:y1, x0:x1]):
                coverage_cells += 1
    spatial_coverage = coverage_cells / float(grid_rows * grid_cols)
    if method == "ROI Neutral":
        confidence = (
            min(1.0, sample_count / 512.0)
            * np.clip(1.0 - green_mismatch * 4.0, 0.25, 1.0)
        )
    else:
        confidence = (
            np.clip(selected_fraction * 3.0, 0.15, 1.0)
            * np.clip(spatial_coverage * 1.5, 0.25, 1.0)
            * np.clip(1.0 - chroma_dispersion * 2.5, 0.2, 1.0)
            * np.clip(1.0 - green_mismatch * 4.0, 0.25, 1.0)
        )
    if reached_limit:
        confidence *= 0.3
    mask_artifact = np.repeat(np.repeat(sample_mask.astype(np.uint8), 2, axis=0), 2, axis=1)
    mask_artifact = mask_artifact[:src.shape[0], :src.shape[1]]
    return AWBResult(
        gains["R"],
        gains["Gr"],
        gains["Gb"],
        gains["B"],
        float(confidence),
        method,
        sample_count,
        {
            "channel_values": values,
            "selected_fraction": selected_fraction,
            "neutral_fraction": selected_fraction,
            "spatial_coverage": spatial_coverage,
            "chroma_dispersion": chroma_dispersion,
            "green_mismatch": green_mismatch,
            "chroma_center_log_rg_bg": chroma_center.tolist(),
            "gain_limited": reached_limit,
            "valid_samples": int(valid.sum()),
        },
        {"AWB Selected Pixel Mask": mask_artifact},
    )
