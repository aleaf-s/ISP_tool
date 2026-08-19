from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


Point = Tuple[int, int]

GESTURE_NONE = "none"
GESTURE_GRAY_PICK = "gray_pick"
GESTURE_COMPARE = "compare"
GESTURE_LINE_PROFILE = "line_profile"
GESTURE_ROI = "roi"

ARMABLE_GESTURES = {GESTURE_GRAY_PICK, GESTURE_LINE_PROFILE}
ACTIVE_GESTURES = {
    GESTURE_GRAY_PICK,
    GESTURE_COMPARE,
    GESTURE_LINE_PROFILE,
    GESTURE_ROI,
}


@dataclass(frozen=True)
class GestureSnapshot:
    armed: str
    active: str
    start: Optional[Point]
    current: Optional[Point]


class CanvasGestureCoordinator:
    """Pure state machine for mutually exclusive main-canvas gestures.

    Priority is intentionally fixed to match the product contract:
    Gray Picker > Compare divider > armed measurement > ROI > Compare body.
    The coordinator owns arbitration and transient pointer state, while the
    application remains responsible for geometry changes and rendering.
    """

    def __init__(self) -> None:
        self.armed = GESTURE_NONE
        self.active = GESTURE_NONE
        self.start: Optional[Point] = None
        self.current: Optional[Point] = None

    @property
    def snapshot(self) -> GestureSnapshot:
        return GestureSnapshot(
            self.armed, self.active, self.start, self.current
        )

    def arm(self, gesture: str) -> None:
        if gesture not in ARMABLE_GESTURES:
            raise ValueError(f"Gesture cannot be armed: {gesture}")
        self.active = GESTURE_NONE
        self.start = None
        self.current = None
        self.armed = gesture

    def disarm(self, gesture: Optional[str] = None) -> None:
        if gesture is None or self.armed == gesture:
            self.armed = GESTURE_NONE

    def begin(
        self,
        point: Optional[Point],
        *,
        compare_divider_hit: bool,
        roi_enabled: bool,
        compare_enabled: bool,
    ) -> str:
        if self.active != GESTURE_NONE:
            return self.active
        if self.armed == GESTURE_GRAY_PICK:
            gesture = GESTURE_GRAY_PICK
        elif compare_divider_hit:
            gesture = GESTURE_COMPARE
        elif self.armed == GESTURE_LINE_PROFILE:
            gesture = GESTURE_LINE_PROFILE
        elif roi_enabled:
            gesture = GESTURE_ROI
        elif compare_enabled:
            gesture = GESTURE_COMPARE
        else:
            gesture = GESTURE_NONE
        if gesture != GESTURE_NONE:
            self.active = gesture
            self.start = point
            self.current = point
        return gesture

    def update(self, point: Optional[Point]) -> str:
        if self.active != GESTURE_NONE and point is not None:
            self.current = point
        return self.active

    def finish(self) -> str:
        gesture = self.active
        self.active = GESTURE_NONE
        self.start = None
        self.current = None
        if gesture in ARMABLE_GESTURES:
            self.disarm(gesture)
        return gesture

    def cancel_active(self, gesture: Optional[str] = None) -> None:
        if gesture is None or self.active == gesture:
            self.active = GESTURE_NONE
            self.start = None
            self.current = None

    def cancel_all(self) -> None:
        self.cancel_active()
        self.armed = GESTURE_NONE

    def force_active(self, gesture: str, enabled: bool) -> None:
        """Compatibility bridge for legacy application properties."""
        if gesture not in ACTIVE_GESTURES:
            raise ValueError(f"Unknown gesture: {gesture}")
        if enabled:
            self.active = gesture
        elif self.active == gesture:
            self.cancel_active(gesture)

    def set_armed(self, gesture: str, enabled: bool) -> None:
        if enabled:
            self.arm(gesture)
        else:
            self.disarm(gesture)

    def cursor(
        self, *, compare_divider_hit: bool, roi_enabled: bool
    ) -> str:
        if self.active == GESTURE_COMPARE or compare_divider_hit:
            return "sb_h_double_arrow"
        if (
            self.active in {GESTURE_LINE_PROFILE, GESTURE_ROI}
            or self.armed in ARMABLE_GESTURES
            or roi_enabled
        ):
            return "crosshair"
        return "arrow"
