from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any, Hashable, Optional, Tuple


CacheKey = Tuple[Hashable, ...]


class RenderCache:
    """Small thread-safe LRU caches for display RGB and analysis results."""

    def __init__(
        self,
        stage_capacity: int = 8,
        analysis_capacity: int = 24,
    ) -> None:
        self.stage_capacity = max(1, int(stage_capacity))
        self.analysis_capacity = max(1, int(analysis_capacity))
        self._stage: "OrderedDict[CacheKey, Any]" = OrderedDict()
        self._analysis: "OrderedDict[CacheKey, Any]" = OrderedDict()
        self._lock = threading.RLock()
        self.stage_hits = 0
        self.stage_misses = 0
        self.analysis_hits = 0
        self.analysis_misses = 0

    @staticmethod
    def stage_key(
        result_revision: int,
        stage_index: int,
        domain: str,
        metadata_revision: int,
    ) -> CacheKey:
        return (
            "stage",
            int(result_revision),
            int(stage_index),
            str(domain),
            int(metadata_revision),
        )

    @staticmethod
    def analysis_key(
        result_revision: int,
        stage_index: int,
        analysis_type: str,
        roi_key: Hashable,
        *settings: Hashable,
    ) -> CacheKey:
        return (
            "analysis",
            int(result_revision),
            int(stage_index),
            str(analysis_type),
            roi_key,
            *settings,
        )

    def get_stage(self, key: CacheKey) -> Optional[Any]:
        with self._lock:
            if key not in self._stage:
                self.stage_misses += 1
                return None
            self.stage_hits += 1
            self._stage.move_to_end(key)
            return self._stage[key]

    def put_stage(self, key: CacheKey, value: Any) -> None:
        with self._lock:
            self._stage[key] = value
            self._stage.move_to_end(key)
            while len(self._stage) > self.stage_capacity:
                self._stage.popitem(last=False)

    def get_analysis(self, key: CacheKey) -> Optional[Any]:
        with self._lock:
            if key not in self._analysis:
                self.analysis_misses += 1
                return None
            self.analysis_hits += 1
            self._analysis.move_to_end(key)
            return self._analysis[key]

    def put_analysis(self, key: CacheKey, value: Any) -> None:
        with self._lock:
            self._analysis[key] = value
            self._analysis.move_to_end(key)
            while len(self._analysis) > self.analysis_capacity:
                self._analysis.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._stage.clear()
            self._analysis.clear()

    def clear_analysis(self) -> None:
        with self._lock:
            self._analysis.clear()

    def counters(self) -> dict:
        with self._lock:
            return {
                "stage_hits": self.stage_hits,
                "stage_misses": self.stage_misses,
                "analysis_hits": self.analysis_hits,
                "analysis_misses": self.analysis_misses,
                "stage_entries": len(self._stage),
                "analysis_entries": len(self._analysis),
            }

