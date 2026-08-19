from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Optional, Protocol


class Scheduler(Protocol):
    def after(self, delay_ms: int, callback: Callable[[], None]): ...

    def after_cancel(self, callback_id) -> None: ...


@dataclass(frozen=True)
class PreviewRequestToken:
    generation: int
    cancel_event: threading.Event


class PreviewRequestCoordinator:
    """Coordinate one latest-wins preview request lifecycle.

    The coordinator owns debounce callbacks, request generations, cooperative
    cancellation and Future polling.  It deliberately knows nothing about RAW,
    YUV, Tk widgets or how a completed payload is applied.
    """

    def __init__(
        self,
        scheduler: Scheduler,
        *,
        poll_interval_ms: int = 15,
        on_request_dropped: Optional[Callable[[], None]] = None,
        on_result_dropped: Optional[Callable[[], None]] = None,
    ) -> None:
        self.scheduler = scheduler
        self.poll_interval_ms = max(1, int(poll_interval_ms))
        self.on_request_dropped = on_request_dropped
        self.on_result_dropped = on_result_dropped
        self.generation = 0
        self.pending_after = None
        self.current_future = None
        self.cancel_event: Optional[threading.Event] = None
        self.poll_after_ids: set = set()
        self.closed = False

    @staticmethod
    def _future_running(future) -> bool:
        return future is not None and not future.done()

    def _notify_request_dropped(self) -> None:
        if self.on_request_dropped is not None:
            self.on_request_dropped()

    def _cancel_callback(self, callback_id) -> bool:
        if callback_id is None:
            return False
        try:
            self.scheduler.after_cancel(callback_id)
        except Exception:
            return False
        return True

    def schedule(
        self,
        start: Callable[[], None],
        *,
        immediate: bool = False,
        delay_ms: int = 90,
        immediate_delay_ms: int = 1,
    ) -> None:
        if self.closed:
            return
        if self.pending_after is not None:
            self._cancel_callback(self.pending_after)
            self.pending_after = None
        delay = immediate_delay_ms if immediate else delay_ms

        def run() -> None:
            self.pending_after = None
            if not self.closed:
                start()

        self.pending_after = self.scheduler.after(
            max(0, int(delay)), run
        )

    def cancel(self, *, count_drops: bool = True) -> None:
        """Invalidate the active generation and cancel pending/running work."""
        self.generation += 1
        if self.pending_after is not None:
            cancelled = self._cancel_callback(self.pending_after)
            self.pending_after = None
            if cancelled and count_drops:
                self._notify_request_dropped()
        if self.cancel_event is not None:
            self.cancel_event.set()
        future = self.current_future
        if self._future_running(future) and future.cancel():
            if count_drops:
                self._notify_request_dropped()

    def begin(self) -> PreviewRequestToken:
        """Start a new generation and supersede the prior worker request."""
        if self.closed:
            raise RuntimeError("Preview request coordinator is closed")
        if self.pending_after is not None:
            self._cancel_callback(self.pending_after)
            self.pending_after = None
        self.generation += 1
        if self.cancel_event is not None:
            self.cancel_event.set()
        future = self.current_future
        if self._future_running(future):
            future.cancel()
        event = threading.Event()
        self.cancel_event = event
        return PreviewRequestToken(self.generation, event)

    def bind_future(self, future) -> None:
        self.current_future = future

    def is_current(self, generation: int) -> bool:
        return not self.closed and int(generation) == self.generation

    def reject_stale_result(self) -> None:
        if self.on_result_dropped is not None:
            self.on_result_dropped()

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

    def close(self) -> None:
        if self.closed:
            return
        self.generation += 1
        self.closed = True
        if self.cancel_event is not None:
            self.cancel_event.set()
        if self.pending_after is not None:
            self._cancel_callback(self.pending_after)
            self.pending_after = None
        future = self.current_future
        if self._future_running(future):
            future.cancel()
        for callback_id in tuple(self.poll_after_ids):
            self._cancel_callback(callback_id)
        self.poll_after_ids.clear()
