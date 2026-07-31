from __future__ import annotations

from typing import Optional, Sequence

import numpy as np

from ..models import CCMCalibrationResult, ColorCheckerPatch, ISPError
from .delta_e import (
    delta_e_values,
    linear_srgb_to_lab,
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
    offset_strength = np.sqrt(max(identity_regularization * 0.25, 0.0))

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
    lower_matrix = np.full((3, 3), -1.25, np.float64)
    upper_matrix = np.full((3, 3), 1.25, np.float64)
    np.fill_diagonal(
        lower_matrix,
        1.0001 if structure_prior else 0.10,
    )
    np.fill_diagonal(upper_matrix, 2.75)
    if structure_prior:
        upper_matrix[~np.eye(3, dtype=bool)] = 0.08
    lower = lower_matrix.ravel()
    upper = upper_matrix.ravel()
    if include_offset:
        lower = np.concatenate([lower, np.full(3, -0.20)])
        upper = np.concatenate([upper, np.full(3, 0.20)])
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

    identity_regularization = max(float(ridge), 0.0)
    row_regularization = max(float(row_sum_regularization), 0.0)
    if white_constraint:
        row_regularization = max(row_regularization, 0.25)
    initial_matrix, initial_offset, design_condition = (
        _initial_regularized_fit(
            measured,
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

    def residuals(parameters: np.ndarray) -> np.ndarray:
        matrix, offset = _unpack(parameters, include_offset)
        predicted = apply_ccm(measured, matrix, offset)
        parts = [
            ((predicted - reference) * sqrt_weights).ravel(),
        ]
        if identity_regularization > 0:
            parts.append(
                np.sqrt(identity_regularization)
                * (matrix - identity).ravel()
            )
            if include_offset:
                parts.append(
                    np.sqrt(identity_regularization * 0.25) * offset
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
                * np.maximum(off_diagonal_values, 0.0)
            )
        if perceptual_weight > 0:
            predicted_lab = linear_srgb_to_lab(
                np.clip(predicted, 0.0, 1.25)
            )
            reference_lab = linear_srgb_to_lab(
                np.clip(reference, 0.0, 1.25)
            )
            parts.append(
                np.sqrt(perceptual_weight)
                * ((predicted_lab - reference_lab) / 100.0)
                * sqrt_weights
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
    predicted_initial = apply_ccm(
        measured, initial_matrix, initial_offset
    )
    predicted_after = apply_ccm(measured, matrix, offset)
    delta_before, _, _ = _delta_e(measured, reference)
    delta_initial, _, _ = _delta_e(predicted_initial, reference)
    delta_after, measured_lab, reference_lab = _delta_e(
        predicted_after, reference
    )
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
    if use_structure_prior and not np.all(diagonal_values > 1.0):
        rejection_reasons.append("CCM 主对角线没有全部大于 1")
    if use_structure_prior and positive_off_diagonal_count > 2:
        rejection_reasons.append("CCM 非对角正元素过多")
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

    return CCMCalibrationResult(
        matrix.astype(np.float32),
        offset.astype(np.float32),
        (
            "Signed constrained weighted CCM + perceptual refinement"
            if use_structure_prior
            else "Constrained weighted CCM + perceptual refinement"
        ),
        matrix_condition,
        before_summary,
        after_summary,
        [],
        {
            "ridge": identity_regularization,
            "row_sum_regularization": row_regularization,
            "perceptual_weight": float(perceptual_weight),
            "structure_prior": use_structure_prior,
            "sign_regularization": sign_strength,
            "white_constraint": bool(white_constraint),
            "sample_count": int(len(measured)),
            "sample_weights": sample_weights.astype(float).tolist(),
            "initial_matrix": initial_matrix.astype(float).tolist(),
            "initial_offset": initial_offset.astype(float).tolist(),
            "predicted_initial_rgb": predicted_initial.astype(float).tolist(),
            "predicted_rgb": predicted_after.astype(float).tolist(),
            "measured_rgb": measured.astype(float).tolist(),
            "reference_rgb": reference.astype(float).tolist(),
            "measured_lab_after": measured_lab.astype(float).tolist(),
            "reference_lab": reference_lab.astype(float).tolist(),
            "delta_e_before_values": delta_before.astype(float).tolist(),
            "delta_e_initial_values": delta_initial.astype(float).tolist(),
            "delta_e_after_values": delta_after.astype(float).tolist(),
            "delta_e_initial": initial_summary,
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
        },
    )


def solve_ccm_from_patches(
    patches: Sequence[ColorCheckerPatch],
    include_offset: bool = True,
    ridge: float = 0.015,
    weights: Optional[Sequence[float]] = None,
    white_constraint: bool = True,
    row_sum_regularization: float = 0.25,
    perceptual_weight: float = 0.08,
    structure_prior: bool = True,
    sign_regularization: float = 0.35,
) -> CCMCalibrationResult:
    all_patches = list(patches)
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
    valid_patches = [all_patches[index] for index in valid_indices]
    measured = np.stack(
        [patch.measured_rgb for patch in valid_patches]
    )
    reference = np.stack(
        [patch.reference_rgb for patch in valid_patches]
    )
    if weights is None:
        auto_weights = []
        for patch in valid_patches:
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
            auto_weights.append(weight)
        selected_weights = auto_weights
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
    )
    corrected = apply_ccm(measured, result.matrix, result.offset)
    delta, measured_lab, reference_lab = _delta_e(
        corrected, reference
    )
    before_values = result.diagnostics["delta_e_before_values"]
    initial_values = result.diagnostics["delta_e_initial_values"]
    corrected_values = result.diagnostics["predicted_rgb"]
    result.patches = []
    for index, patch in enumerate(valid_patches):
        copied = ColorCheckerPatch.from_dict(patch.to_dict())
        copied.measured_lab = measured_lab[index].astype(np.float32)
        copied.reference_lab = reference_lab[index].astype(np.float32)
        copied.delta_e = float(delta[index])
        copied.diagnostics.update({
            "delta_e_before": float(before_values[index]),
            "delta_e_initial": float(initial_values[index]),
            "delta_e_after": float(delta[index]),
            "corrected_rgb": corrected_values[index],
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
        "patch_diagnostics": {
            str(patch.patch_id): dict(patch.diagnostics)
            for patch in all_patches
        },
        "rejection_reasons": rejection_reasons,
        "safe_to_apply": not rejection_reasons,
    })
    return result
