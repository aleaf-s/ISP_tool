from __future__ import annotations

import math
import threading
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Dict, Mapping

import numpy as np


@dataclass(frozen=True)
class TimingSummary:
    latest: float = 0.0
    average: float = 0.0
    p50: float = 0.0
    p95: float = 0.0
    maximum: float = 0.0
    count: int = 0

    def as_dict(self) -> dict:
        return {
            "latest": self.latest,
            "average": self.average,
            "p50": self.p50,
            "p95": self.p95,
            "maximum": self.maximum,
            "count": self.count,
        }


@dataclass(frozen=True)
class CacheSummary:
    hits: int = 0
    misses: int = 0

    @property
    def requests(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        if self.requests <= 0:
            return 0.0
        return self.hits / self.requests

    def as_dict(self) -> dict:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "requests": self.requests,
            "hit_rate": self.hit_rate,
        }


@dataclass(frozen=True)
class PerformanceSnapshot:
    timings: Mapping[str, TimingSummary]
    caches: Mapping[str, CacheSummary]
    memory_bytes: Mapping[str, int]
    values: Mapping[str, object]
    counters: Mapping[str, int]


def format_bytes(value: int) -> str:
    size = max(0, int(value))
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KiB"
    if size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MiB"
    return f"{size / (1024 * 1024 * 1024):.2f} GiB"


def estimate_ndarray_bytes(*values: object) -> int:
    """Estimate unique NumPy backing-store bytes reachable from values."""

    roots: dict[int, int] = {}
    visited: set[int] = set()

    def visit(value: object) -> None:
        identity = id(value)
        if identity in visited:
            return
        visited.add(identity)
        if isinstance(value, np.ndarray):
            root = value
            while isinstance(getattr(root, "base", None), np.ndarray):
                root = root.base
            roots[id(root)] = max(
                roots.get(id(root), 0), int(getattr(root, "nbytes", 0))
            )
            return
        if isinstance(value, Mapping):
            for item in value.values():
                visit(item)
            return
        if isinstance(value, (list, tuple, set, deque)):
            for item in value:
                visit(item)
            return
        image = getattr(value, "image", None)
        artifacts = getattr(value, "artifacts", None)
        if image is not None:
            visit(image)
        if artifacts is not None:
            visit(artifacts)
        for attribute in (
            "preview_image",
            "pipeline_cache",
            "results",
            "frame",
            "planes",
            "conversion",
        ):
            nested = getattr(value, attribute, None)
            if nested is not None:
                visit(nested)

    for value in values:
        visit(value)
    return sum(roots.values())


