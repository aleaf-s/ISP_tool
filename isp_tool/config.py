from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

from . import __version__
from .models import CalibrationSession, ISPError, RawMetadata
from .pipeline import ISPPipeline


SCHEMA_VERSION = 4


def build_config(
    metadata: RawMetadata,
    pipeline: ISPPipeline,
    name: str = "",
    notes: str = "",
    ui_state: Optional[Dict[str, Any]] = None,
    calibration: Optional[CalibrationSession] = None,
) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": "ISP RAW Visual Simulator",
        "tool_version": __version__,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "name": name,
        "notes": notes,
        "raw": metadata.to_dict(),
        "pipeline": pipeline.snapshot(),
        "calibration": calibration.to_dict() if calibration else {},
        "ui_state": dict(ui_state or {}),
    }


def save_config(
    path: str,
    metadata: RawMetadata,
    pipeline: ISPPipeline,
    ui_state: Optional[Dict[str, Any]] = None,
    calibration: Optional[CalibrationSession] = None,
) -> None:
    target = Path(path)
    payload = build_config(
        metadata, pipeline, ui_state=ui_state, calibration=calibration
    )
    # Static DPC maps can be large.  Store the dense map in a sibling NPZ and
    # leave only a relative reference in JSON.
    for item in payload.get("pipeline", []):
        if item.get("id") != "defective_pixel_correction":
            continue
        state = item.get("state", {})
        shape = state.get("shape") if isinstance(state, dict) else None
        pixels = state.get("defect_pixels", []) if isinstance(state, dict) else []
        if shape and pixels:
            defect_array = np.zeros(tuple(map(int, shape)), np.uint8)
            for x, y, kind, *_rest in pixels:
                if 0 <= int(y) < defect_array.shape[0] and 0 <= int(x) < defect_array.shape[1]:
                    defect_array[int(y), int(x)] = np.uint8(
                        np.clip(int(kind), 1, 2)
                    )
            asset = target.with_name(f"{target.stem}_dpc_map.npz")
            np.savez_compressed(
                str(asset),
                defect_map=defect_array,
                bayer_pattern=np.array(metadata.bayer_pattern),
            )
            item["state"] = {"external_path": asset.name}
            payload.setdefault("calibration", {}).setdefault(
                "external_assets", {}
            )["dpc_map"] = asset.name
    target.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def migrate_config(data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(data, dict):
        raise ISPError("配置文件根节点必须是 JSON Object")
    migrated = dict(data)
    version = int(migrated.get("schema_version", 1))
    if version > SCHEMA_VERSION:
        raise ISPError(
            f"配置 schema_version={version} 高于当前支持版本 {SCHEMA_VERSION}"
        )
    if version <= 1:
        migrated["tool_version"] = migrated.get("tool_version", migrated.get("version", "0.1.0"))
        migrated.setdefault("ui_state", {})
        normalized_pipeline = []
        for item in migrated.get("pipeline", []):
            normalized = dict(item)
            if "id" not in normalized:
                candidate = normalized.get("module_id") or normalized.get("name")
                normalized["id"] = candidate
            normalized_pipeline.append(normalized)
        migrated["pipeline"] = normalized_pipeline
    if version <= 2:
        migrated["schema_version"] = 3
        migrated.setdefault("calibration", {})
    if version <= 3:
        migrated["schema_version"] = 4
        calibration = migrated.setdefault("calibration", {})
        if isinstance(calibration, dict):
            calibration.setdefault("auto_recommendations", {})
            calibration.setdefault("calibration_history", [])
            calibration.setdefault("noise_profile", None)
            calibration.setdefault("external_assets", {})
    migrated.setdefault("raw", {})
    migrated.setdefault("pipeline", [])
    migrated.setdefault("calibration", {})
    migrated.setdefault("ui_state", {})
    return migrated


def load_config(path: str) -> Dict[str, Any]:
    try:
        raw_text = Path(path).read_text(encoding="utf-8")
        data = json.loads(raw_text)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ISPError(f"配置文件损坏或无法读取：{exc}") from exc
    migrated = migrate_config(data)
    calibration = migrated.get("calibration", {})
    mesh_data = calibration.get("lsc_mesh") if isinstance(calibration, dict) else None
    if isinstance(mesh_data, dict) and mesh_data.get("external_path"):
        from .calibration.lsc_mesh import load_lsc_mesh
        mesh_path = Path(path).parent / mesh_data["external_path"]
        try:
            calibration["lsc_mesh"] = load_lsc_mesh(str(mesh_path)).to_dict()
        except Exception as exc:
            migrated.setdefault("_warnings", []).append(
                f"外部 LSC Mesh 无法加载：{mesh_path}：{exc}"
            )
            calibration["lsc_mesh"] = None
    for item in migrated.get("pipeline", []):
        if item.get("id") != "defective_pixel_correction":
            continue
        state = item.get("state", {})
        if not isinstance(state, dict) or not state.get("external_path"):
            continue
        defect_path = Path(path).parent / state["external_path"]
        try:
            with np.load(str(defect_path), allow_pickle=False) as values:
                defect_array = np.asarray(values["defect_map"], np.uint8)
            ys, xs = np.nonzero(defect_array)
            item["state"] = {
                "shape": list(defect_array.shape),
                "defect_pixels": [
                    [int(x), int(y), int(defect_array[y, x])]
                    for y, x in zip(ys, xs)
                ],
            }
        except Exception as exc:
            migrated.setdefault("_warnings", []).append(
                f"外部 DPC 坏点表无法加载：{defect_path}：{exc}"
            )
            item["state"] = {}
    external_assets = (
        calibration.get("external_assets", {})
        if isinstance(calibration, dict) else {}
    )
    resolved_assets = {}
    for name, relative in external_assets.items():
        asset_path = Path(relative)
        if not asset_path.is_absolute():
            asset_path = Path(path).parent / asset_path
        resolved_assets[name] = str(asset_path)
        if not asset_path.exists():
            migrated.setdefault("_warnings", []).append(
                f"外部标定文件不存在：{name}：{asset_path}"
            )
    if resolved_assets:
        migrated["_resolved_external_assets"] = resolved_assets
    return migrated
