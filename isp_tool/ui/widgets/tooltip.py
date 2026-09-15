"""Small lazy tooltip; never participates in layout or parameter commits."""
import tkinter as tk
from tkinter import ttk


class Tooltip:
    def __init__(self, widget, text):
        self.widget, self.text = widget, text
        self.pending = self.window = None
        widget.bind("<Enter>", self.schedule, add="+")
        for event in ("<Leave>", "<ButtonPress>", "<Destroy>"):
            widget.bind(event, self.hide, add="+")

    def schedule(self, _event=None):
        self.hide()
        self.pending = self.widget.after(550, self.show)

    def show(self):
        self.pending = None
        if not self.widget.winfo_exists():
            return
        text = self.text() if callable(self.text) else self.text
        if not text:
            return
        self.window = tk.Toplevel(self.widget)
        self.window.overrideredirect(True)
        self.window.geometry(f"+{self.widget.winfo_pointerx()+12}+{self.widget.winfo_pointery()+18}")
        ttk.Label(self.window, text=text, padding=7, wraplength=420,
                  relief="solid", borderwidth=1).pack()

    def hide(self, _event=None):
        if self.pending:
            self.widget.after_cancel(self.pending)
            self.pending = None
        if self.window:
            self.window.destroy()
            self.window = None
