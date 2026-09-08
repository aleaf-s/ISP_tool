from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Protocol, Sequence

from .preview_result_application import (
    ACTION_APPLY,
    ACTION_CANCELLED,
    ACTION_STALE,
    ACTION_WAIT,
)


class Scheduler(Protocol):
    def after(self, delay_ms: int, callback: Callable[[], None]): ...

    def after_cancel(self, callback_id) -> None: ...


class ImportPayloadError(ValueError):
    pass


@dataclass(frozen=True)
class ImportFailure:
    path: str
    message: str

    def __str__(self) -> str:
        name = Path(self.path).name or self.path
        return f"{name}: {self.message}"


@dataclass(frozen=True)
class PreparedImportPayload:
    requested_paths: tuple[str, ...]
    items: tuple[Any, ...]
    failures: tuple[ImportFailure, ...]
    elapsed_ms: float
    original_payload: Mapping[str, Any]

    @property
    def succeeded(self) -> int:
        return len(self.items)

    @property
    def failed(self) -> int:
        return len(self.failures)

    @property
    def failure_messages(self) -> tuple[str, ...]:
        return tuple(str(failure) for failure in self.failures)


class ImportResultApplicationController:
    """Validate one completed file-import batch before workspace mutation."""

    @staticmethod
    def decide(
        *, is_current: bool, done: bool, cancelled: bool = False
    ) -> str:
        if not is_current:
            return ACTION_STALE
        if not done:
            return ACTION_WAIT
        if cancelled:
            return ACTION_CANCELLED
        return ACTION_APPLY

    @staticmethod
    def _failure(value: Any) -> ImportFailure:
        if isinstance(value, ImportFailure):
            return value
        if isinstance(value, Mapping):
            path = str(value.get("path", ""))
            message = str(value.get("message", ""))
            if not path or not message:
                raise ImportPayloadError(
                    "Import failure requires path and message"
                )
            return ImportFailure(path, message)
        raise ImportPayloadError(
            "Import failures must use ImportFailure or mapping values"
        )

    def prepare(
        self,
        payload: Any,
        expected_paths: Sequence[str],
    ) -> PreparedImportPayload:
        if not isinstance(payload, Mapping):
            raise ImportPayloadError("Import payload must be a mapping")
        missing = {
            key
            for key in ("requested_paths", "items", "failures", "elapsed_ms")
            if key not in payload
        }
        if missing:
            raise ImportPayloadError(
                "Import payload is missing: " + ", ".join(sorted(missing))
            )
        requested = tuple(str(path) for path in payload["requested_paths"])
        expected = tuple(str(path) for path in expected_paths)
        if not expected or requested != expected:
            raise ImportPayloadError(
                "Import payload paths do not match the active request"
            )
        items_value = payload["items"]
        failures_value = payload["failures"]
        if not isinstance(items_value, (list, tuple)):
            raise ImportPayloadError("Import items must be a sequence")
        if not isinstance(failures_value, (list, tuple)):
            raise ImportPayloadError("Import failures must be a sequence")
        items = tuple(items_value)
        successful_paths = []
        for index, item in enumerate(items):
            if not all(
                hasattr(item, attribute)
                for attribute in (
                    "loaded",
                    "pipeline_snapshot",
                    "calibration_session",
                )
            ):
                raise ImportPayloadError(
                    f"Import item {index} is not an ImageWorkItem"
                )
            source_path = getattr(item.loaded, "source_path", None)
            if source_path is None:
                raise ImportPayloadError(
                    f"Import item {index} has no source path"
                )
            successful_paths.append(str(source_path))
        failures = tuple(self._failure(value) for value in failures_value)
        if len(items) + len(failures) != len(expected):
            raise ImportPayloadError(
                "Import outcome count does not match requested path count"
            )
        canonical = lambda path: str(Path(path).resolve()).casefold()
        outcome_paths = successful_paths + [
            failure.path for failure in failures
        ]
        if Counter(map(canonical, outcome_paths)) != Counter(
            map(canonical, expected)
        ):
            raise ImportPayloadError(
                "Import outcomes do not belong to the requested paths"
            )
        elapsed_ms = float(payload["elapsed_ms"])
        if not math.isfinite(elapsed_ms) or elapsed_ms < 0.0:
            raise ImportPayloadError(
                "Import elapsed_ms must be finite and non-negative"
            )
        return PreparedImportPayload(
            requested_paths=requested,
            items=items,
            failures=failures,
            elapsed_ms=elapsed_ms,
            original_payload=dict(payload),
        )


class ImportRequestCoordinator:
    """Own a latest-wins import Future and all of its poll callbacks."""

    def __init__(
        self,
        scheduler: Scheduler,
        *,
        poll_interval_ms: int = 40,
        on_request_superseded: Optional[Callable[[], None]] = None,
        on_result_stale: Optional[Callable[[], None]] = None,
    ) -> None:
        self.scheduler = scheduler
        self.poll_interval_ms = max(1, int(poll_interval_ms))
        self.on_request_superseded = on_request_superseded
        self.on_result_stale = on_result_stale
        self.generation = 0
        self.current_future = None
        self.poll_after_ids: set = set()
        self.closed = False

    @staticmethod
    def _future_running(future) -> bool:
        return future is not None and not future.done()

    def begin(self) -> int:
        if self.closed:
            raise RuntimeError("Import request coordinator is closed")
        self.generation += 1
        if self._future_running(self.current_future):
            self.current_future.cancel()
            if self.on_request_superseded is not None:
                self.on_request_superseded()
        self.current_future = None
        return self.generation

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
        if self._future_running(self.current_future):
            self.current_future.cancel()
            if count_superseded and self.on_request_superseded is not None:
                self.on_request_superseded()
        self.current_future = None
        for callback_id in tuple(self.poll_after_ids):
            try:
                self.scheduler.after_cancel(callback_id)
            except Exception:
                pass
        self.poll_after_ids.clear()

    def close(self) -> None:
        if self.closed:
            return
        self.cancel(count_superseded=False)
        self.closed = True
