from __future__ import annotations

from typing import Any, Dict, Optional

import cv2
import numpy as np

from ..bayer import channel_positions
from ..models import ImageROI, ISPError, ParameterRecommendation, RawMetadata
from .base import CancellationToken, ModuleAnalyzer


def _trimmed_mean(values: np.ndarray, fraction: float) -> float:
    flattened = np.sort(np.asarray(values, np.float64).ravel())
    trim = int(flattened.size * float(np.clip(fraction, 0.0, 0.4)))
    if trim and flattened.size > 2 * trim:
        flattened = flattened[trim:-trim]
    return float(np.mean(flattened))


def _curve_image(values: np.ndarray, width: int = 384, height: int = 128) -> np.ndarray:
    values = np.asarray(values, np.float32).ravel()
    canvas = np.zeros((height, width), np.float32)
    if values.size < 2:
        return canvas
    low, high = np.percentile(values, [1, 99])
    if high <= low:
        high = low + 1.0
    xs = np.linspace(0, width - 1, values.size).astype(np.int32)
    ys = np.round(
        (1.0 - np.clip((values - low) / (high - low), 0.0, 1.0))
        * (height - 1)
    ).astype(np.int32)
    points = np.column_stack([xs, ys]).reshape(-1, 1, 2)
    cv2.polylines(canvas, [points], False, 1.0, 1, cv2.LINE_AA)
    return canvas


