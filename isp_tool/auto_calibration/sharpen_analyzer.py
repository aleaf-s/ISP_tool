from __future__ import annotations

from typing import Any, Dict, Optional

import cv2
import numpy as np

from ..models import ImageROI, ISPError, ParameterRecommendation, RawMetadata
from .base import CancellationToken, ModuleAnalyzer


def _robust_sigma(values: np.ndarray) -> float:
    finite = np.asarray(values, np.float64)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return 0.0
    median = np.median(finite)
    return float(1.4826 * np.median(np.abs(finite - median)))


class SharpenAnalyzer(ModuleAnalyzer):
    module_id = "auto_sharpen"
    target_module_id = "sharpen"
    name = "Auto Sharpen"

    def analyze(
        self,
        image: np.ndarray,
        metadata: RawMetadata,
        current_parameters: Dict[str, Any],
        roi: Optional[ImageROI] = None,
        cancel_token: Optional[CancellationToken] = None,
        source_description: str = "Noise Reduction output",
        **_options: Any,
    ) -> ParameterRecommendation:
        del metadata
        token = cancel_token or CancellationToken()
        src = np.asarray(image, np.float32)
        if src.ndim != 3 or src.shape[2] < 3:
            raise ISPError("Auto Sharpen 需要 Sharpen 之前的 RGB 图像")
        if roi is not None:
            roi.validate(src.shape)
            ys, xs = roi.slices()
            working = src[ys, xs, :3]
        else:
            working = src[:, :, :3]
        if working.shape[0] < 16 or working.shape[1] < 16:
            raise ISPError("Auto Sharpen 分析区域过小")
        if not np.all(np.isfinite(working)):
            raise ISPError("Auto Sharpen 输入包含 NaN/Infinity")
        token.check()

        luma = np.sum(
            working * np.array([0.2126, 0.7152, 0.0722], np.float32),
            axis=2,
        )
        gx = cv2.Sobel(luma, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(luma, cv2.CV_32F, 0, 1, ksize=3)
        gradient = np.hypot(gx, gy)
        valid = (luma > 0.01) & (luma < 0.99)
        valid_gradient = gradient[valid]
        if valid_gradient.size < 64:
            raise ISPError("Auto Sharpen 有效亮度样本不足")
        flat_threshold = float(np.percentile(valid_gradient, 35))
        edge_threshold = float(np.percentile(valid_gradient, 85))
        flat_mask = valid & (gradient <= flat_threshold)
        edge_mask = valid & (gradient >= max(edge_threshold, 0.01))

        blur_small = cv2.GaussianBlur(luma, (0, 0), 0.8)
        highpass = luma - blur_small
        noise_sigma = _robust_sigma(highpass[flat_mask])
        edge_values = gradient[edge_mask]
        edge_strength = float(np.median(edge_values)) if edge_values.size else 0.0
        edge_density = float(np.mean(edge_mask))
        laplacian = cv2.Laplacian(luma, cv2.CV_32F, ksize=3)
        laplacian_energy = float(np.mean(laplacian[edge_mask] ** 2)) if np.any(edge_mask) else 0.0

        local_blur = cv2.GaussianBlur(luma, (0, 0), 1.5)
        broad_detail = luma - local_blur
        halo_threshold = max(0.035, 4.0 * noise_sigma)
        overshoot = edge_mask & (broad_detail > halo_threshold)
        undershoot = edge_mask & (broad_detail < -halo_threshold)
        halo_ratio = float(np.mean(overshoot | undershoot))

        # A broad, low-gradient edge generally needs a slightly larger radius.
        sharpness_proxy = float(np.clip(edge_strength / 0.35, 0.0, 1.0))
        radius = float(np.clip(0.8 + (1.0 - sharpness_proxy) * 1.5, 0.4, 3.0))
        base_strength = float(np.clip(1.25 - sharpness_proxy * 0.85, 0.25, 1.25))
        noise_penalty = float(np.clip(noise_sigma * 14.0, 0.0, 0.88))
        halo_penalty = float(np.clip(halo_ratio * 8.0, 0.0, 0.5))
        strength = float(
            np.clip(base_strength * (1.0 - noise_penalty) * (1.0 - halo_penalty), 0.0, 1.5)
        )
        threshold = float(np.clip(max(0.004, noise_sigma * 3.5), 0.0, 0.2))
        halo_suppression = float(
            np.clip(0.42 + halo_ratio * 7.0 + noise_sigma * 2.0, 0.35, 1.0)
        )
        warnings = []
        if noise_sigma > 0.035:
            warnings.append("平坦区域噪声较高，锐化强度已保守限制")
        if halo_ratio > 0.01:
            warnings.append("检测到潜在过冲/欠冲，建议关注光晕")
        if edge_density < 0.01:
            warnings.append("有效边缘数量较少，自动锐化置信度有限")
        if edge_density > 0.35:
            warnings.append("图像纹理非常密集，锐化建议可能放大细纹噪声")
        confidence = float(
            np.clip(edge_mask.sum() / 4096.0, 0.15, 1.0)
            * np.clip(flat_mask.sum() / 4096.0, 0.15, 1.0)
            * np.clip(1.0 - noise_sigma * 5.0, 0.35, 1.0)
        )

        risk = np.clip(
            np.abs(broad_detail) / max(halo_threshold * 2.0, 1e-6),
            0.0,
            1.0,
        )
        return ParameterRecommendation(
            module_id=self.module_id,
            target_module_id=self.target_module_id,
            current_parameters=dict(current_parameters),
            suggested_parameters={
                "strength": strength,
                "radius": radius,
                "threshold": threshold,
                "halo_suppression": halo_suppression,
            },
            measurements={
                "flat_region_noise_sigma": noise_sigma,
                "edge_strength": edge_strength,
                "edge_density": edge_density,
                "laplacian_energy": laplacian_energy,
                "sharpness_proxy": sharpness_proxy,
                "overshoot_ratio": float(np.mean(overshoot)),
                "undershoot_ratio": float(np.mean(undershoot)),
                "halo_risk_ratio": halo_ratio,
            },
            confidence=confidence,
            warnings=warnings,
            artifacts={
                "Edge Mask": edge_mask.astype(np.uint8),
                "Flat Region Mask": flat_mask.astype(np.uint8),
                "Overshoot Mask": overshoot.astype(np.uint8),
                "Undershoot Mask": undershoot.astype(np.uint8),
                "Sharpen Risk Heatmap": risk.astype(np.float32),
            },
            source_description=source_description,
            roi=roi,
            method="Edge and Noise Heuristic",
        )

