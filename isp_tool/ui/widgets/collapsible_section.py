from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional


class CollapsibleSection(ttk.Frame):
    def __init__(
        self,
        parent,
        title: str,
        expanded: bool = True,
        on_toggle: Optional[Callable[[bool], None]] = None,
    ):
        super().__init__(parent)
        self.title = title
        self.expanded = bool(expanded)
        self.on_toggle = on_toggle
        self.button = ttk.Button(
            self, style="Secondary.TButton", command=self.toggle
        )
        self.button.pack(fill="x")
        self.body = ttk.Frame(self, padding=(6, 6))
        self._sync()

    def toggle(self) -> None:
        self.set_expanded(not self.expanded)

    def set_expanded(self, expanded: bool) -> None:
        self.expanded = bool(expanded)
        self._sync()
        if self.on_toggle:
            self.on_toggle(self.expanded)

    def _sync(self) -> None:
        self.button.configure(
            text=f"{'▼' if self.expanded else '▶'}  {self.title}"
        )
        if self.expanded:
            if not self.body.winfo_manager():
                self.body.pack(fill="both", expand=True)
        else:
            self.body.pack_forget()