class BLCAnalyzer(ModuleAnalyzer):
    module_id = "auto_blc"
    target_module_id = "black_level_correction"
    name = "Auto Black Level"

    def analyze(
        self,
        image: np.ndarray,
        metadata: RawMetadata,
        current_parameters: Dict[str, Any],
        roi: Optional[ImageROI] = None,
        cancel_token: Optional[CancellationToken] = None,
        source_description: str = "Current RAW",
        statistic: str = "Median",
        trim_fraction: float = 0.05,
        **_options: Any,
    ) -> ParameterRecommendation:
        token = cancel_token or CancellationToken()
        token.check()
        src = np.asarray(image, dtype=np.float32)
        if src.ndim != 2:
            raise ISPError("Auto BLC 需要 BLC 之前的单通道 Bayer RAW")
        if src.size < 64 or not np.all(np.isfinite(src)):
            raise ISPError("Auto BLC 输入数据不足或包含 NaN/Infinity")

        selected_roi = roi
        if selected_roi is not None:
            selected_roi = selected_roi.align_for_bayer(src.shape)
            ys, xs = selected_roi.slices()
            analysis = np.ascontiguousarray(src[ys, xs])
        else:
            analysis = src
        # Standard-image paths are normally converted back to DN by raw_io.
        # Still support normalized test data and custom callers explicitly.
        normalized_input = float(np.nanmax(analysis)) <= 2.0
        if normalized_input:
            analysis_dn = analysis * float(metadata.white_level)
        else:
            analysis_dn = analysis

        token.check()
        names = ("R", "Gr", "Gb", "B")
        statistics: Dict[str, Dict[str, float]] = {}
        recommendations: Dict[str, float] = {}
        hot_mask = np.zeros(analysis.shape, np.uint8)
        warnings = []
        table = np.zeros((4, 8), np.float32)
        for index, name in enumerate(names):
            py, px = channel_positions(metadata.bayer_pattern)[name]
            values = analysis_dn[py::2, px::2].astype(np.float64)
            finite = values[np.isfinite(values)]
            if finite.size < 16:
                raise ISPError(f"Auto BLC 的 {name} 通道有效样本不足")
            p1, median, p99 = np.percentile(finite, [1.0, 50.0, 99.0])
            mean = float(np.mean(finite))
            std = float(np.std(finite))
            trimmed = _trimmed_mean(finite, trim_fraction)
            if statistic == "Trimmed Mean":
                estimate = trimmed
            elif statistic == "Mean":
                estimate = mean
            else:
                estimate = float(median)
            estimate = float(np.clip(round(estimate), 0, metadata.white_level - 1))
            recommendations[name.lower()] = estimate
            robust_sigma = max(
                1.4826 * float(np.median(np.abs(finite - median))), 1e-6
            )
            hot = values > median + max(8.0 * robust_sigma, 4.0)
            hot_mask[py::2, px::2] = hot.astype(np.uint8)
            statistics[name] = {
                "mean": mean,
                "median": float(median),
                "trimmed_mean": trimmed,
                "standard_deviation": std,
                "p1": float(p1),
                "p50": float(median),
                "p99": float(p99),
                "sample_count": int(finite.size),
                "suggested_black_level": estimate,
                "hot_pixel_candidates": int(np.count_nonzero(hot)),
            }
            table[index] = (
                mean, median, trimmed, std, p1, p99, estimate, finite.size
            )
            if finite.size < 64:
                warnings.append(f"{name} 通道样本数量偏少")
            token.check()

        channel_medians = np.array(
            [statistics[name]["median"] for name in names], np.float32
        )
        median_level = float(np.median(channel_medians))
        white = max(float(metadata.white_level), 1.0)
        relative_dark_level = median_level / white
        if relative_dark_level > 0.08:
            warnings.append("分析区域平均亮度过高，可能不是暗场或光学黑区")
        if float(np.max(channel_medians) - np.min(channel_medians)) > 0.04 * white:
            warnings.append("四个 Bayer 通道的黑电平差异异常")
        hot_ratio = float(np.mean(hot_mask > 0))
        if hot_ratio > 0.01:
            warnings.append("热像素候选比例过高，暗场可能漏光或噪声过强")

        black_map = np.zeros_like(analysis_dn)
        for name, (py, px) in channel_positions(metadata.bayer_pattern).items():
            black_map[py::2, px::2] = recommendations[name.lower()]
        corrected = analysis_dn - black_map
        negative_ratio = float(np.mean(corrected < 0.0))
        zero_ratio = float(np.mean(corrected <= 0.5))
        row_means = np.mean(analysis_dn, axis=1)
        column_means = np.mean(analysis_dn, axis=0)
        row_noise = float(np.std(row_means - np.median(row_means)))
        column_noise = float(np.std(column_means - np.median(column_means)))
        if row_noise > max(2.0, 0.01 * white):
            warnings.append("检测到较明显的行黑电平变化")
        if column_noise > max(2.0, 0.01 * white):
            warnings.append("检测到较明显的列黑电平变化")

        sample_factor = min(1.0, analysis_dn.size / 4096.0)
        darkness_factor = float(np.clip(1.0 - relative_dark_level / 0.15, 0.0, 1.0))
        spread_factor = float(
            np.clip(1.0 - np.mean(table[:, 3]) / max(0.03 * white, 1.0), 0.0, 1.0)
        )
        confidence = sample_factor * (
            0.55 * darkness_factor + 0.45 * spread_factor
        )
        if hot_ratio > 0.01:
            confidence *= 0.65

        roi_mask = np.zeros(src.shape, np.uint8)
        if selected_roi is None:
            roi_mask[:] = 1
        else:
            ys, xs = selected_roi.slices()
            roi_mask[ys, xs] = 1
        measurements = {
            "channels": statistics,
            "statistic": statistic,
            "normalized_input": normalized_input,
            "relative_dark_level": relative_dark_level,
            "predicted_negative_clipping": negative_ratio,
            "predicted_zero_ratio": zero_ratio,
            "row_black_level_variation": row_noise,
            "column_black_level_variation": column_noise,
            "hot_pixel_candidate_ratio": hot_ratio,
        }
        return ParameterRecommendation(
            module_id=self.module_id,
            target_module_id=self.target_module_id,
            current_parameters=dict(current_parameters),
            suggested_parameters=recommendations,
            measurements=measurements,
            confidence=float(confidence),
            warnings=warnings,
            artifacts={
                "BLC Analysis ROI": roi_mask,
                "Hot Pixel Candidate Mask": hot_mask,
                "Row Mean Curve": _curve_image(row_means),
                "Column Mean Curve": _curve_image(column_means),
                "Bayer Channel Statistics": table,
            },
            source_description=source_description,
            roi=selected_roi,
            method=statistic,
        )

