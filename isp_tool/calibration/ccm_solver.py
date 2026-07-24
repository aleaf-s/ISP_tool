from __future__ import annotations

from typing import Optional, Sequence

import numpy as np

from ..models import CCMCalibrationResult, ColorCheckerPatch, ISPError
from .delta_e import delta_e_values, summarize_delta_e


def apply_ccm(
    rgb: np.ndarray,
    matrix: np.ndarray,
    offset: Optional[np.ndarray] = None,
) -> np.ndarray:
    values = np.asarray(rgb, dtype=np.float64)
    transform = np.asarray(matrix, dtype=np.float64).reshape(3, 3)
    bias = np.zeros(3, np.float64) if offset is None else np.asarray(offset, dtype=np.float64)
    return np.einsum("...c,dc->...d", values, transform) + bias


def solve_ccm(
    measured_rgb: np.ndarray,
    reference_rgb: np.ndarray,
    include_offset: bool = True,
    ridge: float = 0.0,
    weights: Optional[Sequence[float]] = None,
    white_constraint: bool = False,
) -> CCMCalibrationResult:
    measured = np.asarray(measured_rgb, dtype=np.float64)
    reference = np.asarray(reference_rgb, dtype=np.float64)
    if measured.shape != reference.shape or measured.ndim != 2 or measured.shape[1] != 3:
        raise ISPError("CCM 求解输入必须是形状相同的 N×3 数组")
    if measured.shape[0] < (4 if include_offset else 3):
        raise ISPError("CCM 求解色块数量不足")
    if not np.all(np.isfinite(measured)) or not np.all(np.isfinite(reference)):
        raise ISPError("CCM 求解输入包含 NaN 或 Infinity")
    design = np.column_stack([measured, np.ones(len(measured))]) if include_offset else measured
    target = reference.copy()
    sample_weights = np.ones(len(measured), np.float64)
    if weights is not None:
        sample_weights = np.asarray(weights, dtype=np.float64)
        if sample_weights.shape != (len(measured),) or np.any(sample_weights <= 0):
            raise ISPError("CCM 权重必须是 N 个正数")
    if white_constraint:
        white_design = np.array([[1, 1, 1, 1] if include_offset else [1, 1, 1]], np.float64)
        design = np.vstack([design, white_design])
        target = np.vstack([target, [1, 1, 1]])
        sample_weights = np.concatenate([sample_weights, [10.0]])
    sqrt_weights = np.sqrt(sample_weights)[:, None]
    weighted_design = design * sqrt_weights
    weighted_target = target * sqrt_weights
    condition = float(np.linalg.cond(weighted_design))
    regularizer = np.eye(design.shape[1], dtype=np.float64) * max(float(ridge), 0.0)
    if include_offset:
        regularizer[-1, -1] = 0.0
    lhs = weighted_design.T @ weighted_design + regularizer
    rhs = weighted_design.T @ weighted_target
    try:
        coefficients = np.linalg.solve(lhs, rhs)
    except np.linalg.LinAlgError:
        coefficients = np.linalg.lstsq(weighted_design, weighted_target, rcond=None)[0]
    matrix = coefficients[:3, :].T
    offset = coefficients[3, :] if include_offset else np.zeros(3, np.float64)
    predicted_before = measured
    predicted_after = apply_ccm(measured, matrix, offset)
    delta_before, _, _ = delta_e_values(predicted_before, reference, "CIE 2000")
    delta_after, measured_lab, reference_lab = delta_e_values(
        predicted_after, reference, "CIE 2000"
    )
    delta76_before, _, _ = delta_e_values(
        predicted_before, reference, "CIE 1976"
    )
    delta76_after, _, _ = delta_e_values(
        predicted_after, reference, "CIE 1976"
    )
    return CCMCalibrationResult(
        matrix.astype(np.float32),
        offset.astype(np.float32),
        "Ridge" if ridge > 0 else ("3×3 + Offset" if include_offset else "3×3 Least Squares"),
        condition,
        summarize_delta_e(delta_before),
        summarize_delta_e(delta_after),
        [],
        {
            "ridge": float(ridge),
            "white_constraint": bool(white_constraint),
            "sample_count": int(len(measured)),
            "predicted_rgb": predicted_after.astype(float).tolist(),
            "measured_lab_after": measured_lab.astype(float).tolist(),
            "reference_lab": reference_lab.astype(float).tolist(),
            "delta_e_after_values": delta_after.astype(float).tolist(),
            "delta_e76_before": summarize_delta_e(delta76_before),
            "delta_e76_after": summarize_delta_e(delta76_after),
        },
    )


def solve_ccm_from_patches(
    patches: Sequence[ColorCheckerPatch],
    include_offset: bool = True,
    ridge: float = 1e-4,
    weights: Optional[Sequence[float]] = None,
    white_constraint: bool = True,
) -> CCMCalibrationResult:
    if len(patches) < 6:
        raise ISPError("CCM 校准至少需要 6 个有效色块")
    measured = np.stack([patch.measured_rgb for patch in patches])
    reference = np.stack([patch.reference_rgb for patch in patches])
    result = solve_ccm(
        measured, reference, include_offset, ridge, weights, white_constraint
    )
    corrected = apply_ccm(measured, result.matrix, result.offset)
    delta, measured_lab, reference_lab = delta_e_values(
        corrected, reference, "CIE 2000"
    )
    result.patches = []
    for index, patch in enumerate(patches):
        copied = ColorCheckerPatch.from_dict(patch.to_dict())
        copied.measured_lab = measured_lab[index].astype(np.float32)
        copied.reference_lab = reference_lab[index].astype(np.float32)
        copied.delta_e = float(delta[index])
        result.patches.append(copied)
    return result
