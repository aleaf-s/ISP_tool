from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional


class BusyOverlay(ttk.Frame):
    def __init__(self, parent, cancel_command: Optional[Callable[[], None]] = None):
        super().__init__(parent, style="Panel.TFrame", padding=8)
        self.cancel_command = cancel_command
        self.started = 0.0
        self.after_id: Optional[str] = None
        self.task_var = tk.StringVar(value="")
        self.time_var = tk.StringVar(value="0.0 s")
        ttk.Label(self, textvariable=self.task_var, style="Preview.TLabel").pack(side="left")
        ttk.Label(self, textvariable=self.time_var, style="Muted.TLabel").pack(
            side="left", padx=10
        )
        self.cancel_button = ttk.Button(
            self, text="Cancel", style="Danger.TButton", command=self._cancel
        )
        self.cancel_button.pack(side="right")

    def show(self, task: str, stage: str = "") -> None:
        self.started = time.perf_counter()
        self.task_var.set(f"{task} · {stage}" if stage else task)
        if not self.winfo_manager():
            self.pack(fill="x", pady=(0, 6))
        self._tick()

    def hide(self) -> None:
        if self.after_id is not None:
            try:
                self.after_cancel(self.after_id)
            except tk.TclError:
                pass
            self.after_id = None
        self.pack_forget()

    def _tick(self) -> None:
        if not self.winfo_manager():
            return
        self.time_var.set(f"{time.perf_counter() - self.started:.1f} s")
        self.after_id = self.after(100, self._tick)

    def _cancel(self) -> None:
        if self.cancel_command:
            self.cancel_command()
