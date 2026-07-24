from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk
from typing import Any, Dict

from ..theme import COLORS


class ParameterDiff(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.current: Dict[str, Any] = {}
        self.suggested: Dict[str, Any] = {}
        self.tree = ttk.Treeview(
            self,
            columns=("parameter", "current", "suggested", "change"),
            show="headings",
            style="Status.Treeview",
            height=8,
        )
        for key, label, width in (
            ("parameter", "Parameter", 135),
            ("current", "Current", 85),
            ("suggested", "Suggested", 85),
            ("change", "Change", 75),
        ):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, anchor="w" if key == "parameter" else "e")
        self.tree.tag_configure("increase", foreground=COLORS["success"])
        self.tree.tag_configure("decrease", foreground=COLORS["warning"])
        self.tree.tag_configure("changed", foreground=COLORS["accent"])
        self.tree.pack(fill="both", expand=True)
        controls = ttk.Frame(self)
        controls.pack(fill="x", pady=(4, 0))
        ttk.Button(controls, text="Copy Row", command=self.copy_selected).pack(side="left")
        ttk.Button(
            controls, text="Copy Suggested JSON", command=self.copy_all
        ).pack(side="left", padx=4)

    def set_values(
        self, current: Dict[str, Any], suggested: Dict[str, Any]
    ) -> None:
        self.current = dict(current)
        self.suggested = dict(suggested)
        self.tree.delete(*self.tree.get_children())
        for key, suggested_value in self.suggested.items():
            current_value = self.current.get(key, "—")
            tag = ""
            if isinstance(current_value, (int, float)) and isinstance(
                suggested_value, (int, float)
            ):
                delta = suggested_value - current_value
                change = f"{delta:+.6g}"
                tag = "increase" if delta > 0 else ("decrease" if delta < 0 else "")
            else:
                changed = current_value != suggested_value
                change = "Changed" if changed else "Same"
                tag = "changed" if changed else ""
            self.tree.insert(
                "", "end", iid=str(key),
                values=(
                    key,
                    self._format(current_value),
                    self._format(suggested_value),
                    change,
                ),
                tags=(tag,) if tag else (),
            )

    def clear(self) -> None:
        self.current = {}
        self.suggested = {}
        self.tree.delete(*self.tree.get_children())

    def copy_selected(self) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        key = selected[0]
        payload = {key: self.suggested.get(key)}
        self._clipboard(json.dumps(payload, ensure_ascii=False, indent=2))

    def copy_all(self) -> None:
        self._clipboard(
            json.dumps(self.suggested, ensure_ascii=False, indent=2)
        )

    def _clipboard(self, text: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(text)

    @staticmethod
    def _format(value: Any) -> str:
        if isinstance(value, float):
            return f"{value:.6g}"
        return str(value)

