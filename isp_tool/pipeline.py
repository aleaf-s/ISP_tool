from __future__ import annotations

import copy
import math
import time
from concurrent.futures import CancelledError
from typing import Any, Callable, Dict, Iterable, List, Optional

import numpy as np

from .backends import (
    DEFAULT_BACKEND_PREFERENCE,
    BackendSelection,
    ProcessingBackend,
    select_backend,
)
from .models import (
    ISPError,
    ImageROI,
    RawMetadata,
    StageDataState,
    StageResult,
)
from .modules import (
    BlackLevelCorrection,
    ColorCorrectionMatrix,
    Demosaic,
    LensShadingCorrection,
    WhiteBalance,
)


class ISPPipeline:
    def __init__(
        self,
        backend: Optional[ProcessingBackend] = None,
        backend_preference: str = DEFAULT_BACKEND_PREFERENCE,
    ) -> None:
        selection = select_backend(backend_preference)
        if backend is not None:
            selection = BackendSelection(
                selection.preference,
                backend,
                selection.native,
            )
        self.backend_selection = selection
        self.modules = [
            BlackLevelCorrection(),
            LensShadingCorrection(),
            WhiteBalance(),
            Demosaic(),
            ColorCorrectionMatrix(),
        ]
        self._assign_backend()

    @property
    def backend(self) -> ProcessingBackend:
        return self.backend_selection.backend

    @property
    def backend_preference(self) -> str:
        return self.backend_selection.preference

    @property
    def backend_cache_key(self) -> str:
        return self.backend_selection.cache_key

    @property
    def native_backend_available(self) -> bool:
        return self.backend_selection.native.available

    def _assign_backend(self) -> None:
        for module in self.modules:
            module.processing_backend = self.backend

    def set_backend_preference(
        self, preference: str
    ) -> BackendSelection:
        self.backend_selection = select_backend(preference)
        self._assign_backend()
        return self.backend_selection

    def set_backend(
        self,
        backend: ProcessingBackend,
        preference: Optional[str] = None,
    ) -> BackendSelection:
        current = self.backend_selection
        self.backend_selection = BackendSelection(
            preference or current.preference,
            backend,
            current.native,
        )
        self._assign_backend()
        return self.backend_selection

    def module_by_id(self, module_id: str):
        return next(module for module in self.modules if module.module_id == module_id)

    @staticmethod
    def _normalize_module_output(
        output, module_name: str, validated_input: Optional[np.ndarray] = None
    ):
        if not isinstance(output, tuple) or len(output) not in {3, 4}:
            raise ISPError(f"{module_name} 返回了无效的模块结果")
        if len(output) == 3:
            image, domain, diagnostics = output
            artifacts = {}
        else:
            image, domain, diagnostics, artifacts = output
        image = np.asarray(image, dtype=np.float32)
        if image is not validated_input and not np.all(np.isfinite(image)):
            count = int(np.size(image) - np.count_nonzero(np.isfinite(image)))
            raise ISPError(f"{module_name} 输出包含 {count} 个 NaN 或 Infinity")
        return image, domain, dict(diagnostics or {}), dict(artifacts or {})

    @staticmethod
    def _crop_array(array: np.ndarray, core: ImageROI, working_shape) -> np.ndarray:
        value = np.asarray(array)
        if value.ndim >= 2 and value.shape[:2] == tuple(working_shape[:2]):
            ys, xs = core.slices()
            return value[ys, xs]
        return value

    def _public_result(self, result: StageResult, core: ImageROI) -> StageResult:
        return StageResult(
            result.module_id,
            result.name,
            self._crop_array(result.image, core, result.image.shape),
            result.domain,
            result.elapsed_ms,
            dict(result.diagnostics),
            {
                name: self._crop_array(artifact, core, result.image.shape)
                for name, artifact in result.artifacts.items()
            },
            result.data_state,
        )

    @staticmethod
    def _module_output_state(
        module,
        current_state: StageDataState,
        output_domain: str,
        parameters: Dict[str, Any],
    ) -> StageDataState:
        if module.module_id == "black_level_correction":
            return StageDataState(
                "bayer",
                "Bayer Linear Normalized",
                float(parameters.get("output_min", 0.0)),
                float(parameters.get("output_max", 1.0)),
                True,
                True,
                current_state.bit_depth,
                current_state.black_level,
                current_state.white_level,
            )
        return current_state.with_domain(output_domain)

    @staticmethod
    def _state_diagnostics(state: StageDataState) -> Dict[str, Any]:
        return {
            "数值域": state.encoding,
            "标称范围": f"{state.value_min:g}…{state.value_max:g}",
            "BLC Applied": bool(state.black_level_applied),
            "Normalized": bool(state.normalized),
            "Bit Depth": int(state.bit_depth),
            "White Level": float(state.white_level),
        }

    def _run_module(
        self,
        module,
        config: Dict[str, Any],
        current: np.ndarray,
        current_domain: str,
        current_state: StageDataState,
        metadata: RawMetadata,
        backend: ProcessingBackend,
    ) -> StageResult:
        enabled = bool(config["enabled"])
        if not enabled or current_domain not in module.input_domains:
            reason = "Disabled" if not enabled else f"跳过：需要 {tuple(module.input_domains)}"
            return StageResult(
                module.module_id,
                module.name,
                current,
                current_domain,
                0.0,
                {
                    "状态": reason,
                    **self._state_diagnostics(current_state),
                },
                {},
                current_state,
            )
        # A full deepcopy duplicates DPC maps and other calibration state for
        # every refresh. The detached snapshot below is the worker's source of
        # truth, so a shallow module shell is sufficient and much cheaper.
        worker_module = copy.copy(module)
        worker_module.enabled = enabled
        worker_module.processing_backend = backend
        worker_module.parameters = dict(config["parameters"])
        worker_module.load_state(config.get("state", {}))
        metadata._stage_data_state = current_state
        try:
            started = time.perf_counter()
            raw_output = worker_module.process(current, current_domain, metadata)
            elapsed = (time.perf_counter() - started) * 1000.0
            image, domain, diagnostics, artifacts = self._normalize_module_output(
                raw_output, module.name, current
            )
        except ISPError:
            raise
        except MemoryError as exc:
            raise ISPError(f"{module.name} 内存不足") from exc
        except Exception as exc:
            raise ISPError(f"{module.name} 执行失败：{exc}") from exc
        if image.shape[:2] != current.shape[:2]:
            raise ISPError(
                f"{module.name} 意外改变了图像尺寸："
                f"{current.shape[:2]} → {image.shape[:2]}"
            )
        output_state = self._module_output_state(
            worker_module, current_state, domain, worker_module.parameters
        )
        diagnostics = {
            **diagnostics,
            **self._state_diagnostics(output_state),
        }
        return StageResult(
            module.module_id,
            module.name,
            image,
            domain,
            elapsed,
            diagnostics,
            artifacts,
            output_state,
        )

    def process(
        self,
        image: np.ndarray,
        domain: str,
        metadata: RawMetadata,
        snapshot: Optional[List[Dict]] = None,
        roi: Optional[ImageROI] = None,
        roi_halo: int = 24,
    ) -> List[StageResult]:
        return self.process_cached(
            image,
            domain,
            metadata,
            snapshot or self.snapshot(),
            {},
            input_revision=0,
            roi=roi,
            roi_halo=roi_halo,
        )

    def process_cached(
        self,
        image: np.ndarray,
        domain: str,
        metadata: RawMetadata,
        snapshot: List[Dict],
        cache: Dict[str, Any],
        input_revision: int,
        roi: Optional[ImageROI] = None,
        roi_halo: int = 24,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> List[StageResult]:
        """Process a full preview or a halo-expanded ROI with prefix caching."""
        process_started = time.perf_counter()
        # Capture one backend for the entire worker request. A UI backend
        # switch can then safely supersede this request without mixing kernels.
        processing_backend = self.backend
        backend_cache_key = processing_backend.cache_key
        source = np.asarray(image, dtype=np.float32)
        if source.ndim not in {2, 3}:
            raise ISPError(f"流水线输入维度无效：{source.shape}")
        if not np.all(np.isfinite(source)):
            raise ISPError("流水线输入包含 NaN 或 Infinity")

        if roi is not None:
            roi.validate(source.shape)
            requested = roi.align_for_bayer(source.shape) if domain == "bayer" else roi
            outer = requested.expanded(
                roi_halo, source.shape, bayer_aligned=(domain == "bayer")
            )
        else:
            requested = ImageROI(0, 0, source.shape[1], source.shape[0])
            outer = requested
        core = requested.relative_to(outer)
        roi_key = (
            requested.x, requested.y, requested.width, requested.height,
            int(roi_halo), outer.x, outer.y, outer.width, outer.height,
        )

        previous_snapshot = cache.get("snapshot")
        working_results = cache.get("working_results")
        public_results = cache.get("results")
        cache_valid = (
            cache.get("input_revision") == input_revision
            and cache.get("backend_cache_key") == backend_cache_key
            and cache.get("roi_key") == roi_key
            and isinstance(working_results, list)
            and len(working_results) == len(self.modules) + 1
            and isinstance(public_results, list)
            and len(public_results) == len(self.modules) + 1
            and isinstance(previous_snapshot, list)
            and len(previous_snapshot) == len(snapshot)
        )

        dirty_index = 0
        if cache_valid:
            dirty_index = len(self.modules)
            for index, (old, new) in enumerate(zip(previous_snapshot, snapshot)):
                if old != new:
                    dirty_index = index
                    break
            if dirty_index == len(self.modules):
                wall_elapsed = (time.perf_counter() - process_started) * 1000.0
                cache["last_metrics"] = {
                    "cache_hits": len(self.modules),
                    "recomputed": 0,
                    "elapsed_ms": 0.0,
                    "wall_elapsed_ms": wall_elapsed,
                    "overhead_ms": wall_elapsed,
                    "module_timings": {},
                    "dirty_index": len(self.modules),
                    "backend_cache_key": backend_cache_key,
                    "roi": requested.to_dict() if roi is not None else None,
                    "halo": roi_halo if roi is not None else 0,
                }
                return public_results

        process_metadata = copy.copy(metadata)
        # Runtime-only coordinates let spatial modules such as LSC evaluate an
        # ROI in the same coordinate system as the full preview.
        process_metadata._processing_frame_width = source.shape[1]
        process_metadata._processing_frame_height = source.shape[0]
        process_metadata._processing_origin_x = outer.x
        process_metadata._processing_origin_y = outer.y

        if cache_valid and dirty_index > 0:
            new_working = list(working_results[:dirty_index + 1])
            new_public = list(public_results[:dirty_index + 1])
            previous = new_working[-1]
            current = previous.image
            current_domain = previous.domain
            current_state = previous.data_state or StageDataState.for_input(
                current_domain, process_metadata
            )
        else:
            dirty_index = 0
            ys, xs = outer.slices()
            current = np.ascontiguousarray(source[ys, xs])
            current_domain = domain
            current_state = StageDataState.for_input(domain, process_metadata)
            input_working = StageResult(
                "input",
                "RAW Input" if domain == "bayer" else "RGB Input",
                current,
                current_domain,
                0.0,
                self._state_diagnostics(current_state),
                {},
                current_state,
            )
            new_working = [input_working]
            new_public = [self._public_result(input_working, core)]

        for module, config in zip(self.modules[dirty_index:], snapshot[dirty_index:]):
            if cancel_check is not None and cancel_check():
                raise CancelledError("Superseded ISP preview")
            result = self._run_module(
                module,
                config,
                current,
                current_domain,
                current_state,
                process_metadata,
                processing_backend,
            )
            current, current_domain = result.image, result.domain
            current_state = result.data_state or current_state.with_domain(
                current_domain
            )
            new_working.append(result)
            new_public.append(self._public_result(result, core))

        cache["input_revision"] = input_revision
        cache["backend_cache_key"] = backend_cache_key
        cache["roi_key"] = roi_key
        cache["snapshot"] = copy.deepcopy(snapshot)
        cache["working_results"] = new_working
        cache["results"] = new_public
        recomputed_results = new_working[dirty_index + 1:]
        module_elapsed = float(
            sum(result.elapsed_ms for result in recomputed_results)
        )
        wall_elapsed = (time.perf_counter() - process_started) * 1000.0
        cache["last_metrics"] = {
            "cache_hits": dirty_index,
            "recomputed": len(self.modules) - dirty_index,
            "elapsed_ms": module_elapsed,
            "wall_elapsed_ms": wall_elapsed,
            "overhead_ms": max(0.0, wall_elapsed - module_elapsed),
            "module_timings": {
                result.module_id: float(result.elapsed_ms)
                for result in recomputed_results
            },
            "dirty_index": dirty_index,
            "backend_cache_key": backend_cache_key,
            "roi": requested.to_dict() if roi is not None else None,
            "halo": roi_halo if roi is not None else 0,
        }
        return new_public

    def snapshot(self) -> List[Dict]:
        return [module.config() for module in self.modules]

    def load_snapshot(self, configs: Iterable[Dict]) -> List[str]:
        """Load known settings, clamp unsafe values, and return warnings."""
        warnings: List[str] = []
        by_id: Dict[str, Dict] = {}
        known_ids = {module.module_id for module in self.modules}
        for item in configs:
            identifier = item.get("id") or item.get("module_id") or item.get("name")
            if identifier in known_ids:
                by_id[identifier] = item
            else:
                warnings.append(f"忽略未知模块：{identifier}")

        for module in self.modules:
            item = by_id.get(module.module_id)
            if not item:
                continue
            module.enabled = bool(item.get("enabled", module.enabled))
            try:
                module.load_state(item.get("state", {}))
            except Exception as exc:
                warnings.append(f"{module.name} 状态加载失败：{exc}")
            values = item.get("parameters", {})
            for key, value in values.items():
                spec = module.specs.get(key)
                if spec is None:
                    warnings.append(f"{module.name}：忽略未知参数 {key}")
                    continue
                try:
                    if spec.kind == "float":
                        converted = float(value)
                        if not math.isfinite(converted):
                            raise ValueError("不是有限数值")
                    elif spec.kind == "int":
                        converted = int(value)
                    elif spec.kind == "bool":
                        converted = bool(value)
                    elif spec.kind == "choice":
                        converted = str(value)
                        if converted not in spec.choices:
                            raise ValueError(f"可选值为 {tuple(spec.choices)}")
                    else:
                        converted = value
                    if spec.kind in {"float", "int"}:
                        original = converted
                        if spec.minimum is not None:
                            converted = max(spec.minimum, converted)
                        if spec.maximum is not None:
                            converted = min(spec.maximum, converted)
                        if spec.kind == "int":
                            converted = int(converted)
                        if converted != original:
                            warnings.append(
                                f"{module.name}.{key} 已限制到 {converted}"
                            )
                    module.parameters[key] = converted
                except (TypeError, ValueError) as exc:
                    warnings.append(
                        f"{module.name}.{key} 无效，保留原值：{exc}"
                    )
        return warnings
