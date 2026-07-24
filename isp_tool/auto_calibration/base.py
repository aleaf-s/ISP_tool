from __future__ import annotations

import copy
import math
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

import numpy as np

from ..models import (
    CalibrationSession,
    ImageROI,
    ISPError,
    ParameterRecommendation,
    RawMetadata,
)


class AnalysisCancelled(ISPError):
    """Raised cooperatively when an obsolete analysis should stop."""


class CancellationToken:
    """Small cooperative cancellation token for NumPy/OpenCV work."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        if self.cancelled:
            raise AnalysisCancelled("分析任务已取消")


class ModuleAnalyzer(ABC):
    module_id = ""
    target_module_id = ""
    name = ""

    @abstractmethod
    def analyze(
        self,
        image: np.ndarray,
        metadata: RawMetadata,
        current_parameters: Dict[str, Any],
        roi: Optional[ImageROI] = None,
        cancel_token: Optional[CancellationToken] = None,
        **options: Any,
    ) -> ParameterRecommendation:
        """Measure an image and return a recommendation without mutating ISP."""


@dataclass
class _PreviewSnapshot:
    target_module_id: str
    parameters: Dict[str, Any]
    state: Dict[str, Any]
    recommendation: ParameterRecommendation


class AutoCalibrationController:
    """Owns the transient Preview/Apply/Revert lifecycle.

    The controller is intentionally UI-agnostic.  A schedule callback can be
    supplied by Tk/Qt code to refresh the pipeline after parameter changes.
    """

    def __init__(
        self,
        pipeline,
        schedule_callback: Optional[Callable[[], None]] = None,
        session: Optional[CalibrationSession] = None,
    ) -> None:
        self.pipeline = pipeline
        self.schedule_callback = schedule_callback
        self.session = session
        self._preview: Optional[_PreviewSnapshot] = None
        self._generation = 0
        self._active_token: Optional[CancellationToken] = None

    @property
    def has_preview(self) -> bool:
        return self._preview is not None

    @property
    def preview_target(self) -> Optional[str]:
        return self._preview.target_module_id if self._preview else None

    def begin_analysis(self) -> tuple[int, CancellationToken]:
        self._generation += 1
        if self._active_token is not None:
            self._active_token.cancel()
        self._active_token = CancellationToken()
        return self._generation, self._active_token

    def is_current(self, generation: int) -> bool:
        return generation == self._generation

    def cancel_analysis(self) -> None:
        self._generation += 1
        if self._active_token is not None:
            self._active_token.cancel()
        self._active_token = None

    def analyze(
        self,
        analyzer: ModuleAnalyzer,
        image: np.ndarray,
        metadata: RawMetadata,
        roi: Optional[ImageROI] = None,
        generation: Optional[int] = None,
        cancel_token: Optional[CancellationToken] = None,
        **options: Any,
    ) -> ParameterRecommendation:
        """Run an analyzer against a copied parameter set.

        This method never changes a pipeline module.  It also clamps/rejects
        recommendations according to the target module's ParameterSpec.
        """
        target = analyzer.target_module_id or analyzer.module_id
        module = self.pipeline.module_by_id(target)
        current = copy.deepcopy(module.parameters)
        token = cancel_token
        if token is None:
            if generation is None:
                generation, token = self.begin_analysis()
            else:
                token = self._active_token or CancellationToken()
        token.check()
        started = time.perf_counter()
        recommendation = analyzer.analyze(
            np.asarray(image).copy(),
            copy.deepcopy(metadata),
            current,
            roi=copy.deepcopy(roi),
            cancel_token=token,
            **options,
        )
        token.check()
        recommendation.elapsed_ms = (
            recommendation.elapsed_ms
            or (time.perf_counter() - started) * 1000.0
        )
        recommendation.target_module_id = target
        recommendation.current_parameters = current
        recommendation.suggested_parameters = self._sanitize_parameters(
            module, recommendation.suggested_parameters
        )
        recommendation.confidence = float(
            np.clip(recommendation.confidence, 0.0, 1.0)
        )
        if generation is not None and not self.is_current(generation):
            raise AnalysisCancelled("分析结果已经过期")
        if self.session is not None:
            self.session.auto_recommendations[
                recommendation.module_id
            ] = recommendation
            if recommendation.module_id == "noise_profile":
                self.session.noise_profile = dict(recommendation.measurements)
        return recommendation

    @staticmethod
    def _sanitize_parameters(module, values: Dict[str, Any]) -> Dict[str, Any]:
        output: Dict[str, Any] = {}
        for key, value in values.items():
            spec = module.specs.get(key)
            if spec is None:
                continue
            try:
                if spec.kind == "float":
                    converted: Any = float(value)
                    if not math.isfinite(converted):
                        continue
                elif spec.kind == "int":
                    converted = int(round(float(value)))
                elif spec.kind == "bool":
                    converted = bool(value)
                elif spec.kind == "choice":
                    converted = str(value)
                    if converted not in spec.choices:
                        continue
                else:
                    converted = value
                if spec.kind in {"float", "int"}:
                    if spec.minimum is not None:
                        converted = max(spec.minimum, converted)
                    if spec.maximum is not None:
                        converted = min(spec.maximum, converted)
                    if spec.kind == "int":
                        converted = int(converted)
                output[key] = converted
            except (TypeError, ValueError):
                continue
        return output

    def preview(self, recommendation: ParameterRecommendation) -> None:
        target = recommendation.target
        if self._preview is not None:
            self.revert()
        module = self.pipeline.module_by_id(target)
        self._preview = _PreviewSnapshot(
            target,
            copy.deepcopy(module.parameters),
            copy.deepcopy(module.export_state()),
            recommendation,
        )
        module.parameters.update(copy.deepcopy(recommendation.suggested_parameters))
        if recommendation.state_updates:
            module.load_state(copy.deepcopy(recommendation.state_updates))
        recommendation.applied = False
        self._notify()

    def apply(self, recommendation: ParameterRecommendation) -> None:
        if (
            self._preview is None
            or self._preview.recommendation is not recommendation
        ):
            self.preview(recommendation)
        recommendation.applied = True
        self._preview = None
        if self.session is not None:
            self.session.auto_recommendations[
                recommendation.module_id
            ] = recommendation
            self.session.calibration_history.append(
                recommendation.to_dict(include_artifacts=False)
            )
        self._notify()

    def revert(self) -> None:
        if self._preview is None:
            return
        snapshot = self._preview
        module = self.pipeline.module_by_id(snapshot.target_module_id)
        module.parameters = copy.deepcopy(snapshot.parameters)
        module.load_state(copy.deepcopy(snapshot.state))
        snapshot.recommendation.applied = False
        self._preview = None
        self._notify()

    def close(self) -> None:
        self.cancel_analysis()
        self.revert()

    def _notify(self) -> None:
        if self.schedule_callback is not None:
            self.schedule_callback()

