from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from ..bayer import split_planes
from ..models import ImageROI, ISPError, ParameterRecommendation, RawMetadata
from .base import CancellationToken, ModuleAnalyzer


def _mad_sigma(values: np.ndarray) -> float:
    values = np.asarray(values, np.float64)
    median = np.median(values)
    return float(1.4826 * np.median(np.abs(values - median)))


def _fit_noise(points: Sequence[Tuple[float, float]]) -> Dict[str, float]:
    data = np.asarray(points, np.float64)
    means = data[:, 0]
    variances = data[:, 1]
    if len(points) >= 2 and np.ptp(means) > 1e-4:
        design = np.column_stack([means, np.ones_like(means)])
        coefficients = np.linalg.lstsq(design, variances, rcond=None)[0]
        shot = max(float(coefficients[0]), 0.0)
        read = max(float(coefficients[1]), 0.0)
        predicted = shot * means + read
    else:
        shot = 0.0
        read = max(float(np.median(variances)), 0.0)
        predicted = np.full_like(variances, read)
    residual = variances - predicted
    total = float(np.sum((variances - np.mean(variances)) ** 2))
    r2 = 1.0 - float(np.sum(residual ** 2)) / max(total, 1e-12)
    return {
        "shot_noise": shot,
        "read_noise": read,
        "r_squared": float(np.clip(r2, -1.0, 1.0)),
        "rmse": float(np.sqrt(np.mean(residual ** 2))),
        "sample_count": int(len(points)),
    }


def _plot_points(
    channel_points: Dict[str, List[Tuple[float, float]]],
    fits: Dict[str, Dict[str, float]],
    size: int = 320,
) -> np.ndarray:
    canvas = np.zeros((size, size, 3), np.float32)
    colors = {
        "R": (1.0, 0.2, 0.2),
        "G": (0.2, 1.0, 0.4),
        "Gr": (0.2, 1.0, 0.4),
        "Gb": (0.1, 0.7, 0.3),
        "B": (0.2, 0.45, 1.0),
        "Y": (0.95, 0.95, 0.95),
    }
    all_points = [item for values in channel_points.values() for item in values]
    if not all_points:
        return canvas
    maximum_mean = max(max(point[0] for point in all_points), 1e-6)
    maximum_variance = max(max(point[1] for point in all_points), 1e-8)
    for channel, points in channel_points.items():
        color = colors.get(channel, (1.0, 1.0, 1.0))
        for mean, variance in points:
            x = int(np.clip(mean / maximum_mean, 0, 1) * (size - 12)) + 5
            y = size - 6 - int(
                np.clip(variance / maximum_variance, 0, 1) * (size - 12)
            )
            cv2.circle(canvas, (x, y), 2, color, -1, cv2.LINE_AA)
        fit = fits[channel]
        xs = np.linspace(0, maximum_mean, 64)
        ys = fit["shot_noise"] * xs + fit["read_noise"]
        points_xy = np.column_stack([
            5 + xs / maximum_mean * (size - 12),
            size - 6 - np.clip(ys / maximum_variance, 0, 1) * (size - 12),
        ]).astype(np.int32).reshape(-1, 1, 2)
        cv2.polylines(canvas, [points_xy], False, color, 1, cv2.LINE_AA)
    return canvas


