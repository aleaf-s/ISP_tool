from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk
from typing import Dict, Optional, Tuple


def normalize_wheel_delta(
    delta: int = 0,
    button_number: Optional[int] = None,
) -> float:
    """Return scroll units where positive means down/right."""

    if button_number == 4:
        return -1.0
    if button_number == 5:
        return 1.0
    if delta == 0:
        return 0.0
    if sys.platform == "darwin":
        return -float(delta)
    return -float(delta) / 120.0


class MouseWheelRouter:
    """Route wheel input to the nearest registered widget under the pointer."""

    def __init__(self, root: tk.Misc) -> None:
        self.root = root
        self._targets: Dict[str, Tuple[tk.Misc, str]] = {}
        self._remainders: Dict[Tuple[str, str], float] = {}
        self._closed = False
        root.bind_all("<MouseWheel>", self._on_wheel, add="+")
        root.bind_all("<Button-4>", self._on_wheel, add="+")
        root.bind_all("<Button-5>", self._on_wheel, add="+")

    def register(
        self,
        widget: tk.Misc,
        target: Optional[tk.Misc] = None,
        axis: str = "y",
    ) -> None:
        self._targets[str(widget)] = (target or widget, axis)

    def unregister(self, widget: tk.Misc) -> None:
        self._targets.pop(str(widget), None)

    def _candidate_targets(self, widget: tk.Misc):
        current: Optional[tk.Misc] = widget
        seen = set()
        while current is not None:
            registration = self._targets.get(str(current))
            if registration is not None and id(registration[0]) not in seen:
                seen.add(id(registration[0]))
                yield registration
            current = getattr(current, "master", None)

    @staticmethod
    def _can_scroll(target: tk.Misc, axis: str, units: int) -> bool:
        view_name = "xview" if axis == "x" else "yview"
        try:
            first, last = getattr(target, view_name)()
        except (AttributeError, tk.TclError, TypeError):
            return False
        if units < 0:
            return float(first) > 1e-6
        if units > 0:
            return float(last) < 1.0 - 1e-6
        return False

    def _scroll(
        self,
        target: tk.Misc,
        axis: str,
        amount: float,
    ) -> bool:
        key = (str(target), axis)
        accumulated = self._remainders.get(key, 0.0) + amount
        units = int(accumulated)
        self._remainders[key] = accumulated - units
        if units == 0:
            direction = -1 if accumulated < 0 else 1
            if not self._can_scroll(target, axis, direction):
                self._remainders[key] = 0.0
                return False
            return True
        if not self._can_scroll(target, axis, units):
            self._remainders[key] = 0.0
            return False
        view_name = "xview_scroll" if axis == "x" else "yview_scroll"
        try:
            getattr(target, view_name)(units, "units")
        except (AttributeError, tk.TclError):
            return False
        return True

    def _on_wheel(self, event):
        if self._closed:
            return None
        widget = event.widget
        try:
            pointed = self.root.winfo_containing(
                int(getattr(event, "x_root", 0)),
                int(getattr(event, "y_root", 0)),
            )
            if pointed is not None:
                widget = pointed
        except (AttributeError, tk.TclError, TypeError, ValueError):
            pass
        try:
            if widget.winfo_class() in {"TCombobox", "ComboboxPopdown"}:
                return None
        except tk.TclError:
            return None
        amount = normalize_wheel_delta(
            int(getattr(event, "delta", 0) or 0),
            getattr(event, "num", None),
        )
        if amount == 0:
            return None
        shift = bool(int(getattr(event, "state", 0) or 0) & 0x0001)
        for target, default_axis in self._candidate_targets(widget):
            axis = "x" if shift else default_axis
            if self._scroll(target, axis, amount):
                return "break"
        return None

    def close(self) -> None:
        # bind_all callbacks vanish with the root. Marking closed prevents any
        # late event from touching widgets during teardown.
        self._closed = True
        self._targets.clear()
        self._remainders.clear()


class ScrollableFrame(ttk.Frame):
    """Reusable vertically scrollable ttk frame."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(
            self, orient="vertical", command=self.canvas.yview
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = ttk.Frame(self.canvas)
        self.window = self.canvas.create_window(
            (0, 0), window=self.body, anchor="nw"
        )
        self.body.bind("<Configure>", self._sync_region)
        self.canvas.bind("<Configure>", self._sync_width)

    def _sync_region(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _sync_width(self, event) -> None:
        self.canvas.itemconfigure(self.window, width=event.width)
