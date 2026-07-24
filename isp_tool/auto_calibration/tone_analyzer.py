from __future__ import annotations

from typing import Any, Dict, Optional

import cv2
import numpy as np

from ..models import ImageROI, ISPError, ParameterRecommendation, RawMetadata
from ..modules.tone import evaluate_tone_curve
from .base import CancellationToken, ModuleAnalyzer


def _histogram_image(values: np.ndarray, width: int = 512, height: int = 180) -> np.ndarray:
    hist, _ = np.histogram(
        np.clip(np.asarray(values, np.float32), 0.0, 1.0),
        bins=256,
        range=(0.0, 1.0),
    )
    hist = np.log1p(hist.astype(np.float32))
    hist /= max(float(hist.max(initial=1.0)), 1e-8)
    canvas = np.zeros((height, width), np.float32)
    points = []
    for index, value in enumerate(hist):
        points.append((
            int(index / 255.0 * (width - 1)),
            int(height - 1 - value * (height - 8)),
        ))
    cv2.polylines(
        canvas,
        [np.asarray(points, np.int32).reshape(-1, 1, 2)],
        False,
        1.0,
        1,
        cv2.LINE_AA,
    )
    return canvas


def _curve_comparison(
    current: Dict[str, Any],
    suggested: Dict[str, Any],
    width: int = 512,
    height: int = 256,
) -> np.ndarray:
    x = np.linspace(0.0, max(
        1.0,
        float(current.get("white_point", 1.0)),
        float(suggested.get("white_point", 1.0)),
    ), width, dtype=np.float32)
    current_y = evaluate_tone_curve(x, current)
    suggested_y = evaluate_tone_curve(x, suggested)
    canvas = np.zeros((height, width, 3), np.float32)
    for curve, color in (
        (current_y, (0.55, 0.62, 0.72)),
        (suggested_y, (0.15, 0.72, 1.0)),
    ):
        points = np.column_stack([
            np.arange(width),
            np.round((1.0 - np.clip(curve, 0.0, 1.0)) * (height - 1)),
        ]).astype(np.int32).reshape(-1, 1, 2)
        cv2.polylines(canvas, [points], False, color, 2, cv2.LINE_AA)
    return canvas


