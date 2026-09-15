"""Shared draft-only CCM editor; representation changes never apply a matrix."""
import tkinter as tk
from tkinter import ttk
import numpy as np
from ...ccm_encoding import encode_ccm, decode_ccm

FLOAT = "Float"
FIXED = "Fixed 13-bit / ×1024"


class CCMMatrixEditor(ttk.Frame):
    def __init__(self, parent, matrix, preference=None):
        super().__init__(parent)
        self.preference = preference if preference is not None else tk.StringVar(self, value=FLOAT)
        self.mode = FLOAT
        self.mode_var = tk.StringVar(self, value=FLOAT)
        self.combo = ttk.Combobox(self, textvariable=self.mode_var, values=(FLOAT, FIXED), state="readonly")
        self.combo.pack(fill="x", pady=(0, 5))
        self.combo.bind("<<ComboboxSelected>>", self._mode_selected)
        grid = ttk.Frame(self)
        grid.pack(anchor="w")
        self.variables, self.entries = [], []
        for r in range(3):
            for c in range(3):
                variable = tk.StringVar(self)
                entry = ttk.Entry(grid, textvariable=variable, justify="right", width=9, style="Parameter.TEntry")
                entry.grid(row=r, column=c, sticky="ew", padx=3, pady=4)
                self.variables.append(variable)
                self.entries.append(entry)
        self.message_var = tk.StringVar(self)
        ttk.Label(self, textvariable=self.message_var, style="Muted.TLabel", wraplength=360).pack(fill="x")
        self._trace = self.preference.trace_add("write", self._preference_changed)
        self.set_matrix(matrix)

    def set_matrix(self, matrix):
        self.precise = np.asarray(matrix, dtype=float).reshape(3, 3).copy()
        self.mode = FLOAT
        self._render()
        if self.preference.get() == FIXED:
            self.set_mode(FIXED)

    def _render(self):
        values = self.precise.ravel()
        texts = [str(encode_ccm(v)) for v in values] if self.mode == FIXED else [format(v, ".12g") for v in values]
        for var, text in zip(self.variables, texts):
            var.set(text)
        cell_width = max(8, min(12, max(map(len, texts)) + 1))
        for entry in self.entries:
            entry.configure(width=cell_width)
        self._rendered = texts
        self.mode_var.set(self.mode)
        approximate = self.mode == FIXED and any(decode_ccm(encode_ccm(v)) != v for v in values)
        self.message_var.set("Fixed 为量化近似 / Quantized view; Float precision retained" if approximate else "")

    def matrix(self):
        values = self.precise.ravel().copy()
        for i, variable in enumerate(self.variables):
            text = variable.get().strip()
            if text == self._rendered[i]:
                continue
            try:
                if self.mode == FIXED:
                    if not text.isascii() or not text.isdecimal():
                        raise ValueError("Fixed code must be an integer in 0…8191")
                    values[i] = decode_ccm(int(text))
                else:
                    value = float(text)
                    if not np.isfinite(value) or not -4 <= value <= 4:
                        raise ValueError("Float range: −4 … +4")
                    values[i] = value
            except ValueError as exc:
                self.message_var.set(f"M{i//3+1}{i%3+1}: {exc}")
                raise ValueError(self.message_var.get()) from exc
        return values.reshape(3, 3)

    def set_mode(self, mode):
        if mode not in (FLOAT, FIXED):
            return False
        try:
            matrix = self.matrix()
            if mode == FIXED:
                for value in matrix.ravel():
                    encode_ccm(value)
            self.precise = matrix
            self.mode = mode
            self._render()
            return True
        except ValueError as exc:
            self.message_var.set(str(exc))
            self.mode_var.set(self.mode)
            return False

    def _mode_selected(self, _event=None):
        if self.set_mode(self.mode_var.get()):
            self.preference.set(self.mode)

    def _preference_changed(self, *_args):
        if self.preference.get() != self.mode:
            self.set_mode(self.preference.get())

    def snapshot(self):
        return (self.precise.copy(), self.mode, list(self._rendered), [v.get() for v in self.variables])

    def restore(self, snapshot):
        self.precise, self.mode, self._rendered, texts = snapshot
        self.mode_var.set(self.mode)
        for var, text in zip(self.variables, texts):
            var.set(text)
        if self.preference.get() != self.mode:
            self.set_mode(self.preference.get())

    def destroy(self):
        self.preference.trace_remove("write", self._trace)
        super().destroy()
