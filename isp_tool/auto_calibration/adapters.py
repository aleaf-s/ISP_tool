from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

import numpy as np

from ..calibration.ae import estimate_exposure
from ..calibration.awb import estimate_awb
from ..calibration.ccm_solver import apply_ccm, solve_ccm_from_patches
from ..calibration.flat_field import generate_lsc_mesh
from ..models import (
    ColorCheckerPatch,
    ImageROI,
    ISPError,
    ParameterRecommendation,
    RawMetadata,
)
from .base import CancellationToken, ModuleAnalyzer


class AWBAnalyzerAdapter(ModuleAnalyzer):
    module_id = "auto_white_balance"
    target_module_id = "white_balance"
    name = "Automatic White Balance"

    def analyze(
        self,
        image: np.ndarray,
        metadata: RawMetadata,
        current_parameters: Dict[str, Any],
        roi: Optional[ImageROI] = None,
        cancel_token: Optional[CancellationToken] = None,
        method: str = "Robust Neutral",
        source_description: str = "LSC output",
        **options: Any,
    ) -> ParameterRecommendation:
        token = cancel_token or CancellationToken()
        token.check()
        result = estimate_awb(
            image,
            metadata,
            method=method,
            roi=roi,
            low_percentile=float(options.get("low_percentile", 2.0)),
            high_percentile=float(options.get("high_percentile", 98.0)),
            gain_limit=float(options.get(
                "gain_limit", current_parameters.get("gain_limit", 8.0)
            )),
            shades_p=float(options.get("shades_p", 6.0)),
            neutral_tolerance=float(options.get("neutral_tolerance", 0.18)),
            data_state=options.get("data_state"),
        )
        warnings = []
        if result.diagnostics.get("gain_limited"):
            warnings.append("至少一个白平衡增益达到 Gain Limit")
        if result.confidence < 0.4:
            warnings.append("场景中性样本不足，AWB 结果置信度较低")
        if result.diagnostics.get("spatial_coverage", 1.0) < 0.25:
            warnings.append("AWB 样本集中在局部区域，建议框选中性灰 ROI")
        if result.diagnostics.get("green_mismatch", 0.0) > 0.05:
            warnings.append("Gr/Gb 差异偏大，请检查 BLC、坏点或照明均匀性")
        return ParameterRecommendation(
            module_id=self.module_id,
            target_module_id=self.target_module_id,
            current_parameters=dict(current_parameters),
            suggested_parameters={
                "r_gain": result.r_gain,
                "gr_gain": result.gr_gain,
                "gb_gain": result.gb_gain,
                "b_gain": result.b_gain,
            },
            measurements={
                "method": result.method,
                "sample_count": result.sample_count,
                **result.diagnostics,
            },
            confidence=result.confidence,
            warnings=warnings,
            artifacts=dict(result.artifacts),
            source_description=source_description,
            roi=roi,
            method=method,
        )


class AEAnalyzerAdapter(ModuleAnalyzer):
    module_id = "auto_exposure"
    target_module_id = "white_balance"
    name = "Automatic Exposure"

    def analyze(
        self,
        image: np.ndarray,
        metadata: RawMetadata,
        current_parameters: Dict[str, Any],
        roi: Optional[ImageROI] = None,
        cancel_token: Optional[CancellationToken] = None,
        method: str = "Highlight Protected",
        domain: str = "bayer",
        target_level: float = 0.45,
        source_description: str = "LSC output",
        **options: Any,
    ) -> ParameterRecommendation:
        token = cancel_token or CancellationToken()
        token.check()
        result = estimate_exposure(
            image,
            domain,
            metadata,
            method=method,
            target_level=float(target_level),
            measurement_percentile=float(options.get("measurement_percentile", 50.0)),
            highlight_percentile=float(options.get("highlight_percentile", 99.5)),
            maximum_gain=float(options.get(
                "maximum_gain", current_parameters.get("gain_limit", 8.0)
            )),
            maximum_allowed_clipping=float(
                options.get("maximum_allowed_clipping", 0.01)
            ),
            roi=roi,
            data_state=options.get("data_state"),
        )
        warnings = []
        if result.diagnostics.get("highlight_limited"):
            warnings.append("建议曝光增益受到高光保护限制")
        if result.predicted_clipped_ratio > 0.01:
            warnings.append("应用建议后仍可能存在超过 1% 的高光裁剪")
        sample_count = int(result.diagnostics.get("sample_count", 0))
        confidence = float(
            np.clip(sample_count / 65536.0, 0.2, 1.0)
            * np.clip(1.0 - result.predicted_clipped_ratio * 5.0, 0.4, 1.0)
        )
        return ParameterRecommendation(
            module_id=self.module_id,
            target_module_id=self.target_module_id,
            current_parameters=dict(current_parameters),
            suggested_parameters={"exposure_gain": result.suggested_gain},
            measurements={
                "target_parameter": "white_balance.exposure_gain",
                **result.to_dict(),
            },
            confidence=confidence,
            warnings=warnings,
            source_description=source_description,
            roi=roi,
            method=method,
        )


