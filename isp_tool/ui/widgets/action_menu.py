from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, List, Optional, Tuple


class ActionMenu(ttk.Menubutton):
    """Compact command menu with refreshable item states."""

    def __init__(
        self,
        parent,
        text: str,
        style: str = "Secondary.TButton",
        **kwargs,
    ):
        super().__init__(parent, text=f"{text} ▾", style=style, **kwargs)
        self.menu = tk.Menu(self, tearoff=False)
        self.configure(menu=self.menu)
        self._dynamic: List[Tuple[int, Callable[[], bool]]] = []
        self.menu.configure(postcommand=self.refresh_states)

    def add_command(
        self,
        label: str,
        command: Callable[[], None],
        enabled: Optional[Callable[[], bool]] = None,
        accelerator: str = "",
    ) -> int:
        self.menu.add_command(
            label=label, command=command, accelerator=accelerator
        )
        index = int(self.menu.index("end"))
        if enabled is not None:
            self._dynamic.append((index, enabled))
        return index

    def add_checkbutton(
        self,
        label: str,
        variable: tk.Variable,
        command: Optional[Callable[[], None]] = None,
        enabled: Optional[Callable[[], bool]] = None,
    ) -> int:
        self.menu.add_checkbutton(
            label=label, variable=variable, command=command
        )
        index = int(self.menu.index("end"))
        if enabled is not None:
            self._dynamic.append((index, enabled))
        return index

    def add_radiobutton(
        self,
        label: str,
        variable: tk.Variable,
        value,
        command: Optional[Callable[[], None]] = None,
    ) -> int:
        self.menu.add_radiobutton(
            label=label, variable=variable, value=value, command=command
        )
        return int(self.menu.index("end"))

    def add_separator(self) -> None:
        self.menu.add_separator()

    def add_cascade(self, label: str, submenu: tk.Menu) -> None:
        self.menu.add_cascade(label=label, menu=submenu)

    def refresh_states(self) -> None:
        for index, predicate in self._dynamic:
            try:
                enabled = bool(predicate())
            except Exception:
                enabled = False
            self.menu.entryconfigure(
                index, state="normal" if enabled else "disabled"
            )
