from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


ACTION_WAIT = "wait"
ACTION_STALE = "stale"
ACTION_CANCELLED = "cancelled"
ACTION_APPLY = "apply"


class PreviewPayloadError(ValueError):
    pass


@dataclass(frozen=True)
class PreparedPreviewPayload:
    kind: str
    results: List[Any]
    metrics: Dict[str, Any]
    frame: Any = None
    conversion: Any = None
    cache_key_to_store: Optional[tuple] = None
    original_payload: Any = None


class PreviewResultApplicationController:
    """Validate completed worker payloads without touching UI state."""

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
    def _validate_results(results: Any) -> List[Any]:
        if not isinstance(results, (list, tuple)) or not results:
            raise PreviewPayloadError(
                "Preview payload must contain a non-empty result list"
            )
        output = list(results)
        for index, result in enumerate(output):
            if not hasattr(result, "image") or not hasattr(result, "domain"):
                raise PreviewPayloadError(
                    f"Preview result {index} is missing image/domain"
                )
        return output

    def prepare_raw(
        self, payload: Any, metrics: Optional[Dict[str, Any]] = None
    ) -> PreparedPreviewPayload:
        return PreparedPreviewPayload(
            kind="raw",
            results=self._validate_results(payload),
            metrics=dict(metrics or {}),
            original_payload=payload,
        )

    def prepare_yuv(
        self,
        payload: Any,
        *,
        cached: bool,
        cache_key: Optional[tuple],
    ) -> PreparedPreviewPayload:
        if not isinstance(payload, dict):
            raise PreviewPayloadError("YUV preview payload must be a mapping")
        missing = {
            key for key in ("frame", "conversion", "results", "metrics")
            if key not in payload
        }
        if missing:
            raise PreviewPayloadError(
                "YUV preview payload is missing: "
                + ", ".join(sorted(missing))
            )
        frame = payload["frame"]
        conversion = payload["conversion"]
        if not hasattr(frame, "metadata") or not hasattr(frame, "frame_index"):
            raise PreviewPayloadError("YUV frame metadata is invalid")
        if not hasattr(conversion, "rgb"):
            raise PreviewPayloadError("YUV conversion has no RGB preview")
        metrics = payload["metrics"]
        if not isinstance(metrics, dict):
            raise PreviewPayloadError("YUV metrics must be a mapping")
        return PreparedPreviewPayload(
            kind="yuv",
            results=self._validate_results(payload["results"]),
            metrics=dict(metrics),
            frame=frame,
            conversion=conversion,
            cache_key_to_store=(
                None if cached or cache_key is None else tuple(cache_key)
            ),
            original_payload=payload,
        )