class LSCAnalyzerAdapter(ModuleAnalyzer):
    module_id = "flat_field_lsc"
    target_module_id = "lens_shading_correction"
    name = "Flat-field LSC"

    def analyze(
        self,
        image: np.ndarray,
        metadata: RawMetadata,
        current_parameters: Dict[str, Any],
        roi: Optional[ImageROI] = None,
        cancel_token: Optional[CancellationToken] = None,
        rows: int = 13,
        cols: int = 17,
        statistic: str = "Median",
        source_description: str = "Flat-field BLC output",
        **options: Any,
    ) -> ParameterRecommendation:
        del roi
        token = cancel_token or CancellationToken()
        token.check()
        mesh, diagnostics, artifacts = generate_lsc_mesh(
            image,
            metadata,
            rows=int(rows),
            cols=int(cols),
            statistic=statistic,
            reference=str(options.get("reference", "Center")),
            trim_fraction=float(options.get("trim_fraction", 0.05)),
            smoothing=float(options.get("smoothing", 0.7)),
            gain_limit=float(options.get(
                "gain_limit", current_parameters.get("max_gain", 3.0)
            )),
        )
        confidence = float(np.clip(
            1.0 - diagnostics["mean_cv_after"]
            / max(diagnostics["mean_cv_before"], 1e-8),
            0.0,
            1.0,
        ))
        warnings = []
        if diagnostics["mean_cv_after"] >= diagnostics["mean_cv_before"]:
            warnings.append("生成的 Mesh 没有改善平场均匀性")
        return ParameterRecommendation(
            module_id=self.module_id,
            target_module_id=self.target_module_id,
            current_parameters=dict(current_parameters),
            suggested_parameters={
                "mode": "Mesh Model",
                "mesh_strength": 1.0,
            },
            state_updates={"lsc_mesh": mesh.to_dict()},
            measurements={
                "mesh_rows": mesh.rows,
                "mesh_cols": mesh.cols,
                **diagnostics,
            },
            confidence=confidence,
            warnings=warnings,
            artifacts=artifacts,
            source_description=source_description,
            method=f"{statistic} {rows}x{cols}",
        )


