from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

import numpy as np

from ..models import ParameterRecommendation


def save_recommendation(path: str, result: ParameterRecommendation) -> None:
    """Save JSON summary and, when present, a sibling compressed NPZ."""
    target = Path(path)
    artifact_path = None
    if result.artifacts:
        artifact_path = target.with_name(f"{target.stem}_artifacts.npz")
        np.savez_compressed(
            str(artifact_path),
            **{name: np.asarray(value) for name, value in result.artifacts.items()},
        )
    payload = result.to_dict(include_artifacts=False)
    if artifact_path is not None:
        payload["artifact_file"] = artifact_path.name
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_recommendation(path: str) -> ParameterRecommendation:
    source = Path(path)
    data = json.loads(source.read_text(encoding="utf-8"))
    result = ParameterRecommendation.from_dict(data)
    artifact_file = data.get("artifact_file")
    if artifact_file:
        artifact_path = source.parent / artifact_file
        if artifact_path.exists():
            with np.load(str(artifact_path), allow_pickle=False) as values:
                result.artifacts = {
                    name: np.asarray(values[name]) for name in values.files
                }
    return result


def save_artifacts(path: str, artifacts: Dict[str, np.ndarray]) -> None:
    np.savez_compressed(
        path, **{name: np.asarray(value) for name, value in artifacts.items()}
    )

