from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Protocol

from .preview_result_application import (
    ACTION_APPLY,
    ACTION_CANCELLED,
    ACTION_STALE,
    ACTION_WAIT,
)


class Scheduler(Protocol):
    def after(self, delay_ms: int, callback: Callable[[], None]): ...

    def after_cancel(self, callback_id) -> None: ...


class AnalysisPayloadError(ValueError):
    pass


@dataclass(frozen=True)
class PreparedAnalysisPayload:
    value: Any
    elapsed_ms: float
    original_payload: Mapping[str, Any]


class AnalysisResultApplicationController:
    """Decide and validate analysis results before cache or UI mutation."""

    @staticmethod
    def decide(
        *,
        is_current: bool,
        context_valid: bool,
        done: bool,
        cancelled: bool = False,
    ) -> str:
        if not is_current or not context_valid:
            return ACTION_STALE
        if not done:
            return ACTION_WAIT
        if cancelled:
            return ACTION_CANCELLED
        return ACTION_APPLY

    @staticmethod
    def prepare(payload: Any) -> PreparedAnalysisPayload:
        if not isinstance(payload, Mapping):
            raise AnalysisPayloadError(
                "Analysis payload must be a mapping"
            )
        missing = {key for key in ("value", "elapsed_ms") if key not in payload}
        if missing:
            raise AnalysisPayloadError(
                "Analysis payload is missing: "
                + ", ".join(sorted(missing))
            )
        elapsed_ms = float(payload["elapsed_ms"])
        if not math.isfinite(elapsed_ms) or elapsed_ms < 0.0:
            raise AnalysisPayloadError(
                "Analysis elapsed_ms must be finite and non-negative"
            )
        if payload["value"] is None:
            raise AnalysisPayloadError("Analysis value cannot be None")
        return PreparedAnalysisPayload(
            value=payload["value"],
            elapsed_ms=elapsed_ms,
            original_payload=dict(payload),
        )


class AnalysisRequestCoordinator:
    """Latest-wins debounce, Future ownership and polling for analyses."""

    def __init__(
        self,
        scheduler: Scheduler,
        *,
        poll_interval_ms: int = 15,
        on_request_superseded: Optional[Callable[[], None]] = None,
        on_result_stale: Optional[Callable[[], None]] = None,
    ) -> None:
        self.scheduler = scheduler
        self.poll_interval_ms = max(1, int(poll_interval_ms))
        self.on_request_superseded = on_request_superseded
        self.on_result_stale = on_result_stale
        self.generation = 0
        self.pending_after = None
        self.current_future = None
        self.poll_after_ids: set = set()
        self.closed = False

    @staticmethod
    def _future_running(future) -> bool:
        return future is not None and not future.done()

    def _cancel_after(self, callback_id) -> bool:
        if callback_id is None:
            return False
        try:
            self.scheduler.after_cancel(callback_id)
        except Exception:
            return False
        return True

    def _superseded(self) -> None:
        if self.on_request_superseded is not None:
            self.on_request_superseded()

    def schedule(
        self,
        start: Callable[[int], None],
        *,
        delay_ms: int = 220,
    ) -> int:
        if self.closed:
            return self.generation
        self.generation += 1
        generation = self.generation
        if self.pending_after is not None:
            if self._cancel_after(self.pending_after):
                self._superseded()
            self.pending_after = None
        if self._future_running(self.current_future):
            self.current_future.cancel()
            self._superseded()
        self.current_future = None

        def run() -> None:
            self.pending_after = None
            if not self.closed and generation == self.generation:
                start(generation)

        self.pending_after = self.scheduler.after(
            max(0, int(delay_ms)), run
        )
        return generation

    def bind_future(self, future) -> None:
        self.current_future = future

    def is_current(self, generation: int) -> bool:
        return not self.closed and int(generation) == self.generation

    def reject_stale_result(self) -> None:
        if self.on_result_stale is not None:
            self.on_result_stale()

    def schedule_poll(self, callback: Callable[[], None]) -> None:
        if self.closed:
            return
        callback_id = None

        def poll() -> None:
            if callback_id is not None:
                self.poll_after_ids.discard(callback_id)
            if not self.closed:
                callback()

        callback_id = self.scheduler.after(
            self.poll_interval_ms, poll
        )
        self.poll_after_ids.add(callback_id)

    def cancel(self, *, count_superseded: bool = True) -> None:
        if self.closed:
            return
        self.generation += 1
        if self.pending_after is not None:
            cancelled = self._cancel_after(self.pending_after)
            self.pending_after = None
            if cancelled and count_superseded:
                self._superseded()
        if self._future_running(self.current_future):
            self.current_future.cancel()
            if count_superseded:
                self._superseded()
        self.current_future = None

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.generation += 1
        if self.pending_after is not None:
            self._cancel_after(self.pending_after)
            self.pending_after = None
        if self._future_running(self.current_future):
            self.current_future.cancel()
        self.current_future = None
        for callback_id in tuple(self.poll_after_ids):
            self._cancel_after(callback_id)
        self.poll_after_ids.clear()
