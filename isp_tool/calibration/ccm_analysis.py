"""Post-correction chart measurements shared by the editor and analysis view."""
from __future__ import annotations

import copy
import numpy as np

from .ccm_solver import apply_ccm
from .delta_e import delta_e_values, delta_lch_components, summarize_delta_e, summarize_component


def lab_errors(output, reference):
    output = np.asarray(output, dtype=np.float64)
    reference = np.asarray(reference, dtype=np.float64)
    difference = output - reference
    components = delta_lch_components(output, reference)
    return {
        "deab": np.linalg.norm(difference, axis=-1),
        "dcab": np.linalg.norm(difference[..., 1:3], axis=-1),
        "dl": difference[..., 0],
        "da": difference[..., 1],
        "db": difference[..., 2],
        "dc": components["delta_c"],
        "dh": np.where(components["hue_defined"], components["delta_h_degrees"], np.nan),
    }


def evaluate_matrix(measurements, matrix, input_gain=1.0, offset=None):
    """Evaluate the exact edited matrix; never run an optimiser here."""
    matrix = np.asarray(matrix, dtype=np.float64).reshape(3, 3)
    offset = np.zeros(3) if offset is None else np.asarray(offset, dtype=np.float64).reshape(3)
    if not np.all(np.isfinite(matrix)) or not np.all(np.isfinite(offset)):
        raise ValueError("CCM must contain finite numbers")
    if np.max(np.abs(matrix)) > 4 or np.max(np.abs(offset)) > 1 or not 0.25 <= input_gain <= 4:
        raise ValueError("CCM / Exposure outside the supported range")
    condition = float(np.linalg.cond(matrix))
    if not np.isfinite(condition) or condition > 50:
        raise ValueError("CCM is singular or unstable (condition > 50)")
    result = copy.deepcopy(measurements)
    patches = result.get("patches", [])
    valid_deltas, output_labs, target_labs = [], [], []
    for patch in patches:
        source = np.asarray(patch["measured_rgb"], dtype=np.float64)
        target = np.asarray(patch["reference_rgb"], dtype=np.float64)
        if source.shape != (3,) or target.shape != (3,) or not np.all(np.isfinite([source, target])):
            patch.setdefault("diagnostics", {}).update(valid=False, reasons=["Non-finite RGB sample"])
            continue
        output = apply_ccm(source * input_gain, matrix, offset)
        delta, lab, target_lab = delta_e_values(np.clip(output, 0, 1.25), np.clip(target, 0, 1.25))
        components = delta_lch_components(lab, target_lab)
        d = patch.setdefault("diagnostics", {})
        d.update(corrected_rgb=output.tolist(), corrected_lab=lab.tolist(),
                 reference_lab=target_lab.tolist(), delta_e_after=float(delta),
                 corrected_lch=components["measured_lch"].tolist())
        for name in ("delta_l", "delta_c", "delta_h"):
            d[name + "_after"] = float(components[name])
        patch["delta_e"] = float(delta)
        if d.get("valid", True):
            valid_deltas.append(float(delta))
            output_labs.append(lab)
            target_labs.append(target_lab)
    if not valid_deltas:
        raise ValueError("No valid ColorChecker samples")
    components = delta_lch_components(np.asarray(output_labs), np.asarray(target_labs))
    result.update(
        matrix=matrix.tolist(), offset=offset.tolist(),
        pre_ccm_exposure_gain=float(input_gain), condition_number=condition,
        row_sums=matrix.sum(axis=1).tolist(),
        delta_e_after=summarize_delta_e(np.asarray(valid_deltas)),
        delta_lch_after={key: summarize_component(components[key])
                         for key in ("delta_l", "delta_c", "delta_h")},
        safe_to_apply=True, rejection_reasons=[], method="Manual CCM evaluation",
        valid_patch_count=len(valid_deltas),
    )
    # Persist the new evaluation, not an old optimiser's nested diagnostics.
    result["diagnostics"] = {
        key: copy.deepcopy(result[key]) for key in (
            "pre_ccm_exposure_gain", "condition_number", "row_sums",
            "delta_e_after", "delta_lch_after", "safe_to_apply", "rejection_reasons",
            "valid_patch_count", "method",
        )
    }
    return result