class CCMAnalyzerAdapter(ModuleAnalyzer):
    module_id = "colorchecker_ccm"
    target_module_id = "color_correction_matrix"
    name = "ColorChecker CCM"

    def analyze(
        self,
        image: np.ndarray,
        metadata: RawMetadata,
        current_parameters: Dict[str, Any],
        roi: Optional[ImageROI] = None,
        cancel_token: Optional[CancellationToken] = None,
        patches: Optional[Sequence[ColorCheckerPatch]] = None,
        source_description: str = "ColorChecker patches",
        **options: Any,
    ) -> ParameterRecommendation:
        del metadata, roi
        token = cancel_token or CancellationToken()
        token.check()
        if not patches:
            raise ISPError("CCM Adapter 需要已采样的 ColorChecker 色块")
        result = solve_ccm_from_patches(
            patches,
            include_offset=bool(options.get("include_offset", True)),
            ridge=float(options.get("ridge", 0.015)),
            weights=options.get("weights"),
            white_constraint=bool(options.get("white_constraint", True)),
            row_sum_regularization=float(
                options.get("row_sum_regularization", 0.25)
            ),
            perceptual_weight=float(
                options.get("perceptual_weight", 0.08)
            ),
            structure_prior=bool(
                options.get("structure_prior", True)
            ),
            sign_regularization=float(
                options.get("sign_regularization", 0.35)
            ),
        )
        source = np.asarray(image, dtype=np.float32)
        if source.ndim == 3 and source.shape[2] >= 3:
            step = max(
                1,
                int(np.ceil(
                    np.sqrt(source.shape[0] * source.shape[1] / 250_000)
                )),
            )
            predicted_frame = apply_ccm(
                source[::step, ::step, :3],
                result.matrix,
                result.offset,
            )
            frame_negative_ratio = float(
                np.mean(predicted_frame < 0.0)
            )
            frame_overflow_ratio = float(
                np.mean(predicted_frame > 1.0)
            )
            result.diagnostics["frame_negative_ratio"] = (
                frame_negative_ratio
            )
            result.diagnostics["frame_overflow_ratio"] = (
                frame_overflow_ratio
            )
            rejection_reasons = list(
                result.diagnostics.get("rejection_reasons", [])
            )
            if frame_negative_ratio > 0.15:
                rejection_reasons.append(
                    "整幅校正预览出现大量负值"
                )
            if frame_overflow_ratio > 0.20:
                rejection_reasons.append(
                    "整幅校正预览出现大量通道溢出"
                )
            result.diagnostics["rejection_reasons"] = (
                rejection_reasons
            )
            result.diagnostics["safe_to_apply"] = not rejection_reasons
        suggested = {
            f"m{row}{col}": float(result.matrix[row, col])
            for row in range(3) for col in range(3)
        }
        suggested.update({
            "offset_r": float(result.offset[0]),
            "offset_g": float(result.offset[1]),
            "offset_b": float(result.offset[2]),
            "strength": 1.0,
        })
        warnings = list(
            result.diagnostics.get("rejection_reasons", [])
        )
        rejected_patch_ids = result.diagnostics.get(
            "rejected_patch_ids", []
        )
        if rejected_patch_ids:
            warnings.append(
                "已排除异常色块："
                + ", ".join(map(str, rejected_patch_ids))
            )
        improvement = (
            result.delta_e_before.get("mean", 0.0)
            - result.delta_e_after.get("mean", 0.0)
        )
        confidence = float(np.clip(
            improvement / max(result.delta_e_before.get("mean", 1.0), 1e-6),
            0.0,
            1.0,
        ))
        return ParameterRecommendation(
            module_id=self.module_id,
            target_module_id=self.target_module_id,
            current_parameters=dict(current_parameters),
            suggested_parameters=suggested,
            measurements={
                "method": result.method,
                "condition_number": result.condition_number,
                "delta_e_before": result.delta_e_before,
                "delta_e_initial": result.diagnostics.get(
                    "delta_e_initial", {}
                ),
                "delta_e_after": result.delta_e_after,
                "patch_count": len(result.patches),
                "valid_patch_count": len(
                    result.diagnostics.get("valid_patch_ids", [])
                ),
                "matrix": result.matrix.astype(float).tolist(),
                "offset": result.offset.astype(float).tolist(),
                "initial_matrix": result.diagnostics.get(
                    "initial_matrix"
                ),
                "initial_offset": result.diagnostics.get(
                    "initial_offset"
                ),
                "row_sums": result.diagnostics.get("row_sums"),
                "row_sums_initial": result.diagnostics.get(
                    "row_sums_initial"
                ),
                "diagonal_values": result.diagnostics.get(
                    "diagonal_values", []
                ),
                "positive_off_diagonal_count": result.diagnostics.get(
                    "positive_off_diagonal_count", 0
                ),
                "negative_off_diagonal_count": result.diagnostics.get(
                    "negative_off_diagonal_count", 0
                ),
                "safe_to_apply": bool(
                    result.diagnostics.get("safe_to_apply", False)
                ),
                "rejection_reasons": warnings,
                "negative_ratio": result.diagnostics.get(
                    "negative_ratio", 0.0
                ),
                "overflow_ratio": result.diagnostics.get(
                    "overflow_ratio", 0.0
                ),
                "frame_negative_ratio": result.diagnostics.get(
                    "frame_negative_ratio", 0.0
                ),
                "frame_overflow_ratio": result.diagnostics.get(
                    "frame_overflow_ratio", 0.0
                ),
                "valid_patch_ids": result.diagnostics.get(
                    "valid_patch_ids", []
                ),
                "rejected_patch_ids": rejected_patch_ids,
                "patches": [
                    patch.to_dict() for patch in result.patches
                ],
                "diagnostics": dict(result.diagnostics),
            },
            confidence=confidence,
            warnings=warnings,
            source_description=source_description,
            method=result.method,
        )
