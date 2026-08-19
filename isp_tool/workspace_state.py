from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .models import CalibrationSession, ImageROI, LoadedImage
from .workspace import ImageWorkItem


@dataclass(frozen=True)
class WorkItemEditableState:
    loaded: LoadedImage
    pipeline_snapshot: List[Dict]
    calibration_session: CalibrationSession
    rois: List[ImageROI]
    active_roi_index: int
    roi_grid_bounds: Optional[ImageROI]
    roi_grid_rows: int
    roi_grid_cols: int
    roi_grid_inset: float
    manual_parameter_snapshots: Dict[str, Dict]
    manual_dirty_modules: Tuple[str, ...]
    preview_shape: Optional[tuple]
    input_revision: int

    @property
    def active_roi(self) -> Optional[ImageROI]:
        if 0 <= self.active_roi_index < len(self.rois):
            return self.rois[self.active_roi_index]
        return None


class WorkspaceItemStateController:
    """Copy-safe editable state transfer between the UI and work items."""

    @staticmethod
    def capture(
        *,
        loaded: LoadedImage,
        pipeline_snapshot: Sequence[Dict],
        calibration_session: CalibrationSession,
        rois: Sequence[ImageROI],
        active_roi_index: int,
        roi_grid_bounds: Optional[ImageROI],
        roi_grid_rows: int,
        roi_grid_cols: int,
        roi_grid_inset: float,
        manual_parameter_snapshots: Dict[str, Dict],
        manual_dirty_modules: Sequence[str],
        preview_shape: Optional[tuple],
        input_revision: int,
    ) -> WorkItemEditableState:
        roi_list = list(rois)
        active = int(active_roi_index)
        if not (0 <= active < len(roi_list)):
            active = -1
        return WorkItemEditableState(
            loaded=loaded,
            pipeline_snapshot=copy.deepcopy(list(pipeline_snapshot)),
            calibration_session=copy.deepcopy(calibration_session),
            rois=roi_list,
            active_roi_index=active,
            roi_grid_bounds=roi_grid_bounds,
            roi_grid_rows=max(1, int(roi_grid_rows)),
            roi_grid_cols=max(1, int(roi_grid_cols)),
            roi_grid_inset=float(roi_grid_inset),
            manual_parameter_snapshots=copy.deepcopy(
                manual_parameter_snapshots
            ),
            manual_dirty_modules=tuple(sorted(set(manual_dirty_modules))),
            preview_shape=(
                tuple(preview_shape) if preview_shape is not None else None
            ),
            input_revision=max(0, int(input_revision)),
        )

    @staticmethod
    def store(
        item: ImageWorkItem, state: WorkItemEditableState
    ) -> None:
        runtime_preview = item.runtime_preview
        item.loaded = state.loaded
        item.pipeline_snapshot = copy.deepcopy(state.pipeline_snapshot)
        item.calibration_session = copy.deepcopy(
            state.calibration_session
        )
        item.rois = list(state.rois)
        item.active_roi_index = state.active_roi_index
        item.roi_grid_bounds = state.roi_grid_bounds
        item.roi_grid_rows = state.roi_grid_rows
        item.roi_grid_cols = state.roi_grid_cols
        item.roi_grid_inset = state.roi_grid_inset
        item.manual_parameter_snapshots = copy.deepcopy(
            state.manual_parameter_snapshots
        )
        item.manual_dirty_modules = list(state.manual_dirty_modules)
        item.preview_shape = state.preview_shape
        item.input_revision = state.input_revision
        item.runtime_preview = runtime_preview

    @classmethod
    def activation(cls, item: ImageWorkItem) -> WorkItemEditableState:
        return cls.capture(
            loaded=item.loaded,
            pipeline_snapshot=item.pipeline_snapshot,
            calibration_session=item.calibration_session,
            rois=item.rois,
            active_roi_index=item.active_roi_index,
            roi_grid_bounds=item.roi_grid_bounds,
            roi_grid_rows=item.roi_grid_rows,
            roi_grid_cols=item.roi_grid_cols,
            roi_grid_inset=item.roi_grid_inset,
            manual_parameter_snapshots=item.manual_parameter_snapshots,
            manual_dirty_modules=item.manual_dirty_modules,
            preview_shape=item.preview_shape,
            input_revision=item.input_revision,
        )
