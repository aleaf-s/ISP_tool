from decimal import Decimal, InvalidOperation
import tkinter as tk
from tkinter import ttk
from .tooltip import Tooltip
from ..number_format import format_number


class ParameterControl(ttk.Frame):
    """Draft numeric entry: only valid, changed commits reach the pipeline."""
    def __init__(self, parent, spec, value, command, throttle_ms=25):
        super().__init__(parent)
        self.spec, self.command = spec, command
        self.variable = tk.DoubleVar(self, value=float(value))
        self.entry_var = tk.StringVar(self, value=self._format(value))
        self._rendered = self.entry_var.get()
        self.error_var = tk.StringVar(self)
        controls = ttk.Frame(self)
        controls.pack(fill="x")
        self.entry = ttk.Entry(controls, textvariable=self.entry_var, width=10,
                               justify="right", style="Parameter.TEntry")
        self.entry.pack(side="left")
        self.reset_button = ttk.Button(controls, text="↺", width=3, command=self.reset,
                                       style="Compact.TButton")
        self.reset_button.pack(side="left", padx=(6, 0))
        self.tooltip = Tooltip(self.entry,
            lambda:f"Range {spec.minimum} … {spec.maximum} · Default {spec.default} · Step {spec.step}\n实际值 / Value: {self.value():.12g}")
        self.reset_tooltip = Tooltip(self.reset_button, f"Reset: {spec.default}")
        self.error_label = ttk.Label(self, textvariable=self.error_var, style="Error.TLabel", wraplength=320)
        self.entry.bind("<Return>", self._entry_commit)
        self.entry.bind("<FocusOut>", self._entry_commit)
        self.entry.bind("<Up>", lambda e: self._key_step(e, 1))
        self.entry.bind("<Down>", lambda e: self._key_step(e, -1))
        # Entry has no wheel class binding; the panel's wheel router owns it.

    def _format(self, value):
        return str(int(value)) if self.spec.kind == "int" else format_number(value,step=self.spec.step)

    def _parse(self):
        if self.entry_var.get().strip()==self._rendered:
            return self.value()
        try:
            value = Decimal(self.entry_var.get().strip())
        except InvalidOperation:
            raise ValueError("请输入有效数字 / Enter a number")
        if not value.is_finite():
            raise ValueError("数值必须有限 / Finite numbers only")
        if self.spec.kind == "int" and value != value.to_integral_value():
            raise ValueError("请输入整数 / Integer required")
        if not Decimal(str(self.spec.minimum)) <= value <= Decimal(str(self.spec.maximum)):
            raise ValueError(f"范围 / Range: {self.spec.minimum} … {self.spec.maximum}")
        # Step controls keyboard increments, not silent rounding of typed values.
        return int(value) if self.spec.kind == "int" else float(value)

    def _error(self, message):
        self.error_var.set(message)
        self.error_label.pack(anchor="w", pady=(2, 0))
        self.entry.configure(style="Invalid.Parameter.TEntry")

    def _commit_value(self, value):
        changed = value != self.value()
        self.variable.set(value)
        self.entry_var.set(self._format(value))
        self._rendered = self.entry_var.get()
        self.error_var.set("")
        self.error_label.pack_forget()
        self.entry.configure(style="Parameter.TEntry")
        if changed:
            self.command(True)

    def _entry_commit(self, _event=None):
        try:
            self._commit_value(self._parse())
        except ValueError as exc:
            self._error(str(exc))
        return "break"

    def _key_step(self, event, direction):
        try:
            value = Decimal(str(self._parse()))
            multiplier = 10 if event.state & 1 else 5 if event.state & 4 else 1
            value += Decimal(str(self.spec.step or 1)) * direction * multiplier
            if not Decimal(str(self.spec.minimum)) <= value <= Decimal(str(self.spec.maximum)):
                raise ValueError(f"范围 / Range: {self.spec.minimum} … {self.spec.maximum}")
            self._commit_value(int(value) if self.spec.kind == "int" else float(value))
        except ValueError as exc:
            self._error(str(exc))
        return "break"

    def reset(self):
        self._commit_value(self.spec.default)

    def value(self):
        value = self.variable.get()
        return int(value) if self.spec.kind == "int" else float(value)
