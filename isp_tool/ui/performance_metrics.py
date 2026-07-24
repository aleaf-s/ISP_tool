from __future__ import annotations

import math
import threading
from collections import defaultdict, deque
from typing import Deque, Dict

import numpy as np


class PerformanceMetrics:
    """Rolling performance samples and lightweight counters."""

    def __init__(self, window: int = 20) -> None:
        self.window = max(2, int(window))
        self._samples: Dict[str, Deque[float]] = defaultdict(
            lambda: deque(maxlen=self.window)
        )
        self._values: Dict[str, object] = {}
        self._counters: Dict[str, int] = defaultdict(int)
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

    def summary(self, name: str) -> dict:
        with self._lock:
            values = list(self._samples.get(str(name), ()))
        if not values:
            return {
                "latest": 0.0,
                "average": 0.0,
                "p50": 0.0,
                "p95": 0.0,
                "count": 0,
            }
        array = np.asarray(values, dtype=np.float64)
        return {
            "latest": float(array[-1]),
            "average": float(np.mean(array)),
            "p50": float(np.percentile(array, 50)),
            "p95": float(np.percentile(array, 95)),
            "count": int(array.size),
        }

    def snapshot(self) -> dict:
        with self._lock:
            names = list(self._samples)
            values = dict(self._values)
            counters = dict(self._counters)
        return {
            "timings": {name: self.summary(name) for name in names},
            "values": values,
            "counters": counters,
        }

    def status_text(self) -> str:
        pipeline = self.summary("pipeline")["latest"]
        view = self.summary("view")["latest"]
        analysis = self.summary("analysis")["latest"]
        with self._lock:
            analysis_state = str(
                self._values.get("analysis_state", "deferred")
            )
            cache = str(self._values.get("pipeline_cache", "0/0"))
        analysis_text = (
            f"{analysis:.0f} ms" if analysis_state == "ready"
            else analysis_state
        )
        return (
            f"Pipeline {pipeline:.0f} ms · View {view:.0f} ms · "
            f"Analysis {analysis_text} · Cache {cache}"
        )

    def details_text(self) -> str:
        snapshot = self.snapshot()
        lines = ["PERFORMANCE DETAILS", ""]
        for name in sorted(snapshot["timings"]):
            values = snapshot["timings"][name]
            lines.append(
                f"{name:<16} latest {values['latest']:8.2f} ms  "
                f"avg {values['average']:8.2f} ms  "
                f"p50 {values['p50']:8.2f} ms  "
                f"p95 {values['p95']:8.2f} ms"
            )
        if snapshot["values"]:
            lines.extend(["", "STATE"])
            lines.extend(
                f"{name:<20} {value}"
                for name, value in sorted(snapshot["values"].items())
            )
        if snapshot["counters"]:
            lines.extend(["", "COUNTERS"])
            lines.extend(
                f"{name:<20} {value}"
                for name, value in sorted(snapshot["counters"].items())
            )
        return "\n".join(lines)
