from __future__ import annotations

from typing import Optional, Sequence

import numpy as np

from ..models import CCMCalibrationResult, ColorCheckerPatch, ISPError
from .delta_e import (
    delta_lch_components,
    delta_e_values,
    linear_srgb_to_lab,
    summarize_component,
    summarize_delta_e,
)

try:
    from scipy.optimize import least_squares
except ImportError:  # pragma: no cover
    least_squares = None


def apply_ccm(
    rgb: np.ndarray,
    matrix: np.ndarray,
    offset: Optional[np.ndarray] = None,
) -> np.ndarray:
    values = np.asarray(rgb, dtype=np.float64)
    transform = np.asarray(matrix, dtype=np.float64).reshape(3, 3)
    bias = (
        np.zeros(3, np.float64)
        if offset is None
        else np.asarray(offset, dtype=np.float64)
    )
    return np.einsum("...c,dc->...d", values, transform) + bias


def _delta_e(
    measured: np.ndarray,
    reference: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    # Lab conversion is undefined for strongly negative RGB.  Clipping here is
    # only for the perceptual metric; linear fitting still sees unclipped data.
    return delta_e_values(
        np.clip(measured, 0.0, 1.25),
        np.clip(reference, 0.0, 1.25),
        "CIE 2000",
    )


def _initial_regularized_fit(
    measured: np.ndarray,
    reference: np.ndarray,
    sample_weights: np.ndarray,
    include_offset: bool,
    identity_regularization: float,
    row_sum_regularization: float,
) -> tuple[np.ndarray, np.ndarray, float]:
    design = (
        np.column_stack([measured, np.ones(len(measured))])
        if include_offset else measured
    )
    sqrt_weights = np.sqrt(sample_weights)[:, None]
    weighted_design = design * sqrt_weights
    weighted_target = reference * sqrt_weights
    design_condition = float(np.linalg.cond(weighted_design))
    matrix = np.zeros((3, 3), np.float64)
    offset = np.zeros(3, np.float64)
    identity_strength = np.sqrt(max(identity_regularization, 0.0))
    row_strength = np.sqrt(max(row_sum_regularization, 0.0))
    offset_strength = np.sqrt(max(identity_regularization, 0.0))

    for output_channel in range(3):
        rows = [weighted_design]
        targets = [weighted_target[:, output_channel]]
        if identity_strength > 0:
            prior = np.zeros((3, design.shape[1]), np.float64)
            prior[:, :3] = np.eye(3) * identity_strength
            target_prior = np.zeros(3, np.float64)
            target_prior[output_channel] = identity_strength
            rows.append(prior)
            targets.append(target_prior)
        if row_strength > 0:
            row_prior = np.zeros((1, design.shape[1]), np.float64)
            row_prior[0, :3] = row_strength
            rows.append(row_prior)
            targets.append(np.array([row_strength]))
        if include_offset and offset_strength > 0:
            bias_prior = np.zeros((1, design.shape[1]), np.float64)
            bias_prior[0, -1] = offset_strength
            rows.append(bias_prior)
            targets.append(np.zeros(1))
        coefficients = np.linalg.lstsq(
            np.vstack(rows),
            np.concatenate(targets),
            rcond=None,
        )[0]
        matrix[output_channel] = coefficients[:3]
        if include_offset:
            offset[output_channel] = coefficients[3]
    return matrix, offset, design_condition


def _parameter_bounds(
    include_offset: bool,
    structure_prior: bool,
) -> tuple[np.ndarray, np.ndarray]:
    # The familiar positive-diagonal / mostly-negative-off-diagonal CCM shape
    # is an engineering prior, not a physical law.  Keep only broad numerical
    # safety bounds here; the typical shape is encouraged by soft residuals.
    lower_matrix = np.full((3, 3), -1.25, np.float64)
    upper_matrix = np.full((3, 3), 1.25, np.float64)
    np.fill_diagonal(lower_matrix, 0.10)
    np.fill_diagonal(upper_matrix, 2.75)
    lower = lower_matrix.ravel()
    upper = upper_matrix.ravel()
    if include_offset:
        offset_limit = 0.06 if structure_prior else 0.20
        lower = np.concatenate([lower, np.full(3, -offset_limit)])
        upper = np.concatenate([upper, np.full(3, offset_limit)])
    return lower, upper


def _pack(
    matrix: np.ndarray,
    offset: np.ndarray,
    include_offset: bool,
) -> np.ndarray:
    return (
        np.concatenate([matrix.ravel(), offset])
        if include_offset else matrix.ravel()
    )


def _unpack(
    values: np.ndarray,
    include_offset: bool,
) -> tuple[np.ndarray, np.ndarray]:
    matrix = np.asarray(values[:9], dtype=np.float64).reshape(3, 3)
    offset = (
        np.asarray(values[9:12], dtype=np.float64)
        if include_offset else np.zeros(3, np.float64)
    )
    return matrix, offset


def _weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    """Return a deterministic weighted median for robust scalar fitting."""

    data = np.asarray(values, dtype=np.float64).reshape(-1)
    importance = np.asarray(weights, dtype=np.float64).reshape(-1)
    order = np.argsort(data)
    data = data[order]
    importance = importance[order]
    cumulative = np.cumsum(importance)
    threshold = float(cumulative[-1]) * 0.5
    index = min(int(np.searchsorted(cumulative, threshold)), len(data) - 1)
    return float(data[index])


def estimate_global_exposure_gain(
    measured_rgb: np.ndarray,
    reference_rgb: np.ndarray,
    sample_weights: Optional[Sequence[float]] = None,
    minimum_gain: float = 0.25,
    maximum_gain: float = 4.0,
) -> tuple[float, dict]:
    """Robustly match chart brightness before fitting colour coefficients.

    Low-chroma patches are preferred because their luminance ratio is less
    sensitive to camera colour cross-talk.  The weighted median is evaluated
    in log-exposure space so a contaminated patch cannot pull the estimate.
    """

    measured = np.asarray(measured_rgb, dtype=np.float64)
    reference = np.asarray(reference_rgb, dtype=np.float64)
    weights = (
        np.ones(len(measured), dtype=np.float64)
        if sample_weights is None
        else np.asarray(sample_weights, dtype=np.float64).reshape(-1)
    )
    luma_vector = np.array((0.2126729, 0.7151522, 0.0721750))
    measured_luma = measured @ luma_vector
    reference_luma = reference @ luma_vector
    reference_lab = linear_srgb_to_lab(np.clip(reference, 0.0, 1.25))
    reference_chroma = np.hypot(reference_lab[:, 1], reference_lab[:, 2])
    finite = (
        np.isfinite(measured_luma)
        & np.isfinite(reference_luma)
        & (measured_luma > 1e-5)
        & (reference_luma > 1e-5)
    )
    neutral = finite & (reference_chroma < 14.0)
    selected = neutral if np.count_nonzero(neutral) >= 3 else finite
    if not np.any(selected):
        return 1.0, {
            "method": "none",
            "sample_count": 0,
            "clipped_to_bounds": False,
        }
    log_ratios = np.log(reference_luma[selected] / measured_luma[selected])
    raw_gain = float(np.exp(_weighted_median(log_ratios, weights[selected])))
    gain = float(np.clip(raw_gain, minimum_gain, maximum_gain))
    return gain, {
        "method": "neutral weighted median log-luminance ratio",
        "sample_count": int(np.count_nonzero(selected)),
        "used_neutral_patches": bool(np.count_nonzero(neutral) >= 3),
        "raw_gain": raw_gain,
        "minimum_gain": float(minimum_gain),
        "maximum_gain": float(maximum_gain),
        "clipped_to_bounds": bool(abs(gain - raw_gain) > 1e-10),
    }


def solve_ccm(
    measured_rgb: np.ndarray,
    reference_rgb: np.ndarray,
    include_offset: bool = True,
    ridge: float = 0.0,
    weights: Optional[Sequence[float]] = None,
    white_constraint: bool = False,
    row_sum_regularization: float = 0.0,
    perceptual_weight: float = 0.0,
    structure_prior: bool = False,
    sign_regularization: float = 0.35,
    lightness_weight: float = 0.02,
    chroma_weight: float = 1.0,
    hue_weight: float = 1.0,
    normalize_exposure: bool = False,
) -> CCMCalibrationResult:
    """Fit a stable CCM in linear RGB, then refine it perceptually.

    ``ridge`` is an identity-centred regularizer rather than a zero-centred
    coefficient penalty.  This keeps a weakly constrained solution close to
    no correction and is much safer for interactive calibration.
    """
    measured = np.asarray(measured_rgb, dtype=np.float64)
    reference = np.asarray(reference_rgb, dtype=np.float64)
    if (
        measured.shape != reference.shape
        or measured.ndim != 2
        or measured.shape[1] != 3
    ):
        raise ISPError("CCM 求解输入必须是形状相同的 N×3 数组")
    if measured.shape[0] < (6 if include_offset else 5):
        raise ISPError("CCM 求解至少需要 6 个有效色块")
    if not np.all(np.isfinite(measured)) or not np.all(np.isfinite(reference)):
        raise ISPError("CCM 求解输入包含 NaN 或 Infinity")

    sample_weights = np.ones(len(measured), np.float64)
    if weights is not None:
        sample_weights = np.asarray(weights, dtype=np.float64)
        if (
            sample_weights.shape != (len(measured),)
            or np.any(~np.isfinite(sample_weights))
            or np.any(sample_weights <= 0)
        ):
            raise ISPError("CCM 权重必须是 N 个有限正数")
    sample_weights /= max(float(np.mean(sample_weights)), 1e-8)

    reference_lab_for_fit = linear_srgb_to_lab(np.clip(reference, 0.0, 1.25))
    exposure_gain = 1.0
    exposure_diagnostics = {
        "method": "disabled",
        "sample_count": 0,
        "clipped_to_bounds": False,
    }
    if normalize_exposure:
        exposure_gain, exposure_diagnostics = estimate_global_exposure_gain(
            measured,
            reference,
            sample_weights,
            minimum_gain=0.25,
            maximum_gain=4.0,
        )
    fit_measured = measured * exposure_gain

    identity_regularization = max(float(ridge), 0.0)
    row_regularization = max(float(row_sum_regularization), 0.0)
    if white_constraint:
        row_regularization = max(row_regularization, 0.25)
    initial_matrix, initial_offset, design_condition = (
        _initial_regularized_fit(
            fit_measured,
            reference,
            sample_weights,
            include_offset,
            identity_regularization,
            row_regularization,
        )
    )
    use_structure_prior = bool(structure_prior)
    sign_strength = max(float(sign_regularization), 0.0)
    lower, upper = _parameter_bounds(
        include_offset,
        use_structure_prior,
    )
    initial_parameters = np.clip(
        _pack(initial_matrix, initial_offset, include_offset),
        lower + 1e-8,
        upper - 1e-8,
    )
    sqrt_weights = np.sqrt(sample_weights)[:, None]
    identity = np.eye(3, dtype=np.float64)
    lightness_strength = max(float(lightness_weight), 0.0)
    chroma_strength = max(float(chroma_weight), 0.0)
    hue_strength = max(float(hue_weight), 0.0)

    def residuals(parameters: np.ndarray) -> np.ndarray:
        matrix, offset = _unpack(parameters, include_offset)
        predicted = apply_ccm(fit_measured, matrix, offset)
        # The regularised linear fit supplies a stable starting point.  The
        # nonlinear phase then optimises CIE Lab a*/b* directly: global
        # brightness has already been handled by ``exposure_gain`` and must
        # not be disguised as colour-matrix coefficients.  A small optional
        # L* guard exists only to prevent pathological luminance drift.
        parts = []
        if perceptual_weight <= 0 or not normalize_exposure:
            parts.append(((predicted - reference) * sqrt_weights).ravel())
        if identity_regularization > 0:
            parts.append(
                np.sqrt(identity_regularization)
                * (matrix - identity).ravel()
            )
            if include_offset:
                parts.append(
                    np.sqrt(identity_regularization) * offset
                )
        if row_regularization > 0:
            parts.append(
                np.sqrt(row_regularization)
                * (matrix.sum(axis=1) - 1.0)
            )
        if use_structure_prior and sign_strength > 0:
            off_diagonal_values = matrix[~np.eye(3, dtype=bool)]
            parts.append(
                np.sqrt(sign_strength)
                * np.maximum(off_diagonal_values - 0.02, 0.0)
            )
            diagonal = np.diag(matrix)
            # Typical hardware CCMs often have 1..2.5 diagonal terms.  These
            # are soft penalties only, so valid atypical sensors remain
            # representable and can win when their colour error is lower.
            parts.append(
                np.sqrt(sign_strength * 0.18)
                * np.maximum(1.0 - diagonal, 0.0)
            )
            parts.append(
                np.sqrt(sign_strength * 0.18)
                * np.maximum(diagonal - 2.5, 0.0)
            )
            parts.append(
                np.sqrt(sign_strength * 0.10)
                * np.maximum(np.abs(off_diagonal_values) - 0.75, 0.0)
            )
        if perceptual_weight > 0:
            predicted_lab = linear_srgb_to_lab(
                np.clip(predicted, 0.0, 1.25)
            )
            ab_strength = max(
                0.5 * (chroma_strength + hue_strength), 1e-8
            )
            parts.append(
                np.sqrt(perceptual_weight * ab_strength)
                * (predicted_lab[:, 1:3] - reference_lab_for_fit[:, 1:3])
                / 50.0
                * sqrt_weights
            )
            if lightness_strength > 0:
                parts.append(
                    np.sqrt(perceptual_weight * lightness_strength)
                    * (predicted_lab[:, 0] - reference_lab_for_fit[:, 0])
                    / 100.0
                    * sqrt_weights[:, 0]
                )
            neutral = reference_lab_for_fit[:, 1:3]
            neutral_mask = np.hypot(neutral[:, 0], neutral[:, 1]) < 12.0
            if np.any(neutral_mask):
                parts.append(
                    np.sqrt(perceptual_weight * 0.35)
                    * (predicted_lab[neutral_mask, 1:3] - neutral[neutral_mask])
                    / 50.0
                    * sqrt_weights[neutral_mask]
                )
        return np.concatenate([part.ravel() for part in parts])

    optimized_parameters = initial_parameters
    optimizer_status = "regularized_linear_only"
    optimizer_cost = None
    if least_squares is not None:
        optimized = least_squares(
            residuals,
            initial_parameters,
            bounds=(lower, upper),
            method="trf",
            loss="soft_l1",
            f_scale=0.02,
            max_nfev=350,
        )
        optimized_parameters = optimized.x
        optimizer_status = str(optimized.message)
        optimizer_cost = float(optimized.cost)

    matrix, offset = _unpack(optimized_parameters, include_offset)
    predicted_exposure = fit_measured
    predicted_initial = apply_ccm(fit_measured, initial_matrix, initial_offset)
    predicted_after = apply_ccm(fit_measured, matrix, offset)
    delta_before, input_lab, reference_lab = _delta_e(measured, reference)
    delta_exposure, exposure_lab, _ = _delta_e(predicted_exposure, reference)
    delta_initial, initial_lab, _ = _delta_e(predicted_initial, reference)
    delta_after, corrected_lab, reference_lab = _delta_e(
        predicted_after, reference
    )
    lch_before = delta_lch_components(input_lab, reference_lab)
    lch_exposure = delta_lch_components(exposure_lab, reference_lab)
    lch_initial = delta_lch_components(initial_lab, reference_lab)
    lch_after = delta_lch_components(corrected_lab, reference_lab)
    delta76_before, _, _ = delta_e_values(
        np.clip(measured, 0.0, 1.25),
        np.clip(reference, 0.0, 1.25),
        "CIE 1976",
    )
    delta76_after, _, _ = delta_e_values(
        np.clip(predicted_after, 0.0, 1.25),
        np.clip(reference, 0.0, 1.25),
        "CIE 1976",
    )
    matrix_condition = float(np.linalg.cond(matrix))
    row_sums = matrix.sum(axis=1)
    diagonal_values = np.diag(matrix)
    off_diagonal_values = matrix[~np.eye(3, dtype=bool)]
    positive_off_diagonal_count = int(
        np.count_nonzero(off_diagonal_values > 1e-5)
    )
    negative_off_diagonal_count = int(
        np.count_nonzero(off_diagonal_values < -1e-5)
    )
    negative_ratio = float(np.mean(predicted_after < 0.0))
    overflow_ratio = float(np.mean(predicted_after > 1.0))
    before_summary = summarize_delta_e(delta_before)
    initial_summary = summarize_delta_e(delta_initial)
    after_summary = summarize_delta_e(delta_after)

    def component_summary(components) -> dict:
        return {
            "delta_l": summarize_component(components["delta_l"]),
            "delta_c": summarize_component(components["delta_c"]),
            "delta_h": summarize_component(components["delta_h"]),
            "delta_h_degrees": summarize_component(
                components["delta_h_degrees"][components["hue_defined"]]
            ),
        }

    component_before_summary = component_summary(lch_before)
    component_exposure_summary = component_summary(lch_exposure)
    component_initial_summary = component_summary(lch_initial)
    component_after_summary = component_summary(lch_after)
    chroma_hue_before = np.hypot(
        lch_exposure["delta_c"], lch_exposure["delta_h"]
    )
    chroma_hue_after = np.hypot(
        lch_after["delta_c"], lch_after["delta_h"]
    )

    rejection_reasons = []
    minimum_improvement = max(
        0.20, before_summary["mean"] * 0.02
    )
    if before_summary["mean"] - after_summary["mean"] < minimum_improvement:
        rejection_reasons.append("平均 ΔE 未明显降低")
    if after_summary["max"] > before_summary["max"] * 1.15 + 0.5:
        rejection_reasons.append("最大 ΔE 异常增大")
    if not np.all(np.diag(matrix) > 0.0):
        rejection_reasons.append("CCM 主对角线存在非正元素")
    structural_warnings = []
    if use_structure_prior and np.any(
        (diagonal_values < 1.0) | (diagonal_values > 2.5)
    ):
        structural_warnings.append("部分主对角元素超出常见 1.0～2.5 范围")
    if use_structure_prior and positive_off_diagonal_count > 2:
        structural_warnings.append("CCM 正非对角元素较多")
    off_diagonal = np.abs(matrix.copy())
    np.fill_diagonal(off_diagonal, 0.0)
    if np.any(np.diag(matrix) <= np.max(off_diagonal, axis=1)):
        rejection_reasons.append("CCM 主对角线未主导对应行")
    if np.max(np.abs(matrix)) > 2.75:
        rejection_reasons.append("CCM 元素绝对值过大")
    if np.any(np.abs(row_sums - 1.0) > 0.35):
        rejection_reasons.append("CCM 行和偏离 1 过多")
    if not np.isfinite(matrix_condition) or matrix_condition > 50.0:
        rejection_reasons.append("CCM 条件数过高")
    if negative_ratio > 0.15:
        rejection_reasons.append("校正后负值比例过高")
    if overflow_ratio > 0.20:
        rejection_reasons.append("校正后通道溢出比例过高")
    chroma_hue_before_mean = float(np.mean(chroma_hue_before))
    chroma_hue_after_mean = float(np.mean(chroma_hue_after))
    if (
        chroma_hue_before_mean > 0.75
        and chroma_hue_after_mean
        > chroma_hue_before_mean * 0.98 + 0.05
    ):
        rejection_reasons.append("综合色度/色相误差未明显降低")
    if component_exposure_summary["delta_l"]["mean_abs"] > 6.0:
        structural_warnings.append(
            "全局曝光匹配后仍有明显明度差；请检查光照均匀性或 Tone Curve"
        )
    if exposure_diagnostics.get("clipped_to_bounds"):
        structural_warnings.append(
            "Pre-CCM Exposure 已达到安全范围边界，请检查 RAW 归一化和曝光"
        )

    return CCMCalibrationResult(
        matrix.astype(np.float32),
        offset.astype(np.float32),
        (
            ("Exposure matched + " if normalize_exposure else "")
            + ("constrained " if use_structure_prior else "")
            + "Lab a*b* CCM"
        ),
        matrix_condition,
        before_summary,
        after_summary,
        [],
        {
            "ridge": identity_regularization,
            "row_sum_regularization": row_regularization,
            "perceptual_weight": float(perceptual_weight),
            "lightness_weight": lightness_strength,
            "chroma_weight": chroma_strength,
            "hue_weight": hue_strength,
            "exposure_normalization_enabled": bool(normalize_exposure),
            "exposure_normalization_gain": exposure_gain,
            "pre_ccm_exposure_gain": exposure_gain,
            "exposure_match": exposure_diagnostics,
            "optimisation_target": (
                "CIE Lab a*b* (L* guard only)"
                if normalize_exposure
                else "linear RGB + CIE Lab a*b*"
            ),
            "structure_prior": use_structure_prior,
            "sign_regularization": sign_strength,
            "white_constraint": bool(white_constraint),
            "sample_count": int(len(measured)),
            "sample_weights": sample_weights.astype(float).tolist(),
            "initial_matrix": initial_matrix.astype(float).tolist(),
            "initial_offset": initial_offset.astype(float).tolist(),
            "predicted_initial_rgb": predicted_initial.astype(float).tolist(),
            "predicted_rgb": predicted_after.astype(float).tolist(),
            "predicted_exposure_rgb": predicted_exposure.astype(float).tolist(),
            "measured_rgb": measured.astype(float).tolist(),
            "reference_rgb": reference.astype(float).tolist(),
            "input_lab": input_lab.astype(float).tolist(),
            "exposure_matched_lab": exposure_lab.astype(float).tolist(),
            "initial_lab": initial_lab.astype(float).tolist(),
            "corrected_lab": corrected_lab.astype(float).tolist(),
            "reference_lab": reference_lab.astype(float).tolist(),
            "delta_e_before_values": delta_before.astype(float).tolist(),
            "delta_e_initial_values": delta_initial.astype(float).tolist(),
            "delta_e_after_values": delta_after.astype(float).tolist(),
            "delta_e_after_exposure_values": delta_exposure.astype(float).tolist(),
            "delta_e_exposure_normalized_initial_values": delta_initial.astype(float).tolist(),
            "delta_e_exposure_normalized_after_values": delta_after.astype(float).tolist(),
            "delta_e_exposure_normalized_initial": summarize_delta_e(
                delta_initial
            ),
            "delta_e_exposure_normalized_after": summarize_delta_e(
                delta_after
            ),
            "delta_e_after_exposure": summarize_delta_e(delta_exposure),
            "delta_e_initial": initial_summary,
            "delta_lch_before": component_before_summary,
            "delta_lch_after_exposure": component_exposure_summary,
            "delta_lch_initial": component_initial_summary,
            "delta_lch_after": component_after_summary,
            "chroma_hue_error_before": summarize_component(
                chroma_hue_before
            ),
            "chroma_hue_error_after": summarize_component(
                chroma_hue_after
            ),
            "delta_e76_before": summarize_delta_e(
                delta76_before
            ),
            "delta_e76_after": summarize_delta_e(
                delta76_after
            ),
            "row_sums_initial": initial_matrix.sum(axis=1).astype(float).tolist(),
            "row_sums": row_sums.astype(float).tolist(),
            "diagonal_values": diagonal_values.astype(float).tolist(),
            "off_diagonal_values": (
                off_diagonal_values.astype(float).tolist()
            ),
            "positive_off_diagonal_count": positive_off_diagonal_count,
            "negative_off_diagonal_count": negative_off_diagonal_count,
            "design_condition_number": design_condition,
            "matrix_condition_number": matrix_condition,
            "negative_ratio": negative_ratio,
            "overflow_ratio": overflow_ratio,
            "optimizer_status": optimizer_status,
            "optimizer_cost": optimizer_cost,
            "safe_to_apply": not rejection_reasons,
            "rejection_reasons": rejection_reasons,
            "structural_warnings": structural_warnings,
        },
    )


def solve_ccm_from_patches(
    patches: Sequence[ColorCheckerPatch],
    include_offset: bool = True,
    ridge: float = 0.015,
    weights: Optional[Sequence[float]] = None,
    white_constraint: bool = True,
    row_sum_regularization: float = 0.25,
    perceptual_weight: float = 0.80,
    structure_prior: bool = True,
    sign_regularization: float = 0.35,
    lightness_weight: float = 0.02,
    chroma_weight: float = 1.0,
    hue_weight: float = 1.0,
    normalize_exposure: bool = True,
) -> CCMCalibrationResult:
    # Work on copies: automatic quality rejection is diagnostic state for this
    # fit and must not silently mutate the caller's persistent ROI samples.
    all_patches = [
        ColorCheckerPatch.from_dict(patch.to_dict()) for patch in patches
    ]
    valid_indices = [
        index
        for index, patch in enumerate(all_patches)
        if bool(patch.diagnostics.get("valid", True))
        and np.all(np.isfinite(patch.measured_rgb))
        and np.all(np.isfinite(patch.reference_rgb))
    ]
    if len(valid_indices) < 6:
        raise ISPError(
            f"CCM 校准至少需要 6 个有效色块，当前仅 {len(valid_indices)} 个"
        )
    def automatic_weights(selected_patches):
        auto_weights = []
        for patch in selected_patches:
            weight = 1.0
            reference_index = int(
                patch.diagnostics.get(
                    "reference_index", patch.patch_id - 1
                )
            )
            if reference_index in {18, 19, 20, 21, 22, 23}:
                weight *= 2.5
            elif reference_index in {0, 1}:
                weight *= 1.8
            variation = float(
                patch.diagnostics.get("variation", 0.0)
            )
            weight *= 1.0 / (1.0 + variation * 4.0)
            weight *= float(np.clip(
                patch.diagnostics.get("quality_score", 1.0),
                0.10,
                1.0,
            ))
            auto_weights.append(weight)
        return np.asarray(auto_weights, dtype=np.float64)

    def selected_values(indices):
        selected_patches = [all_patches[index] for index in indices]
        measured_values = np.stack([
            patch.measured_rgb for patch in selected_patches
        ])
        reference_values = np.stack([
            patch.reference_rgb for patch in selected_patches
        ])
        return selected_patches, measured_values, reference_values

    valid_patches, measured, reference = selected_values(valid_indices)
    if weights is None:
        selected_weights = automatic_weights(valid_patches)
    else:
        provided = np.asarray(weights, dtype=np.float64)
        if provided.shape == (len(all_patches),):
            selected_weights = provided[valid_indices]
        elif provided.shape == (len(valid_patches),):
            selected_weights = provided
        else:
            raise ISPError("CCM 权重数量与有效色块数量不一致")

    result = solve_ccm(
        measured,
        reference,
        include_offset,
        ridge,
        selected_weights,
        white_constraint,
        row_sum_regularization,
        perceptual_weight,
        structure_prior,
        sign_regularization,
        lightness_weight,
        chroma_weight,
        hue_weight,
        normalize_exposure,
    )

    # A single misdetected/reflected patch can pull all nine coefficients.  A
    # preliminary robust fit therefore gets one chance to reject only gross
    # residual outliers.  Broadly wrong orientation is intentionally *not*
    # hidden: when many patches disagree, safety validation still fails.
    preliminary_delta = np.asarray(
        result.diagnostics.get(
            "delta_e_exposure_normalized_after_values",
            result.diagnostics.get("delta_e_after_values", []),
        ),
        dtype=np.float64,
    )
    auto_rejected_indices = []
    if preliminary_delta.size == len(valid_indices) and len(valid_indices) >= 12:
        center = float(np.median(preliminary_delta))
        mad = float(np.median(np.abs(preliminary_delta - center)))
        robust_scale = max(1.4826 * mad, 0.5)
        cutoff = max(12.0, center + 3.5 * robust_scale)
        candidates = np.flatnonzero(preliminary_delta > cutoff)
        if 0 < len(candidates) <= 4 and len(valid_indices) - len(candidates) >= 12:
            auto_rejected_indices = [valid_indices[int(i)] for i in candidates]
            for index in auto_rejected_indices:
                patch = all_patches[index]
                patch.diagnostics["valid"] = False
                reasons = list(patch.diagnostics.get("reasons", []))
                reasons.append("拟合残差异常")
                patch.diagnostics["reasons"] = reasons
            valid_indices = [
                index for index in valid_indices
                if index not in auto_rejected_indices
            ]
            valid_patches, measured, reference = selected_values(valid_indices)
            selected_weights = (
                automatic_weights(valid_patches)
                if weights is None
                else provided[valid_indices]
                if provided.shape == (len(all_patches),)
                else np.delete(provided, candidates)
            )
            result = solve_ccm(
                measured,
                reference,
                include_offset,
                ridge,
                selected_weights,
                white_constraint,
                row_sum_regularization,
                perceptual_weight,
                structure_prior,
                sign_regularization,
                lightness_weight,
                chroma_weight,
                hue_weight,
                normalize_exposure,
            )
    exposure_gain = float(
        result.diagnostics.get("pre_ccm_exposure_gain", 1.0)
    )
    corrected = apply_ccm(
        measured * exposure_gain, result.matrix, result.offset
    )
    delta, corrected_lab, reference_lab = _delta_e(
        corrected, reference
    )
    _, input_lab, _ = _delta_e(measured, reference)
    before_components = delta_lch_components(input_lab, reference_lab)
    after_components = delta_lch_components(corrected_lab, reference_lab)
    before_values = result.diagnostics["delta_e_before_values"]
    exposure_values = result.diagnostics["delta_e_after_exposure_values"]
    exposure_rgb_values = result.diagnostics["predicted_exposure_rgb"]
    exposure_lab_values = result.diagnostics["exposure_matched_lab"]
    initial_values = result.diagnostics["delta_e_initial_values"]
    corrected_values = result.diagnostics["predicted_rgb"]
    result.patches = []
    for index, patch in enumerate(valid_patches):
        copied = ColorCheckerPatch.from_dict(patch.to_dict())
        copied.measured_lab = input_lab[index].astype(np.float32)
        copied.reference_lab = reference_lab[index].astype(np.float32)
        copied.delta_e = float(delta[index])
        copied.diagnostics.update({
            "delta_e_before": float(before_values[index]),
            "delta_e_after_exposure": float(exposure_values[index]),
            "delta_e_initial": float(initial_values[index]),
            "delta_e_after": float(delta[index]),
            "corrected_rgb": corrected_values[index],
            "input_lab": input_lab[index].astype(float).tolist(),
            "exposure_matched_rgb": exposure_rgb_values[index],
            "exposure_matched_lab": exposure_lab_values[index],
            "reference_lab": reference_lab[index].astype(float).tolist(),
            "corrected_lab": corrected_lab[index].astype(float).tolist(),
            "input_lch": before_components["measured_lch"][index].astype(float).tolist(),
            "reference_lch": before_components["reference_lch"][index].astype(float).tolist(),
            "corrected_lch": after_components["measured_lch"][index].astype(float).tolist(),
            "delta_l_before": float(before_components["delta_l"][index]),
            "delta_c_before": float(before_components["delta_c"][index]),
            "delta_h_before": float(before_components["delta_h"][index]),
            "delta_h_degrees_before": float(before_components["delta_h_degrees"][index]),
            "delta_l_after": float(after_components["delta_l"][index]),
            "delta_c_after": float(after_components["delta_c"][index]),
            "delta_h_after": float(after_components["delta_h"][index]),
            "delta_h_degrees_after": float(after_components["delta_h_degrees"][index]),
            "hue_defined_before": bool(before_components["hue_defined"][index]),
            "hue_defined_after": bool(after_components["hue_defined"][index]),
        })
        result.patches.append(copied)
    for index, patch in enumerate(all_patches):
        if index in valid_indices:
            continue
        copied = ColorCheckerPatch.from_dict(patch.to_dict())
        copied.diagnostics.update({
            "delta_e_before": float(patch.delta_e),
            "delta_e_initial": None,
            "delta_e_after": None,
            "corrected_rgb": None,
        })
        result.patches.append(copied)
    result.patches.sort(key=lambda patch: patch.patch_id)

    neutral_positions = [
        index
        for index, patch in enumerate(valid_patches)
        if int(
            patch.diagnostics.get(
                "reference_index", patch.patch_id - 1
            )
        ) in {18, 19, 20, 21, 22, 23}
    ]
    rejection_reasons = list(
        result.diagnostics.get("rejection_reasons", [])
    )
    if len(valid_patches) < 12:
        rejection_reasons.append(
            "有效色块不足 12 个，结果不适合自动应用"
        )
    if neutral_positions:
        neutral_before = np.asarray(before_values)[neutral_positions]
        neutral_after = np.asarray(delta)[neutral_positions]
        result.diagnostics["neutral_delta_e_before"] = (
            summarize_delta_e(neutral_before)
        )
        result.diagnostics["neutral_delta_e_after"] = (
            summarize_delta_e(neutral_after)
        )
        if (
            float(np.mean(neutral_after))
            > float(np.mean(neutral_before)) * 1.10 + 0.25
        ):
            rejection_reasons.append("中性色块校正后偏色增大")
    result.diagnostics.update({
        "valid_patch_ids": [
            patch.patch_id for patch in valid_patches
        ],
        "rejected_patch_ids": [
            patch.patch_id
            for index, patch in enumerate(all_patches)
            if index not in valid_indices
        ],
        "auto_rejected_patch_ids": [
            all_patches[index].patch_id
            for index in auto_rejected_indices
        ],
        "patch_diagnostics": {
            str(patch.patch_id): dict(patch.diagnostics)
            for patch in all_patches
        },
        "rejection_reasons": rejection_reasons,
        "safe_to_apply": not rejection_reasons,
    })
    return result
