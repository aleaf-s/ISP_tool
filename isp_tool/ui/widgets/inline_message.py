from __future__ import annotations

import tkinter as tk

from ..theme import COLORS, FONTS


class InlineMessage(tk.Label):
    def __init__(self, parent):
        super().__init__(
            parent, anchor="w", justify="left", padx=8, pady=5,
            font=FONTS["body"], wraplength=520,
        )
        self.hide()

    def show(self, text: str, level: str = "info") -> None:
        colors = {
            "info": COLORS["accent"],
            "success": COLORS["success"],
            "warning": COLORS["warning"],
            "error": COLORS["error"],
            "preview": COLORS["preview"],
        }
        color = colors.get(level, COLORS["accent"])
        self.configure(
            text=text, fg=COLORS["foreground"], bg=COLORS["panel_alt"],
            highlightbackground=color, highlightthickness=1,
        )
        if not self.winfo_manager():
            self.pack(fill="x", pady=(0, 6))

    def hide(self) -> None:
        self.pack_forget()

