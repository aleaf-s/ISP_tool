from __future__ import annotations

import tkinter as tk

from ..theme import COLORS, FONTS, STATUS_COLORS


class StatusBadge(tk.Label):
    def __init__(self, parent, state: str = "NOT_ANALYZED", **kwargs):
        super().__init__(
            parent, font=FONTS["body"], padx=7, pady=2,
            relief="flat", **kwargs,
        )
        self.set_state(state)

    def set_state(self, state: str, text: str = "") -> None:
        key = getattr(state, "value", str(state))
        color = STATUS_COLORS.get(key, COLORS["muted"])
        label = text or key.replace("_", " ").title()
        self.configure(
            text=label, fg=color, bg=COLORS["panel_alt"],
            highlightbackground=color, highlightthickness=1,
        )

