from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Dict, Optional, Tuple

from ..sampling import PixelSample
from .theme import COLORS, FONTS


class PixelInspectorWindow(tk.Toplevel):
    """Non-modal current-stage pixel and neighborhood inspector."""

    MAX_PINS = 16

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.geometry("980x620")
        self.minsize(720, 480)
        self.transient(app.root)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.follow_var = tk.BooleanVar(value=True)
        self.size_var = tk.StringVar(value="5×5")
        self.header_var = tk.StringVar(value="")
        self.center_var = tk.StringVar(value="")
        self.message_var = tk.StringVar(value="")
        self.current_sample: Optional[PixelSample] = None
        self.current_stage_name = ""
        self.last_source_point: Optional[Tuple[int, int]] = None
        self.pins: Dict[str, Tuple[int, int]] = {}
        self.pin_samples: Dict[str, PixelSample] = {}
        self._next_pin_id = 1
        self._build()
        self.refresh_language()

    def tr(self, key: str, **values) -> str:
        return self.app.tr(key, **values)

    @property
    def neighborhood_size(self) -> int:
        return 7 if self.size_var.get().startswith("7") else 5

    def _build(self) -> None:
        toolbar = ttk.Frame(self, padding=(10, 8))
        toolbar.pack(fill="x")
        self.title_label = ttk.Label(
            toolbar, text="Pixel Inspector", style="Title.TLabel"
        )
        self.title_label.pack(side="left", padx=(0, 14))
        self.follow_button = ttk.Checkbutton(
            toolbar,
            text="Follow Cursor",
            variable=self.follow_var,
            command=self._follow_changed,
        )
        self.follow_button.pack(side="left")
        self.size_label = ttk.Label(toolbar, text="Neighborhood")
        self.size_label.pack(side="left", padx=(14, 4))
        self.size_combo = ttk.Combobox(
            toolbar,
            textvariable=self.size_var,
            values=("5×5", "7×7"),
            state="readonly",
            width=6,
        )
        self.size_combo.pack(side="left")
        self.size_combo.bind(
            "<<ComboboxSelected>>", lambda _event: self.refresh_from_app()
        )
        self.clear_button = ttk.Button(
            toolbar, text="Clear Pins", command=self.clear_pins
        )
        self.clear_button.pack(side="right")
        self.pin_button = ttk.Button(
            toolbar, text="Pin Current", command=self.pin_current
        )
        self.pin_button.pack(side="right", padx=(0, 5))

        ttk.Label(
            self,
            textvariable=self.header_var,
            style="Muted.TLabel",
            padding=(10, 2),
        ).pack(fill="x")
        ttk.Label(
            self,
            textvariable=self.center_var,
            style="Title.TLabel",
            padding=(10, 3),
        ).pack(fill="x")

        body = ttk.Panedwindow(self, orient="vertical")
        body.pack(fill="both", expand=True, padx=10, pady=(4, 8))
        upper = ttk.Frame(body)
        lower = ttk.Frame(body)
        body.add(upper, weight=3)
        body.add(lower, weight=2)

        stats_frame = ttk.Frame(upper)
        stats_frame.pack(side="left", fill="y", padx=(0, 8))
        self.stats_label = ttk.Label(
            stats_frame, text="Neighborhood Statistics"
        )
        self.stats_label.pack(anchor="w", pady=(0, 4))
        self.stats_tree = ttk.Treeview(
            stats_frame,
            columns=("channel", "min", "mean", "median", "max", "std", "count"),
            show="headings",
            height=8,
        )
        widths = (66, 75, 82, 82, 75, 82, 58)
        for name, width in zip(self.stats_tree["columns"], widths):
            self.stats_tree.heading(name, text=name.title())
            self.stats_tree.column(name, width=width, anchor="e")
        self.stats_tree.column("channel", anchor="center")
        self.stats_tree.pack(fill="y", expand=False)

        grid_frame = ttk.Frame(upper)
        grid_frame.pack(side="left", fill="both", expand=True)
        self.grid_label = ttk.Label(grid_frame, text="Absolute Code Grid")
        self.grid_label.pack(anchor="w", pady=(0, 4))
        self.grid_text = tk.Text(
            grid_frame,
            bg=COLORS["canvas_alt"],
            fg=COLORS["foreground"],
            insertbackground=COLORS["foreground"],
            font=FONTS["mono"],
            relief="flat",
            wrap="none",
            height=10,
        )
        grid_x = ttk.Scrollbar(
            grid_frame, orient="horizontal", command=self.grid_text.xview
        )
        self.grid_text.configure(xscrollcommand=grid_x.set)
        self.grid_text.pack(fill="both", expand=True)
        grid_x.pack(fill="x")

        self.pins_label = ttk.Label(lower, text="Pinned Points")
        self.pins_label.pack(anchor="w", pady=(0, 4))
        self.pins_tree = ttk.Treeview(
            lower,
            columns=("id", "coordinate", "stage", "values"),
            show="headings",
            height=7,
        )
        for name, width in (
            ("id", 58),
            ("coordinate", 135),
            ("stage", 210),
            ("values", 480),
        ):
            self.pins_tree.heading(name, text=name.title())
            self.pins_tree.column(name, width=width, anchor="w")
        self.pins_tree.pack(fill="both", expand=True)
        self.pins_tree.bind("<<TreeviewSelect>>", self._pin_selected)
        ttk.Label(
            self,
            textvariable=self.message_var,
            style="Muted.TLabel",
            padding=(10, 0, 10, 8),
        ).pack(fill="x")

    def refresh_language(self) -> None:
        self.title(self.tr("pixel.title"))
        self.title_label.configure(text=self.tr("pixel.title"))
        self.follow_button.configure(text=self.tr("pixel.follow"))
        self.size_label.configure(text=self.tr("pixel.neighborhood"))
        self.pin_button.configure(text=self.tr("pixel.pin"))
        self.clear_button.configure(text=self.tr("pixel.clear"))
        self.stats_label.configure(text=self.tr("pixel.statistics"))
        self.grid_label.configure(text=self.tr("pixel.grid"))
        self.pins_label.configure(text=self.tr("pixel.pins"))
        if self.current_sample is not None:
            self._show_sample(
                self.current_sample, self.current_stage_name
            )

    def _follow_changed(self) -> None:
        if self.follow_var.get() and self.last_source_point is not None:
            self.refresh_from_app()

    @staticmethod
    def _values_text(sample: PixelSample) -> str:
        return "  ".join(
            f"{name}={value}"
            for name, value in sample.absolute_values.items()
        )

    def update_hover(self, sample: PixelSample, stage_name: str) -> None:
        self.last_source_point = (sample.source_x, sample.source_y)
        if not self.follow_var.get():
            return
        self._show_sample(sample, stage_name)

    def _show_sample(self, sample: PixelSample, stage_name: str) -> None:
        self.current_sample = sample
        self.current_stage_name = stage_name
        self.header_var.set(
            f"{stage_name} · {sample.encoding} · "
            f"x={sample.source_x}, y={sample.source_y} · "
            f"{sample.neighborhood_size}×{sample.neighborhood_size}"
        )
        self.center_var.set(
            f"{self.tr('pixel.center')}: {self._values_text(sample)}"
        )
        for item in self.stats_tree.get_children():
            self.stats_tree.delete(item)
        for name, stats in sample.statistics.items():
            self.stats_tree.insert(
                "",
                "end",
                values=(
                    name,
                    f"{stats.minimum:.1f}",
                    f"{stats.mean:.2f}",
                    f"{stats.median:.2f}",
                    f"{stats.maximum:.1f}",
                    f"{stats.stddev:.2f}",
                    stats.count,
                ),
            )
        self.grid_text.configure(state="normal")
        self.grid_text.delete("1.0", "end")
        self.grid_text.insert(
            "1.0", "\n".join("  ".join(row) for row in sample.grid)
        )
        self.grid_text.configure(state="disabled")
        self.message_var.set("")

    def pin_current(self) -> None:
        if self.current_sample is None:
            self.message_var.set(self.tr("pixel.move_cursor"))
            return
        if len(self.pins) >= self.MAX_PINS:
            self.message_var.set(
                self.tr("pixel.pin_limit", count=self.MAX_PINS)
            )
            return
        pin_id = f"P{self._next_pin_id}"
        self._next_pin_id += 1
        self.pins[pin_id] = (
            self.current_sample.source_x,
            self.current_sample.source_y,
        )
        self.pin_samples[pin_id] = self.current_sample
        self._refresh_pin_rows()

    def clear_pins(self) -> None:
        self.pins.clear()
        self.pin_samples.clear()
        self._refresh_pin_rows()

    def on_image_changed(self) -> None:
        self.current_sample = None
        self.last_source_point = None
        self.clear_pins()
        self.header_var.set(self.tr("pixel.move_cursor"))
        self.center_var.set("")
        for item in self.stats_tree.get_children():
            self.stats_tree.delete(item)
        self.grid_text.configure(state="normal")
        self.grid_text.delete("1.0", "end")
        self.grid_text.configure(state="disabled")

    def refresh_from_app(self) -> None:
        if not self.winfo_exists() or not self.app.results:
            return
        if self.follow_var.get() and self.last_source_point is not None:
            sampled = self.app.sample_source_point(
                self.last_source_point,
                self.neighborhood_size,
            )
            if sampled is not None:
                sample, stage_name = sampled
                self._show_sample(sample, stage_name)
        for pin_id, point in tuple(self.pins.items()):
            sampled = self.app.sample_source_point(
                point, self.neighborhood_size
            )
            if sampled is not None:
                self.pin_samples[pin_id] = sampled[0]
            else:
                self.pin_samples.pop(pin_id, None)
        self._refresh_pin_rows()
        selection = self.pins_tree.selection()
        if selection:
            sample = self.pin_samples.get(selection[0])
            if sample is not None:
                self._show_sample(
                    sample, self.app.current_sample_stage_name()
                )

    def _refresh_pin_rows(self) -> None:
        selection = self.pins_tree.selection()
        selected = selection[0] if selection else ""
        for item in self.pins_tree.get_children():
            self.pins_tree.delete(item)
        stage_name = self.app.current_sample_stage_name()
        for pin_id, point in self.pins.items():
            sample = self.pin_samples.get(pin_id)
            values = self._values_text(sample) if sample is not None else "—"
            self.pins_tree.insert(
                "",
                "end",
                iid=pin_id,
                values=(pin_id, f"x={point[0]}, y={point[1]}", stage_name, values),
            )
        if selected and self.pins_tree.exists(selected):
            self.pins_tree.selection_set(selected)

    def _pin_selected(self, _event=None) -> None:
        selection = self.pins_tree.selection()
        if not selection:
            return
        sample = self.pin_samples.get(selection[0])
        if sample is not None:
            self.follow_var.set(False)
            self._show_sample(sample, self.app.current_sample_stage_name())

    def close(self) -> None:
        self.app.pixel_inspector_window = None
        self.destroy()