class ToneAnalyzer(ModuleAnalyzer):
    module_id = "auto_tone"
    target_module_id = "tone_mapping"
    name = "Auto Tone"

    MODES = (
        "Natural",
        "Preserve Highlights",
        "Lift Shadows",
        "High Contrast",
        "Low-light",
    )

    def analyze(
        self,
        image: np.ndarray,
        metadata: RawMetadata,
        current_parameters: Dict[str, Any],
        roi: Optional[ImageROI] = None,
        cancel_token: Optional[CancellationToken] = None,
        mode: str = "Natural",
        maximum_allowed_clipping: float = 0.01,
        source_description: str = "CCM output (linear RGB)",
        **_options: Any,
    ) -> ParameterRecommendation:
        del metadata
        token = cancel_token or CancellationToken()
        src = np.asarray(image, np.float32)
        if src.ndim != 3 or src.shape[2] < 3:
            raise ISPError("Auto Tone 需要 Tone 之前的线性 RGB 图像")
        if mode not in self.MODES:
            raise ISPError(f"未知 Auto Tone 模式：{mode}")
        if roi is not None:
            roi.validate(src.shape)
            ys, xs = roi.slices()
            working = src[ys, xs, :3]
        else:
            working = src[:, :, :3]
        if not np.all(np.isfinite(working)):
            raise ISPError("Auto Tone 输入包含 NaN/Infinity")
        luma = np.sum(
            working * np.array([0.2126, 0.7152, 0.0722], np.float32),
            axis=2,
        )
        finite = luma[np.isfinite(luma)]
        if finite.size < 64:
            raise ISPError("Auto Tone 有效亮度样本不足")
        token.check()
        percentile_names = (0.1, 1.0, 50.0, 95.0, 99.0, 99.9)
        percentile_values = np.percentile(finite, percentile_names)
        p01, p1, p50, p95, p99, p999 = map(float, percentile_values)
        allowed = float(np.clip(maximum_allowed_clipping, 0.0, 0.2))
        guarded_percentile = 100.0 * (1.0 - allowed)
        guard_value = float(np.percentile(finite, guarded_percentile))

        if mode == "Natural":
            suggested = {
                "gamma": 2.2,
                "black_point": max(0.0, p01 * 0.5),
                "white_point": max(guard_value * 1.02, 0.1),
                "contrast": 1.0,
                "toe_strength": 0.08,
                "shoulder_strength": 0.22,
            }
        elif mode == "Preserve Highlights":
            suggested = {
                "gamma": 2.15,
                "black_point": max(0.0, p01 * 0.35),
                "white_point": max(p999 * 1.12, guard_value * 1.08, 1.0),
                "contrast": 0.96,
                "toe_strength": 0.05,
                "shoulder_strength": 0.55,
            }
        elif mode == "Lift Shadows":
            suggested = {
                "gamma": 2.55,
                "black_point": max(0.0, p01 * 0.15),
                "white_point": max(guard_value * 1.02, 0.1),
                "contrast": 0.94,
                "toe_strength": 0.0,
                "shoulder_strength": 0.28,
            }
        elif mode == "High Contrast":
            suggested = {
                "gamma": 2.1,
                "black_point": max(0.0, p1),
                "white_point": max(p99 * 0.94, 0.1),
                "contrast": 1.22,
                "toe_strength": 0.16,
                "shoulder_strength": 0.12,
            }
        else:
            suggested = {
                "gamma": 2.65,
                "black_point": max(0.0, p01 * 0.1),
                "white_point": max(p99 * 1.04, 0.1),
                "contrast": 1.03,
                "toe_strength": 0.0,
                "shoulder_strength": 0.38,
            }
        suggested["white_point"] = max(
            suggested["white_point"], suggested["black_point"] + 0.05
        )
        suggested = {
            **current_parameters,
            **suggested,
        }
        x = np.linspace(
            0.0, max(4.0, float(suggested["white_point"]) * 1.1),
            4096, dtype=np.float32,
        )
        curve = evaluate_tone_curve(x, suggested)
        warnings = []
        if not np.all(np.isfinite(curve)):
            raise ISPError("Auto Tone 建议曲线包含 NaN/Infinity")
        monotonic = bool(np.all(np.diff(curve) >= -1e-6))
        if not monotonic:
            warnings.append("建议曲线不是单调曲线，已回退到保守参数")
            suggested.update({
                "gamma": 2.2,
                "black_point": 0.0,
                "white_point": max(guard_value, 1.0),
                "contrast": 1.0,
                "toe_strength": 0.0,
                "shoulder_strength": 0.2,
            })
            curve = evaluate_tone_curve(x, suggested)
            monotonic = bool(np.all(np.diff(curve) >= -1e-6))

        mapped = evaluate_tone_curve(working[:, :, :3], suggested)
        predicted_high = float(np.mean(np.any(mapped >= 0.999, axis=2)))
        predicted_low = float(np.mean(np.all(mapped <= 0.001, axis=2)))
        before_high = float(np.mean(finite >= 1.0))
        before_low = float(np.mean(finite <= 0.001))
        if predicted_high > allowed + 0.005:
            warnings.append(
                f"预测高光裁剪 {predicted_high * 100:.2f}% 超过目标限制"
            )
        if p999 - p01 < 0.05:
            warnings.append("输入动态范围很窄，自动曲线可能缺少代表性")
        if p50 <= 0.005:
            warnings.append("图像中值亮度接近零，建议检查曝光或 BLC")
        dynamic_range = float(
            np.log2(max(p999, 1e-6) / max(p01, 1e-6))
        )
        confidence = float(
            np.clip(finite.size / 65536.0, 0.2, 1.0)
            * np.clip((p999 - p01) / 0.25, 0.2, 1.0)
        )
        clipping_map = (
            np.any(mapped >= 0.999, axis=2).astype(np.uint8)
            + np.all(mapped <= 0.001, axis=2).astype(np.uint8) * 2
        )
        return ParameterRecommendation(
            module_id=self.module_id,
            target_module_id=self.target_module_id,
            current_parameters=dict(current_parameters),
            suggested_parameters={
                key: suggested[key]
                for key in (
                    "gamma", "black_point", "white_point", "contrast",
                    "toe_strength", "shoulder_strength",
                )
            },
            measurements={
                "mode": mode,
                "percentiles": {
                    "p0.1": p01,
                    "p1": p1,
                    "p50": p50,
                    "p95": p95,
                    "p99": p99,
                    "p99.9": p999,
                },
                "mean_luminance": float(np.mean(finite)),
                "dynamic_range_stops": dynamic_range,
                "clipped_high_before": before_high,
                "clipped_low_before": before_low,
                "predicted_clipped_high": predicted_high,
                "predicted_clipped_low": predicted_low,
                "maximum_allowed_clipping": allowed,
                "curve_monotonic": monotonic,
            },
            confidence=confidence,
            warnings=warnings,
            artifacts={
                "Input Histogram": _histogram_image(finite),
                "Suggested Tone Curve": np.column_stack([x, curve]),
                "Current-Suggested Curve Comparison": _curve_comparison(
                    current_parameters, suggested
                ),
                "Clipping Prediction": clipping_map,
            },
            source_description=source_description,
            roi=roi,
            method=mode,
        )