class NoiseProfiler(ModuleAnalyzer):
    module_id = "noise_profile"
    target_module_id = "noise_reduction"
    name = "Noise Profile"

    def analyze(
        self,
        image: np.ndarray,
        metadata: RawMetadata,
        current_parameters: Dict[str, Any],
        roi: Optional[ImageROI] = None,
        cancel_token: Optional[CancellationToken] = None,
        rois: Optional[Sequence[ImageROI]] = None,
        domain: str = "rgb",
        grid_rows: int = 4,
        grid_cols: int = 4,
        texture_threshold: float = 0.12,
        source_description: str = "Current pipeline stage",
        **_options: Any,
    ) -> ParameterRecommendation:
        token = cancel_token or CancellationToken()
        src = np.asarray(image, np.float32)
        if domain == "rgb":
            if src.ndim != 3 or src.shape[2] < 3:
                raise ISPError("Noise Profile 的 RGB 输入格式无效")
            src = src[:, :, :3]
        elif domain == "bayer":
            if src.ndim != 2:
                raise ISPError("Noise Profile 的 Bayer 输入格式无效")
            if float(src.max(initial=0.0)) > 2.0:
                normalized = src.copy()
                from ..bayer import channel_positions
                for name, (py, px) in channel_positions(
                    metadata.bayer_pattern
                ).items():
                    index = {"R": 0, "Gr": 1, "Gb": 2, "B": 3}[name]
                    black = float(metadata.black_level[index])
                    normalized[py::2, px::2] = (
                        normalized[py::2, px::2] - black
                    ) / max(float(metadata.white_level) - black, 1.0)
                src = normalized
        else:
            raise ISPError(f"Noise Profile 不支持域：{domain}")
        if not np.all(np.isfinite(src)):
            raise ISPError("Noise Profile 输入包含 NaN/Infinity")

        requested_rois = list(rois or ([] if roi is None else [roi]))
        if not requested_rois:
            requested_rois = [ImageROI(0, 0, src.shape[1], src.shape[0])]
        blocks: List[ImageROI] = []
        # A single broad ROI is subdivided to obtain multiple signal levels.
        if len(requested_rois) == 1:
            base = requested_rois[0]
            base.validate(src.shape)
            y_edges = np.linspace(base.y, base.y2, max(1, grid_rows) + 1).astype(int)
            x_edges = np.linspace(base.x, base.x2, max(1, grid_cols) + 1).astype(int)
            for row in range(len(y_edges) - 1):
                for col in range(len(x_edges) - 1):
                    block = ImageROI(
                        int(x_edges[col]),
                        int(y_edges[row]),
                        int(x_edges[col + 1] - x_edges[col]),
                        int(y_edges[row + 1] - y_edges[row]),
                    )
                    if block.width >= 8 and block.height >= 8:
                        blocks.append(block)
        else:
            for block in requested_rois:
                block.validate(src.shape)
                blocks.append(block)
        if not blocks:
            raise ISPError("Noise Profile 没有足够大的有效 ROI")

        channel_points: Dict[str, List[Tuple[float, float]]] = {}
        rejected: List[Dict[str, Any]] = []
        accepted: List[Dict[str, Any]] = []
        overlay = np.zeros((*src.shape[:2], 3), np.float32)
        for block in blocks:
            token.check()
            local = block.align_for_bayer(src.shape) if domain == "bayer" else block
            ys, xs = local.slices()
            crop = np.ascontiguousarray(src[ys, xs])
            if domain == "rgb":
                luma = np.sum(
                    crop * np.array([0.2126, 0.7152, 0.0722], np.float32),
                    axis=2,
                )
                planes = {"R": crop[:, :, 0], "G": crop[:, :, 1], "B": crop[:, :, 2]}
            else:
                planes = split_planes(crop, metadata.bayer_pattern)
                luma = 0.5 * (planes["Gr"] + planes["Gb"])
            gradient_x = cv2.Sobel(luma, cv2.CV_32F, 1, 0, ksize=3)
            gradient_y = cv2.Sobel(luma, cv2.CV_32F, 0, 1, ksize=3)
            gradient = float(np.mean(np.hypot(gradient_x, gradient_y)))
            clipped_high = float(np.mean(luma >= 0.995))
            clipped_low = float(np.mean(luma <= 0.001))
            reason = ""
            if gradient > texture_threshold:
                reason = "texture"
            elif clipped_high > 0.02:
                reason = "overexposed"
            elif clipped_low > 0.5:
                reason = "underexposed"
            if reason:
                rejected.append({"roi": local.to_dict(), "reason": reason})
                overlay[ys, xs, 0] = 0.65
                continue
            sample = {
                "roi": local.to_dict(),
                "gradient": gradient,
                "clipped_high": clipped_high,
                "clipped_low": clipped_low,
                "channels": {},
            }
            for channel, plane in planes.items():
                values = np.asarray(plane, np.float32)
                mean = float(np.mean(values))
                variance = float(np.var(values, ddof=1))
                sigma_mad = _mad_sigma(values)
                channel_points.setdefault(channel, []).append((mean, variance))
                sample["channels"][channel] = {
                    "mean": mean,
                    "variance": variance,
                    "standard_deviation": float(np.sqrt(max(variance, 0.0))),
                    "mad_sigma": sigma_mad,
                    "sample_count": int(values.size),
                }
            accepted.append(sample)
            overlay[ys, xs, 1] = 0.35

        if not accepted:
            raise ISPError("所有 Noise Profile ROI 都因纹理、过曝或欠曝被排除")
        fits = {
            channel: _fit_noise(points)
            for channel, points in channel_points.items()
        }
        token.check()

        evaluation_level = 0.18
        sigmas = [
            np.sqrt(max(
                fit["shot_noise"] * evaluation_level + fit["read_noise"], 0.0
            ))
            for fit in fits.values()
        ]
        typical_sigma = float(np.median(sigmas))
        rgb_fit = [fits[name] for name in ("R", "G", "B") if name in fits]
        chroma_spread = float(
            np.std([
                np.sqrt(max(
                    fit["shot_noise"] * evaluation_level + fit["read_noise"],
                    0.0,
                ))
                for fit in rgb_fit
            ])
        ) if rgb_fit else 0.0
        spatial_strength = float(np.clip(typical_sigma * 14.0, 0.0, 1.0))
        chroma_strength = float(
            np.clip(typical_sigma * 12.0 + chroma_spread * 10.0, 0.0, 1.0)
        )
        edge_protection = float(np.clip(0.82 - typical_sigma * 3.0, 0.4, 0.9))
        radius = 3 if typical_sigma < 0.015 else (5 if typical_sigma < 0.04 else 7)
        warnings = []
        if len(accepted) < 4:
            warnings.append("有效 ROI 数量不足，噪声模型拟合置信度较低")
        if len(rejected) > len(blocks) * 0.5:
            warnings.append("超过一半 ROI 因纹理或曝光问题被排除")
        mean_r2 = float(np.mean([
            max(0.0, fit["r_squared"]) for fit in fits.values()
        ]))
        if mean_r2 < 0.5 and any(len(points) >= 3 for points in channel_points.values()):
            warnings.append("均值-方差线性拟合较弱，建议增加不同曝光的平坦样本")
        confidence = float(
            np.clip(len(accepted) / 8.0, 0.1, 1.0)
            * np.clip(0.4 + 0.6 * max(mean_r2, 0.0), 0.25, 1.0)
        )
        if len(channel_points) and all(
            np.ptp(np.asarray(points)[:, 0]) < 0.02
            for points in channel_points.values()
        ):
            warnings.append("样本亮度范围较窄，Shot Noise 系数仅供参考")
            confidence *= 0.7

        if domain == "rgb":
            luma_full = np.sum(
                src * np.array([0.2126, 0.7152, 0.0722], np.float32),
                axis=2,
            )
        else:
            planes_full = split_planes(src, metadata.bayer_pattern)
            luma_full = 0.5 * (planes_full["Gr"] + planes_full["Gb"])
        highpass = luma_full - cv2.GaussianBlur(luma_full, (0, 0), 1.0)
        noise_heatmap = cv2.GaussianBlur(highpass * highpass, (0, 0), 2.0)
        curve = _plot_points(channel_points, fits)
        residual_curve = np.zeros((128, 320), np.float32)
        residual_values = []
        for channel, points in channel_points.items():
            fit = fits[channel]
            for mean, variance in points:
                residual_values.append(
                    variance - fit["shot_noise"] * mean - fit["read_noise"]
                )
        if residual_values:
            values = np.asarray(residual_values, np.float32)
            maximum = max(float(np.max(np.abs(values))), 1e-8)
            for index, value in enumerate(values):
                x = int(index / max(len(values) - 1, 1) * 319)
                y = int(np.clip(64 - value / maximum * 56, 0, 127))
                cv2.circle(residual_curve, (x, y), 1, 1.0, -1)

        return ParameterRecommendation(
            module_id=self.module_id,
            target_module_id=self.target_module_id,
            current_parameters=dict(current_parameters),
            suggested_parameters={
                "algorithm": "Bilateral",
                "spatial_strength": spatial_strength,
                "chroma_strength": chroma_strength,
                "edge_protection": edge_protection,
                "radius": radius,
            },
            measurements={
                "domain": domain,
                "accepted_rois": accepted,
                "rejected_rois": rejected,
                "channel_models": fits,
                "evaluation_level": evaluation_level,
                "typical_noise_sigma": typical_sigma,
                "fit_quality": mean_r2,
            },
            confidence=confidence,
            warnings=warnings,
            artifacts={
                "Noise Sample ROI Overlay": overlay,
                "Mean-Variance Curve": curve,
                "Residual Curve": residual_curve,
                "Noise Heatmap": noise_heatmap,
            },
            source_description=source_description,
            roi=roi,
            method="Mean-Variance Linear Model",
        )
