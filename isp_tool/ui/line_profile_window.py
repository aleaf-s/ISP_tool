from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk
from typing import Dict, Optional, Tuple

import numpy as np

from ..sampling import LineProfile
from .theme import COLORS, FONTS


CHANNEL_COLORS = {
    "R": COLORS["channel_r"],
    "G": COLORS["channel_g"],
    "B": COLORS["channel_b"],
    "Gr": "#66D17A",
    "Gb": "#20A85A",
    "Y": COLORS["channel_y"],
    "U": "#42D4F4",
    "V": "#E879F9",
}


class LineProfileWindow(tk.Toplevel):
    """Non-modal absolute-code profile for the active pipeline stage."""

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.geometry("920x500")
        self.minsize(680, 380)
        self.transient(app.root)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.show_input_var = tk.BooleanVar(value=True)
        self.title_var = tk.StringVar(value="")
        self.summary_var = tk.StringVar(value="")
        self.hover_var = tk.StringVar(value="")
        self.channel_vars: Dict[str, tk.BooleanVar] = {}
        self.profiles: Dict[str, LineProfile] = {}
        self.stage_name = ""
        self.plot_bounds: Optional[Tuple[float, float, float, float]] = None
        self.pending_after: Optional[str] = None
        self._build()
        self.refresh_language()
        self.refresh_from_app(0)

    def tr(self, key: str, **values) -> str:
        return self.app.tr(key, **values)

    def _build(self) -> None:
        toolbar = ttk.Frame(self, padding=(10, 8))
        toolbar.pack(fill="x")
        ttk.Label(
            toolbar, textvariable=self.title_var, style="Title.TLabel"
        ).pack(side="left", padx=(0, 12))
        self.channel_frame = ttk.Frame(toolbar)
        self.channel_frame.pack(side="left")
        self.clear_button = ttk.Button(
            toolbar, text="Clear", command=self.clear_line
        )
        self.clear_button.pack(side="right")
        self.draw_button = ttk.Button(
            toolbar, text="Draw Line", command=self.app.arm_line_profile
        )
        self.draw_button.pack(side="right", padx=(0, 5))
        self.input_button = ttk.Checkbutton(
            toolbar,
            text="Show Stage Input",
            variable=self.show_input_var,
            command=lambda: self.refresh_from_app(0),
        )
        self.input_button.pack(side="right", padx=(0, 10))

        self.canvas = tk.Canvas(
            self,
            bg=COLORS["canvas_alt"],
            highlightthickness=0,
        )
        self.canvas.pack(fill="both", expand=True, padx=10)
        self.canvas.bind("<Configure>", lambda _event: self._redraw())
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", lambda _event: self.hover_var.set(""))

        footer = ttk.Frame(self, padding=(10, 7))
        footer.pack(fill="x")
        ttk.Label(
            footer, textvariable=self.summary_var, style="Muted.TLabel"
        ).pack(side="left")
        ttk.Label(
            footer, textvariable=self.hover_var, style="Muted.TLabel"
        ).pack(side="right")

    def refresh_language(self) -> None:
        self.title(self.tr("line.title"))
        self.draw_button.configure(text=self.tr("line.draw"))
        self.clear_button.configure(text=self.tr("line.clear"))
        self.input_button.configure(text=self.tr("line.show_input"))
        self._update_text()
        self._redraw()

    def refresh_from_app(self, delay: int = 50) -> None:
        if not self.winfo_exists():
            return
        if self.pending_after is not None:
            try:
                self.after_cancel(self.pending_after)
            except tk.TclError:
                pass
        self.pending_after = self.after(
            max(0, int(delay)), self._perform_refresh
        )

    def _perform_refresh(self) -> None:
        self.pending_after = None
        payload = self.app.sample_line_profiles(
            include_input=bool(self.show_input_var.get())
        )
        if payload is None:
            self.profiles = {}
            self.stage_name = self.app.current_sample_stage_name()
        else:
            self.profiles, self.stage_name = payload
        self._rebuild_channels()
        self._update_text()
        self._redraw()

    def _rebuild_channels(self) -> None:
        names = []
        for profile in self.profiles.values():
            for name in profile.channels:
                if name not in names:
                    names.append(name)
        if tuple(names) == tuple(self.channel_vars):
            return
        previous = {
            name: variable.get()
            for name, variable in self.channel_vars.items()
        }
        for child in self.channel_frame.winfo_children():
            child.destroy()
        self.channel_vars = {}
        for name in names:
            variable = tk.BooleanVar(value=previous.get(name, True))
            button = tk.Checkbutton(
                self.channel_frame,
                text=name,
                variable=variable,
                command=self._redraw,
                bg=COLORS["panel"],
                fg=CHANNEL_COLORS.get(name, COLORS["foreground"]),
                activebackground=COLORS["panel"],
                activeforeground=CHANNEL_COLORS.get(
                    name, COLORS["foreground"]
                ),
                selectcolor=COLORS["panel_alt"],
                relief="flat",
                borderwidth=0,
                highlightthickness=0,
                font=FONTS["body"],
            )
            button.pack(side="left", padx=(0, 3))
            self.channel_vars[name] = variable

    def _update_text(self) -> None:
        self.title_var.set(
            f"{self.tr('line.title')} · {self.stage_name}"
            if self.stage_name else self.tr("line.title")
        )
        output = self.profiles.get("output")
        if output is None:
            self.summary_var.set(self.tr("line.waiting"))
            return
        self.summary_var.set(self.tr(
            "line.summary",
            x0=output.source_start[0],
            y0=output.source_start[1],
            x1=output.source_end[0],
            y1=output.source_end[1],
            length=f"{output.length:.1f}",
            count=output.sample_count,
            encoding=output.encoding,
        ))

    def _enabled(self, name: str) -> bool:
        variable = self.channel_vars.get(name)
        return bool(variable is not None and variable.get())

    def _series(self):
        for role in ("input", "output"):
            profile = self.profiles.get(role)
            if profile is None:
                continue
            for name, values in profile.channels.items():
                if self._enabled(name):
                    yield role, name, profile, np.asarray(values)

    def _redraw(self) -> None:
        if not hasattr(self, "canvas"):
            return
        self.canvas.delete("all")
        width = max(self.canvas.winfo_width(), 10)
        height = max(self.canvas.winfo_height(), 10)
        left, top, right, bottom = 62, 18, width - 18, height - 42
        if right <= left or bottom <= top:
            return
        series = list(self._series())
        if not series:
            self.plot_bounds = None
            self.canvas.create_text(
                width / 2,
                height / 2,
                text=self.tr("line.waiting"),
                fill=COLORS["muted"],
                font=FONTS["body"],
            )
            return
        finite_values = [
            values[np.isfinite(values)]
            for _role, _name, _profile, values in series
            if np.any(np.isfinite(values))
        ]
        if not finite_values:
            return
        code_max = max(profile.code_max for _, _, profile, _ in series)
        minimum = min(0.0, min(float(np.min(v)) for v in finite_values))
        maximum = max(
            float(code_max), max(float(np.max(v)) for v in finite_values)
        )
        if math.isclose(minimum, maximum):
            maximum = minimum + 1.0
        max_distance = max(profile.length for _, _, profile, _ in series)
        max_distance = max(max_distance, 1.0)
        self.plot_bounds = (left, top, right, bottom)
        for index in range(5):
            fraction = index / 4
            y = bottom - fraction * (bottom - top)
            value = minimum + fraction * (maximum - minimum)
            self.canvas.create_line(
                left, y, right, y, fill=COLORS["grid"], dash=(2, 4)
            )
            self.canvas.create_text(
                left - 7,
                y,
                text=f"{value:.0f}",
                anchor="e",
                fill=COLORS["muted"],
                font=FONTS["small"],
            )
        self.canvas.create_line(left, top, left, bottom, fill=COLORS["border"])
        self.canvas.create_line(
            left, bottom, right, bottom, fill=COLORS["border"]
        )
        self.canvas.create_text(
            (left + right) / 2,
            height - 13,
            text=self.tr("line.axis_distance"),
            fill=COLORS["muted"],
            font=FONTS["small"],
        )
        for role, name, profile, values in series:
            finite = np.isfinite(values)
            if not np.any(finite):
                continue
            indexes = np.flatnonzero(finite)
            if indexes.size > 2048:
                step = int(math.ceil(indexes.size / 2048))
                indexes = indexes[::step]
            x = left + profile.distances[indexes] / max_distance * (right - left)
            y = bottom - (
                (values[indexes] - minimum) / (maximum - minimum)
            ) * (bottom - top)
            points = [coordinate for pair in zip(x, y) for coordinate in pair]
            color = CHANNEL_COLORS.get(name, COLORS["foreground"])
            options = {
                "fill": color,
                "width": 2 if role == "output" else 1,
            }
            if role == "input":
                options["dash"] = (5, 3)
            if len(points) >= 4:
                self.canvas.create_line(*points, **options)
            elif len(points) == 2:
                px, py = points
                self.canvas.create_oval(
                    px - 2, py - 2, px + 2, py + 2,
                    fill=color, outline="",
                )
        legend = self.tr("line.legend")
        if "input" in self.profiles:
            legend += f" · {self.tr('line.input_dashed')}"
        self.canvas.create_text(
            right,
            top,
            text=legend,
            anchor="ne",
            fill=COLORS["muted"],
            font=FONTS["small"],
        )

    def _on_motion(self, event) -> None:
        if self.plot_bounds is None or not self.profiles:
            return
        left, top, right, bottom = self.plot_bounds
        if not (left <= event.x <= right and top <= event.y <= bottom):
            self.hover_var.set("")
            return
        output = self.profiles.get("output") or next(iter(self.profiles.values()))
        distance = (event.x - left) / max(right - left, 1) * max(
            output.length, 1.0
        )
        details = [f"d={distance:.1f}"]
        for role, name, profile, values in self._series():
            finite = np.flatnonzero(np.isfinite(values))
            if not finite.size:
                continue
            nearest = finite[
                np.argmin(np.abs(profile.distances[finite] - distance))
            ]
            prefix = "In" if role == "input" else "Out"
            details.append(f"{prefix} {name}={values[nearest]:.0f}")
        self.hover_var.set(" · ".join(details))

    def clear_line(self) -> None:
        self.app.clear_line_profile()

    def on_image_changed(self) -> None:
        self.profiles = {}
        self.stage_name = ""
        self._rebuild_channels()
        self._update_text()
        self._redraw()

    def close(self) -> None:
        if self.pending_after is not None:
            try:
                self.after_cancel(self.pending_after)
            except tk.TclError:
                pass
            self.pending_after = None
        self.app.line_profile_window = None
        self.app.cancel_line_profile(clear_line=True)
        self.destroy()