class PerformanceMetrics:
    """Thread-safe rolling timings, cache ratios and runtime diagnostics."""

    def __init__(self, window: int = 20) -> None:
        self.window = max(2, int(window))
        self._samples: Dict[str, Deque[float]] = defaultdict(
            lambda: deque(maxlen=self.window)
        )
        self._values: Dict[str, object] = {}
        self._counters: Dict[str, int] = defaultdict(int)
        self._caches: Dict[str, CacheSummary] = {}
        self._memory_bytes: Dict[str, int] = {}
        self._lock = threading.RLock()

    def record(self, name: str, milliseconds: float) -> None:
        value = float(milliseconds)
        if not math.isfinite(value):
            return
        with self._lock:
            self._samples[str(name)].append(max(0.0, value))

    def set_value(self, name: str, value: object) -> None:
        with self._lock:
            self._values[str(name)] = value

    def increment(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._counters[str(name)] += int(amount)

    def set_cache(self, name: str, hits: int, misses: int) -> None:
        with self._lock:
            self._caches[str(name)] = CacheSummary(
                max(0, int(hits)), max(0, int(misses))
            )

    def add_cache(self, name: str, hits: int = 0, misses: int = 0) -> None:
        with self._lock:
            current = self._caches.get(str(name), CacheSummary())
            self._caches[str(name)] = CacheSummary(
                current.hits + max(0, int(hits)),
                current.misses + max(0, int(misses)),
            )

    def set_memory(self, name: str, byte_count: int) -> None:
        with self._lock:
            self._memory_bytes[str(name)] = max(0, int(byte_count))

    def timing_summary(self, name: str) -> TimingSummary:
        with self._lock:
            values = list(self._samples.get(str(name), ()))
        if not values:
            return TimingSummary()
        array = np.asarray(values, dtype=np.float64)
        return TimingSummary(
            latest=float(array[-1]),
            average=float(np.mean(array)),
            p50=float(np.percentile(array, 50)),
            p95=float(np.percentile(array, 95)),
            maximum=float(np.max(array)),
            count=int(array.size),
        )

    def summary(self, name: str) -> dict:
        """Compatibility dict used by existing callers and tests."""
        return self.timing_summary(name).as_dict()

    def cache_summary(self, name: str) -> CacheSummary:
        with self._lock:
            return self._caches.get(str(name), CacheSummary())

    def structured_snapshot(self) -> PerformanceSnapshot:
        with self._lock:
            names = tuple(self._samples)
            caches = dict(self._caches)
            memory = dict(self._memory_bytes)
            values = dict(self._values)
            counters = dict(self._counters)
        return PerformanceSnapshot(
            timings={name: self.timing_summary(name) for name in names},
            caches=caches,
            memory_bytes=memory,
            values=values,
            counters=counters,
        )

    def snapshot(self) -> dict:
        """Return the original serializable shape plus V0.4.34 fields."""
        value = self.structured_snapshot()
        return {
            "timings": {
                name: summary.as_dict()
                for name, summary in value.timings.items()
            },
            "caches": {
                name: summary.as_dict()
                for name, summary in value.caches.items()
            },
            "memory_bytes": dict(value.memory_bytes),
            "values": dict(value.values),
            "counters": dict(value.counters),
        }

    def status_text(self) -> str:
        snapshot = self.structured_snapshot()
        pipeline = snapshot.timings.get("pipeline", TimingSummary()).latest
        module_rows = [
            (name.removeprefix("module:"), timing.latest)
            for name, timing in snapshot.timings.items()
            if name.startswith("module:") and timing.count
        ]
        slowest = max(
            module_rows, key=lambda item: item[1], default=("--", 0.0)
        )
        cache = snapshot.caches.get("pipeline", CacheSummary())
        cache_text = (
            f"{cache.hit_rate * 100:.0f}%" if cache.requests else "--"
        )
        memory = snapshot.memory_bytes.get("estimated_runtime", 0)
        return (
            f"Preview {pipeline:.0f} ms · Slowest {slowest[0]} "
            f"{slowest[1]:.0f} ms · Cache {cache_text} · "
            f"Memory ~{format_bytes(memory)}"
        )

    def details_text(self) -> str:
        snapshot = self.structured_snapshot()
        lines = ["PERFORMANCE MONITOR", "", "END-TO-END"]
        for name, values in sorted(
            (
                item for item in snapshot.timings.items()
                if not item[0].startswith("module:")
            ),
            key=lambda item: item[1].average,
            reverse=True,
        ):
            lines.append(
                f"{name:<32} latest {values.latest:8.2f} ms  "
                f"avg {values.average:8.2f} ms  "
                f"p50 {values.p50:8.2f} ms  p95 {values.p95:8.2f} ms  "
                f"max {values.maximum:8.2f} ms"
            )
        module_rows = sorted(
            (
                (name.removeprefix("module:"), values)
                for name, values in snapshot.timings.items()
                if name.startswith("module:")
            ),
            key=lambda item: item[1].average,
            reverse=True,
        )
        if module_rows:
            lines.extend(["", "ISP MODULES · slowest rolling average first"])
            for name, values in module_rows:
                lines.append(
                    f"{name:<32} latest {values.latest:8.2f} ms  "
                    f"avg {values.average:8.2f} ms  "
                    f"p95 {values.p95:8.2f} ms  max {values.maximum:8.2f} ms"
                )
        if snapshot.caches:
            lines.extend(["", "SOFTWARE CACHES"])
            for name, value in sorted(snapshot.caches.items()):
                lines.append(
                    f"{name:<24} {value.hits}/{value.requests} hits  "
                    f"{value.hit_rate * 100:6.1f}%"
                )
        if snapshot.memory_bytes:
            lines.extend(["", "NUMPY MEMORY ESTIMATE"])
            lines.extend(
                f"{name:<24} ~{format_bytes(value)}"
                for name, value in sorted(snapshot.memory_bytes.items())
            )
        if snapshot.values:
            lines.extend(["", "STATE"])
            lines.extend(
                f"{name:<24} {value}"
                for name, value in sorted(snapshot.values.items())
            )
        if snapshot.counters:
            lines.extend(["", "TASK COUNTERS"])
            lines.extend(
                f"{name:<24} {value}"
                for name, value in sorted(snapshot.counters.items())
            )
        return "\n".join(lines)
