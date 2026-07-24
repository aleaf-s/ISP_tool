from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from typing import Optional

from ..models import ParameterRecommendation
from .theme import COLORS, FONTS
from .widgets import ArtifactGallery, ParameterDiff, StatusBadge


class RecommendationView(ttk.Frame):
    """Unified parameter, diagnostics and artifact result surface."""

    def __init__(self, parent):
        super().__init__(parent)
        self.result: Optional[ParameterRecommendation] = None
        self._build()

    def _build(self) -> None:
        summary = ttk.Frame(self)
        summary.pack(fill="x")
        self.badge = StatusBadge(summary)
        self.badge.pack(side="left")
        self.confidence_var = tk.StringVar(value="Confidence: —")
        self.target_var = tk.StringVar(value="Target: —")
        self.time_var = tk.StringVar(value="Time: —")
        ttk.Label(summary, textvariable=self.target_var).pack(side="left", padx=8)
        ttk.Label(
            summary, textvariable=self.confidence_var, style="Muted.TLabel"
        ).pack(side="left", padx=8)
        ttk.Label(
            summary, textvariable=self.time_var, style="Muted.TLabel"
        ).pack(side="right")

        vertical = ttk.Panedwindow(self, orient="vertical")
        vertical.pack(fill="both", expand=True, pady=(6, 0))
        top = ttk.Frame(vertical)
        bottom = ttk.Frame(vertical)
        vertical.add(top, weight=2)
        vertical.add(bottom, weight=3)

        self.parameter_diff = ParameterDiff(top)
        self.parameter_diff.pack(fill="both", expand=True)

        details = ttk.Notebook(bottom)
        details.pack(fill="both", expand=True)
        measurement_tab = ttk.Frame(details, padding=4)
        warning_tab = ttk.Frame(details, padding=4)
        artifact_tab = ttk.Frame(details, padding=4)
        details.add(measurement_tab, text="Measurements")
        details.add(warning_tab, text="Warnings")
        details.add(artifact_tab, text="Artifacts")
        self.measurements = ScrolledText(
            measurement_tab, bg=COLORS["background"],
            fg=COLORS["foreground"],
            insertbackground="white", font=FONTS["mono"],
        )
        self.measurements.pack(fill="both", expand=True)
        self.warnings = ScrolledText(
            warning_tab, bg=COLORS["warning_panel"],
            fg=COLORS["warning_text"],
            insertbackground="white", font=FONTS["body"],
        )
        self.warnings.pack(fill="both", expand=True)
        self.artifact_gallery = ArtifactGallery(artifact_tab)
        self.artifact_gallery.pack(fill="both", expand=True)

    def set_result(self, result: ParameterRecommendation, base_image=None) -> None:
        self.result = result
        state = "APPLIED" if result.applied else "SUGGESTED"
        self.badge.set_state(state)
        self.target_var.set(
            f"Target: {result.target} · {result.method or result.module_id}"
        )
        self.confidence_var.set(f"Confidence: {result.confidence * 100:.1f}%")
        self.time_var.set(f"Time: {result.elapsed_ms:.1f} ms")
        self.parameter_diff.set_values(
            result.current_parameters, result.suggested_parameters
        )
        self._set_text(
            self.measurements,
            json.dumps(result.measurements, ensure_ascii=False, indent=2),
        )
        self._set_text(
            self.warnings,
            "\n".join(f"• {item}" for item in result.warnings)
            if result.warnings else "No warnings.",
        )
        self.artifact_gallery.set_artifacts(result.artifacts, base_image)

    def set_state(self, state, text: str = "") -> None:
        self.badge.set_state(state, text)

    def clear(self) -> None:
        self.result = None
        self.badge.set_state("NOT_ANALYZED")
        self.parameter_diff.clear()
        self._set_text(self.measurements, "")
        self._set_text(self.warnings, "")
        self.artifact_gallery.set_artifacts({})

    @staticmethod
    def _set_text(widget, text: str) -> None:
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
