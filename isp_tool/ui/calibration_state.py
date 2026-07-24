from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class CalibrationUIState(str, Enum):
    NOT_ANALYZED = "NOT_ANALYZED"
    RUNNING = "RUNNING"
    SUGGESTED = "SUGGESTED"
    PREVIEWING = "PREVIEWING"
    APPLIED = "APPLIED"
    STALE = "STALE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


ALLOWED_TRANSITIONS = {
    CalibrationUIState.NOT_ANALYZED: {CalibrationUIState.RUNNING},
    CalibrationUIState.RUNNING: {
        CalibrationUIState.SUGGESTED,
        CalibrationUIState.FAILED,
        CalibrationUIState.CANCELLED,
    },
    CalibrationUIState.SUGGESTED: {
        CalibrationUIState.PREVIEWING,
        CalibrationUIState.STALE,
    },
    CalibrationUIState.PREVIEWING: {
        CalibrationUIState.APPLIED,
        CalibrationUIState.SUGGESTED,
    },
    CalibrationUIState.APPLIED: {
        CalibrationUIState.STALE,
    },
    CalibrationUIState.STALE: {CalibrationUIState.RUNNING},
    CalibrationUIState.FAILED: {CalibrationUIState.RUNNING},
    CalibrationUIState.CANCELLED: {CalibrationUIState.RUNNING},
}


class InvalidCalibrationTransition(RuntimeError):
    pass


@dataclass
class CalibrationStateMachine:
    state: CalibrationUIState = CalibrationUIState.NOT_ANALYZED
    parameter_snapshot: Optional[Dict[str, Any]] = None
    error: str = ""

    def transition(self, target: CalibrationUIState) -> None:
        target = CalibrationUIState(target)
        if target == self.state:
            return
        if target not in ALLOWED_TRANSITIONS[self.state]:
            raise InvalidCalibrationTransition(
                f"非法标定状态转换：{self.state.value} → {target.value}"
            )
        self.state = target
        if target != CalibrationUIState.FAILED:
            self.error = ""

    def start(self, parameters: Dict[str, Any]) -> None:
        self.transition(CalibrationUIState.RUNNING)
        self.parameter_snapshot = copy.deepcopy(parameters)

    def fail(self, message: str) -> None:
        self.transition(CalibrationUIState.FAILED)
        self.error = str(message)

    def mark_stale_if_changed(self, parameters: Dict[str, Any]) -> bool:
        if self.state not in {
            CalibrationUIState.SUGGESTED,
            CalibrationUIState.APPLIED,
        }:
            return False
        if self.parameter_snapshot is not None and parameters != self.parameter_snapshot:
            self.transition(CalibrationUIState.STALE)
            return True
        return False

    @property
    def can_analyze(self) -> bool:
        return self.state in {
            CalibrationUIState.NOT_ANALYZED,
            CalibrationUIState.STALE,
            CalibrationUIState.FAILED,
            CalibrationUIState.CANCELLED,
        }

    @property
    def can_preview(self) -> bool:
        return self.state == CalibrationUIState.SUGGESTED

    @property
    def can_apply(self) -> bool:
        return self.state == CalibrationUIState.PREVIEWING

    @property
    def can_revert(self) -> bool:
        return self.state == CalibrationUIState.PREVIEWING
