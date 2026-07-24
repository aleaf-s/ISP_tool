from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from .models import CalibrationSession, ImageROI, LoadedImage


@dataclass
class ImageWorkItem:
    """One image and its independent ISP editing state."""

    loaded: LoadedImage
    pipeline_snapshot: List[Dict]
    calibration_session: CalibrationSession
    rois: List[ImageROI] = field(default_factory=list)
    active_roi_index: int = -1
    roi_grid_bounds: Optional[ImageROI] = None
    roi_grid_rows: int = 4
    roi_grid_cols: int = 6
    roi_grid_inset: float = 0.12
    manual_parameter_snapshots: Dict[str, Dict] = field(
        default_factory=dict
    )
    manual_dirty_modules: List[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        if self.loaded.source_path:
            return Path(self.loaded.source_path).name
        return self.loaded.description or "Untitled image"

    def active_roi(self):
        if 0 <= self.active_roi_index < len(self.rois):
            return self.rois[self.active_roi_index]
        return None

    def set_active_roi(self, roi) -> None:
        if roi is None:
            self.active_roi_index = -1
            return
        if 0 <= self.active_roi_index < len(self.rois):
            self.rois[self.active_roi_index] = roi
        else:
            self.rois.append(roi)
            self.active_roi_index = len(self.rois) - 1


def snapshot_for_image(
    base_snapshot: Sequence[Dict], loaded: LoadedImage
) -> List[Dict]:
    """Create a per-image snapshot and initialize BLC from its metadata."""

    snapshot = copy.deepcopy(list(base_snapshot))
    for item in snapshot:
        if item.get("id") != "black_level_correction":
            continue
        parameters = item.setdefault("parameters", {})
        for key, value in zip(
            ("r", "gr", "gb", "b"), loaded.metadata.black_level
        ):
            parameters[key] = float(value)
        break
    return snapshot


def transfer_module_settings(
    source_snapshot: Sequence[Dict],
    target_snapshot: Sequence[Dict],
    module_ids: Iterable[str],
) -> List[Dict]:
    """Copy complete module configuration, including LSC/DPC state."""

    requested = set(module_ids)
    source = {
        str(item.get("id")): item
        for item in source_snapshot
        if item.get("id") in requested
    }
    output = copy.deepcopy(list(target_snapshot))
    for index, item in enumerate(output):
        module_id = str(item.get("id"))
        if module_id in source:
            output[index] = copy.deepcopy(source[module_id])
    return output


def compatible_for_transfer(
    source: LoadedImage, target: LoadedImage, module_ids: Iterable[str]
) -> List[str]:
    """Return non-fatal compatibility warnings for calibration transfer."""

    module_ids = set(module_ids)
    warnings: List[str] = []
    if source.domain != target.domain:
        warnings.append(
            f"输入域不同：{source.domain} → {target.domain}"
        )
    sensor_modules = {
        "black_level_correction",
        "defective_pixel_correction",
        "lens_shading_correction",
        "white_balance",
    }
    if module_ids & sensor_modules:
        if (
            source.metadata.bayer_pattern
            != target.metadata.bayer_pattern
        ):
            warnings.append(
                "Bayer Pattern 不同，传感器域校准可能不兼容"
            )
        if (
            source.metadata.width,
            source.metadata.height,
        ) != (
            target.metadata.width,
            target.metadata.height,
        ):
            warnings.append(
                "图像尺寸不同，LSC Mesh 会重采样，DPC 坐标可能不兼容"
            )
    return warnings
