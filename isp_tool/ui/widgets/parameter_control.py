from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk
from typing import Callable

from ...models import ParameterSpec


class ParameterControl(ttk.Frame):
    """DPI-friendly numeric slider with exact entry and throttled changes."""

    def __init__(
        self,
        parent,
        spec: ParameterSpec,
        value: float,
        command: Callable[[bool], None],
        throttle_ms: int = 25,
    ) -> None:
        super().__init__(parent)
        self.spec = spec
        self.command = command
        self.throttle_ms = max(16, int(throttle_ms))
        self.pending_after = None
        self._updating = False
        self.variable = tk.DoubleVar(value=float(value))
        self.entry_var = tk.StringVar(value=self._format(value))

        controls = ttk.Frame(self)
        controls.pack(fill="x")
        self.scale = ttk.Scale(
            controls,
            from_=float(spec.minimum),
            to=float(spec.maximum),
            variable=self.variable,
            command=self._scale_changed,
            style="Parameter.Horizontal.TScale",
            takefocus=True,
        )
        self.scale.pack(side="left", fill="x", expand=True, ipady=4)
        self.entry = ttk.Entry(
            controls,
            textvariable=self.entry_var,
            width=9,
            justify="right",
            style="Parameter.TEntry",
        )
        self.entry.pack(side="left", padx=(8, 4))
        self.reset_button = ttk.Button(
            controls,
            text="↺",
            width=3,
            command=self.reset,
            style="Compact.TButton",
        )
        self.reset_button.pack(side="left")
        ttk.Label(
            self,
            text=(
                f"{self._format(spec.minimum)} … "
                f"{self._format(spec.maximum)}  ·  "
                f"默认 {self._format(spec.default)}"
            ),
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        self.scale.bind("<ButtonPress-1>", self._track_press)
        self.scale.bind("<ButtonRelease-1>", self._drag_finished, add="+")
        self.scale.bind("<Double-Button-1>", self._double_reset, add="+")
        self.scale.bind("<KeyPress-Left>", lambda event: self._key_step(event, -1))
        self.scale.bind("<KeyPress-Right>", lambda event: self._key_step(event, 1))
        self.scale.bind("<KeyPress-Down>", lambda event: self._key_step(event, -1))
        self.scale.bind("<KeyPress-Up>", lambda event: self._key_step(event, 1))
        self.scale.bind("<MouseWheel>", self._wheel_step)
        self.scale.bind("<Button-4>", lambda event: self._wheel_step(event, 1))
        self.scale.bind("<Button-5>", lambda event: self._wheel_step(event, -1))
        self.entry.bind("<Return>", self._entry_commit)
        self.entry.bind("<FocusOut>", self._entry_commit)

    def _format(self, value) -> str:
        if self.spec.kind == "int":
            return str(int(round(float(value))))
        step = abs(float(self.spec.step or 0.001))
        decimals = max(0, min(6, int(math.ceil(-math.log10(step)))))
        return f"{float(value):.{decimals}f}"

    def _snap(self, value: float) -> float:
        minimum = float(self.spec.minimum)
        maximum = float(self.spec.maximum)
        value = max(minimum, min(maximum, float(value)))
        step = float(self.spec.step or (1.0 if self.spec.kind == "int" else 0.0))
        if step > 0:
            value = minimum + round((value - minimum) / step) * step
        value = max(minimum, min(maximum, value))
        return float(round(value)) if self.spec.kind == "int" else float(value)

    def _set(self, value: float, notify: bool, immediate: bool = False) -> None:
        value = self._snap(value)
        self._updating = True
        try:
            self.variable.set(value)
            self.entry_var.set(self._format(value))
        finally:
            self._updating = False
        if notify:
            self._notify(immediate)

    def _notify(self, immediate: bool) -> None:
        if immediate and self.pending_after is not None:
            try:
                self.after_cancel(self.pending_after)
            except tk.TclError:
                pass
            self.pending_after = None
        if immediate:
            self.command(True)
        elif self.pending_after is None:
            self.pending_after = self.after(
                self.throttle_ms, self._flush_change
            )

    def _flush_change(self) -> None:
        self.pending_after = None
        self.command(False)

    def _scale_changed(self, value) -> None:
        if self._updating:
            return
        self._set(float(value), notify=True, immediate=False)

    def _focus_scale(self, _event=None) -> None:
        self.scale.focus_set()

    def _track_press(self, event):
        """Jump to a clicked trough position while preserving handle drag."""
        self._focus_scale()
        try:
            element = str(self.scale.identify(event.x, event.y)).lower()
        except tk.TclError:
            element = ""
        if "slider" in element:
            return None
        try:
            start_x = float(self.scale.coords(float(self.spec.minimum))[0])
            end_x = float(self.scale.coords(float(self.spec.maximum))[0])
        except (IndexError, TypeError, tk.TclError):
            return None
        span = end_x - start_x
        if abs(span) < 1.0:
            return None
        fraction = max(0.0, min(1.0, (float(event.x) - start_x) / span))
        value = float(self.spec.minimum) + fraction * (
            float(self.spec.maximum) - float(self.spec.minimum)
        )
        self._set(value, notify=True, immediate=False)
        return "break"

    def _drag_finished(self, _event=None) -> None:
        self._set(self.variable.get(), notify=True, immediate=True)

    def _double_reset(self, _event=None):
        self.reset()
        return "break"

    def _entry_commit(self, _event=None):
        try:
            value = float(self.entry_var.get())
        except (TypeError, ValueError, tk.TclError):
            self.entry_var.set(self._format(self.variable.get()))
            return "break"
        self._set(value, notify=True, immediate=True)
        return "break"

    def _step_amount(self, state: int) -> float:
        step = float(self.spec.step or (1.0 if self.spec.kind == "int" else 0.01))
        if state & 0x0001:  # Shift
            return step * 10.0
        if state & 0x0004:  # Control
            return step * 5.0
        return step

    def _key_step(self, event, direction: int):
        amount = self._step_amount(int(getattr(event, "state", 0) or 0))
        self._set(
            self.variable.get() + direction * amount,
            notify=True,
            immediate=True,
        )
        return "break"

    def _wheel_step(self, event, x11_direction: int = 0):
        state = int(getattr(event, "state", 0) or 0)
        if self.focus_get() is not self.scale and not (state & 0x0004):
            return None
        delta = int(getattr(event, "delta", 0) or 0)
        direction = x11_direction or (-1 if delta < 0 else 1)
        return self._key_step(event, direction)

    def reset(self) -> None:
        self._set(float(self.spec.default), notify=True, immediate=True)

    def value(self):
        value = self._snap(self.variable.get())
        return int(round(value)) if self.spec.kind == "int" else float(value)

    def destroy(self) -> None:
        if self.pending_after is not None:
            try:
                self.after_cancel(self.pending_after)
            except tk.TclError:
                pass
            self.pending_after = None
        super().destroy()
