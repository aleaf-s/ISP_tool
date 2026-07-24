from __future__ import annotations

import tkinter as tk
from typing import Optional

from ..theme import COLORS, FONTS


class ToastManager:
    def __init__(self, root: tk.Misc):
        self.root = root
        self.current: Optional[tk.Toplevel] = None
        self.after_id: Optional[str] = None

    def show(self, text: str, level: str = "info", duration: int = 2600) -> None:
        self.close()
        toast = tk.Toplevel(self.root)
        self.current = toast
        toast.overrideredirect(True)
        colors = {
            "info": COLORS["accent"],
            "success": COLORS["success"],
            "warning": COLORS["warning"],
            "error": COLORS["error"],
        }
        border = colors.get(level, COLORS["accent"])
        label = tk.Label(
            toast, text=text, bg=COLORS["panel_alt"], fg=COLORS["foreground"],
            font=FONTS["body"], padx=14, pady=9,
            highlightbackground=border, highlightthickness=1,
        )
        label.pack()
        toast.update_idletasks()
        x = self.root.winfo_rootx() + self.root.winfo_width() - toast.winfo_width() - 24
        y = self.root.winfo_rooty() + 54
        toast.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.after_id = toast.after(duration, self.close)

    def close(self) -> None:
        if self.current is None:
            return
        try:
            if self.after_id is not None:
                self.current.after_cancel(self.after_id)
            if self.current.winfo_exists():
                self.current.destroy()
        except tk.TclError:
            pass
        self.current = None
        self.after_id = None
