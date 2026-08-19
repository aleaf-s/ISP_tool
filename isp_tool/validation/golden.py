from __future__ import annotations

import hashlib
from typing import Any, Dict, Iterable, List, Mapping

import numpy as np

from .. import __version__
from ..pipeline import ISPPipeline
from ..raw_io import synthetic_bayer


BASELINE_SCHEMA_VERSION = 1
DEFAULT_PATTERNS = ("RGGB", "GRBG", "GBRG", "BGGR")
BASELINE_BACKEND = "OpenCV / NumPy"


def _round(value: float) -> float:
    return round(float(value), 8)


def _array_signature(image: np.ndarray, normalized: bool) -> Dict[str, Any]:
    source = np.asarray(image, dtype=np.float32)
    if not np.all(np.isfinite(source)):
        raise ValueError("Golden output contains NaN or Infinity")
    # Quantize to a sensor-relevant 12-bit grid before hashing.  This keeps
    # insignificant floating-point dispatch differences out of the baseline
    # while still detecting visible or algorithmic changes.
    scale = 4095.0 if normalized else 1.0
    quantized = np.rint(source * scale).astype("<i4", copy=False)
    percentiles = np.percentile(source, (1.0, 50.0, 99.0))
    return {
        "shape": list(source.shape),
        "minimum": _round(np.min(source)),
        "maximum": _round(np.max(source)),
        "mean": _round(np.mean(source)),
        "stddev": _round(np.std(source)),
        "p01": _round(percentiles[0]),
        "p50": _round(percentiles[1]),
        "p99": _round(percentiles[2]),
        "quantized_sha256": hashlib.sha256(
            np.ascontiguousarray(quantized).tobytes()
        ).hexdigest(),
    }


def build_pipeline_baseline(
    *,
    width: int = 160,
    height: int = 120,
    patterns: Iterable[str] = DEFAULT_PATTERNS,
) -> Dict[str, Any]:
    patterns = tuple(patterns)
    cases: Dict[str, Any] = {}
    for pattern in patterns:
        source = synthetic_bayer(width, height, pattern)
        pipeline = ISPPipeline(backend_preference=BASELINE_BACKEND)
        pipeline.module_by_id("demosaic").parameters[
            "algorithm"
        ] = "Bilinear"
        results = pipeline.process(
            source.image,
            source.domain,
            source.metadata,
            snapshot=pipeline.snapshot(),
        )
        stages = {}
        for result in results:
            state = result.data_state
            normalized = bool(state.normalized) if state else True
            stages[result.module_id] = {
                "domain": result.domain,
                "encoding": state.encoding if state else "unknown",
                "normalized": normalized,
                **_array_signature(result.image, normalized),
            }
        cases[pattern] = {
            "metadata": source.metadata.to_dict(),
            "stages": stages,
        }
    return {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "tool_version": __version__,
        "backend": BASELINE_BACKEND,
        "fixture": {
            "generator": "synthetic_bayer",
            "width": int(width),
            "height": int(height),
            "patterns": list(patterns),
        },
        "cases": cases,
    }


def verify_pipeline_baseline(
    expected: Mapping[str, Any],
    actual: Mapping[str, Any],
) -> List[str]:
    """Return human-readable mismatches; an empty list means a match."""
    errors: List[str] = []
    if expected.get("schema_version") != actual.get("schema_version"):
        errors.append("schema_version differs")
    if expected.get("backend") != actual.get("backend"):
        errors.append("backend differs")
    expected_cases = expected.get("cases", {})
    actual_cases = actual.get("cases", {})
    if set(expected_cases) != set(actual_cases):
        errors.append("Bayer Pattern case set differs")
        return errors
    for pattern in expected_cases:
        expected_stages = expected_cases[pattern].get("stages", {})
        actual_stages = actual_cases[pattern].get("stages", {})
        if set(expected_stages) != set(actual_stages):
            errors.append(f"{pattern}: stage set differs")
            continue
        for stage_id, expected_stage in expected_stages.items():
            actual_stage = actual_stages[stage_id]
            for key in (
                "domain",
                "encoding",
                "normalized",
                "shape",
                "quantized_sha256",
            ):
                if expected_stage.get(key) != actual_stage.get(key):
                    errors.append(f"{pattern}/{stage_id}: {key} differs")
    return errors
