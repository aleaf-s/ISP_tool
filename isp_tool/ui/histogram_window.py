from __future__ import annotations

import copy
import time
import tkinter as tk
from concurrent.futures import Future
from tkinter import ttk

import numpy as np

from ..analysis import compute_histogram_details
from ..yuv import compute_yuv_histogram_details
from .theme import COLORS, FONTS


DOMAIN_CHANNELS = {
    "bayer": ("R", "Gr", "Gb", "B"),
    "rgb": ("R", "G", "B"),
    "yuv": ("Y", "U", "V"),
}

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


class HistogramWindow(tk.Toplevel):
    """Single non-modal histogram view tracking the active module output."""

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title(self.tr("hist.title"))
        self.minsize(680, 360)
        geometry = str(getattr(app, "histogram_window_geometry", ""))
        self.geometry(geometry or "860x440")
        self.transient(app.root)
        self.protocol("WM_DELETE_WINDOW", self.close)

        self.generation = 0
        self.pending_after = None
        self.poll_after_ids: set[str] = set()
        self.future: Future | None = None
        self.cache = {}
        self.cache_limit = 12
        self.current_domain = ""
        self.channel_vars = {}
        self.channel_buttons = {}
        self.last_payload = None
        self.plot_bounds = None
        self.scale_var = tk.StringVar(
            value=getattr(app, "histogram_scale", "Log")
        )
        self.roi_var = tk.BooleanVar(
            value=bool(getattr(app, "histogram_use_roi", True))
        )
        self.title_var = tk.StringVar(
            value=self.tr("hist.waiting_title")
        )
        self.summary_var = tk.StringVar(value=self.tr("hist.waiting"))
        self.hover_var = tk.StringVar(value="")
        self._build()
        self.refresh(0)

    def tr(self, key: str, **values) -> str:
        return self.app.tr(key, **values)

    def refresh_language(self) -> None:
        self.title(self.tr("hist.title"))
        self.y_axis_label.configure(text=self.tr("hist.axis"))
        if self.app.results:
            result = self.app.results[self._module_result_index()]
            self.title_var.set(f"Histogram · {result.name}")
        else:
            self.title_var.set(self.tr("hist.waiting_title"))
            self.summary_var.set(self.tr("hist.waiting"))
        if self.last_payload is not None:
            self._redraw()

    def _build(self) -> None:
        toolbar = ttk.Frame(self, padding=(10, 8))
        toolbar.pack(fill="x")
        ttk.Label(
            toolbar, textvariable=self.title_var, style="Title.TLabel"
        ).pack(side="left", padx=(0, 14))
        self.channel_frame = ttk.Frame(toolbar)
        self.channel_frame.pack(side="left")
        ttk.Checkbutton(
            toolbar,
            text="ROI",
            variable=self.roi_var,
            command=self._roi_changed,
        ).pack(side="right", padx=(8, 0))
        self.scale_combo = ttk.Combobox(
            toolbar,
            textvariable=self.scale_var,
            values=("Log", "Linear"),
            state="readonly",
            width=7,
        )
        self.scale_combo.pack(side="right")
        self.scale_combo.bind("<<ComboboxSelected>>", self._scale_changed)
        self.y_axis_label = ttk.Label(
            toolbar, text=self.tr("hist.axis")
        )
        self.y_axis_label.pack(side="right", padx=(8, 4))

        self.canvas = tk.Canvas(
            self,
            bg=COLORS["canvas_alt"],
            highlightthickness=0,
            height=260,
        )
        self.canvas.pack(fill="both", expand=True, padx=10)
        self.canvas.bind("<Configure>", lambda _event: self._redraw())
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", self._on_leave)

        footer = ttk.Frame(self, padding=(10, 7))
        footer.pack(fill="x")
        ttk.Label(
            footer, textvariable=self.summary_var, style="Muted.TLabel"
        ).pack(side="left")
        ttk.Label(
            footer, textvariable=self.hover_var, style="Muted.TLabel"
        ).pack(side="right")

    def _module_result_index(self) -> int:
        if not self.app.results:
            return 0
        if self.app.loaded.domain == "yuv":
            index = self.app.selected_module_index
        else:
            index = self.app.selected_module_index + 1
        return max(0, min(index, len(self.app.results) - 1))

    def _domain_for_result(self, result) -> str:
        if self.app.loaded.domain == "yuv":
            return "yuv"
        return "bayer" if result.domain == "bayer" else "rgb"

    def _rebuild_channels(self, domain: str) -> None:
        if domain == self.current_domain and self.channel_vars:
            return
        self.current_domain = domain
        for child in self.channel_frame.winfo_children():
            child.destroy()
        self.channel_vars = {}
        self.channel_buttons = {}
        for channel in DOMAIN_CHANNELS[domain]:
            variable = tk.BooleanVar(value=True)
            button = tk.Checkbutton(
                self.channel_frame,
                text=channel,
                variable=variable,
                command=lambda name=channel: self._channel_changed(name),
                bg=COLORS["panel"],
                fg=CHANNEL_COLORS[channel],
                activebackground=COLORS["panel"],
                activeforeground=CHANNEL_COLORS[channel],
                selectcolor=COLORS["panel_alt"],
                relief="flat",
                borderwidth=0,
                highlightthickness=0,
                font=FONTS["body"],
            )
            button.pack(side="left", padx=(0, 3))
            self.channel_vars[channel] = variable
            self.channel_buttons[channel] = button

    def _enabled_channels(self):
        return tuple(
            name for name, variable in self.channel_vars.items()
            if variable.get()
        )

    def _channel_changed(self, changed: str) -> None:
        if not self._enabled_channels():
            self.channel_vars[changed].set(True)
            self.summary_var.set(self.tr("hist.keep_channel"))
            return
        self.refresh(0)

    def _roi_changed(self) -> None:
        self.app.histogram_use_roi = bool(self.roi_var.get())
        self.refresh(0)

    def _scale_changed(self, _event=None) -> None:
        self.app.histogram_scale = self.scale_var.get()
        self._redraw()

    def refresh(self, delay: int = 180) -> None:
        if not self.winfo_exists():
            return
        self.generation += 1
        generation = self.generation
        if self.pending_after is not None:
            try:
                self.after_cancel(self.pending_after)
            except tk.TclError:
                pass
        self.pending_after = self.after(
            max(0, int(delay)), lambda: self._start(generation)
        )

    def _start(self, generation: int) -> None:
        self.pending_after = None
        if generation != self.generation or not self.app.results:
            return
        index = self._module_result_index()
        result = self.app.results[index]
        domain = self._domain_for_result(result)
        self._rebuild_channels(domain)
        channels = self._enabled_channels()
        roi = None
        if self.roi_var.get() and self.app.roi is not None:
            selected = self.app.roi
            roi = (selected.x, selected.y, selected.width, selected.height)
        key = (
            self.app.current_image_index,
            self.app.result_revision,
            self.app.input_revision,
            index,
            domain,
            roi,
            channels,
        )
        self.title_var.set(f"Histogram · {result.name}")
        cached = self.cache.get(key)
        if cached is not None:
            self._apply(generation, key, cached)
            return

        metadata = copy.deepcopy(self.app.loaded.metadata)
        if domain == "yuv":
            frame = self.app.loaded.yuv_frame
            conversion = self.app.loaded.yuv_conversion
            if frame is None or conversion is None:
                self.summary_var.set(self.tr("hist.waiting_yuv"))
                return
            args = (
                "yuv", frame, np.asarray(conversion.rgb, np.float32),
                metadata, False, roi, channels, None,
            )
        else:
            image = np.asarray(result.image, np.float32)
            if (
                roi is not None
                and not self.app.roi_process_var.get()
                and image.shape[:2] == self.app.preview_image.shape[:2]
            ):
                ys, xs = self.app.roi.slices()
                image = image[ys, xs]
            normalized = (
                self.app._bayer_stage_is_normalized(index)
                if domain == "bayer" else False
            )
            args = (
                domain, image, None, metadata, normalized, None, channels,
                result.data_state,
            )
        if self.future is not None and not self.future.done():
            self.future.cancel()
        self.summary_var.set(self.tr("hist.computing"))
        self.future = self.app.analysis_executor.submit(self._compute, *args)
        self._poll(self.future, generation, key)

    @staticmethod
    def _compute(
        domain, image_or_frame, rgb, metadata, normalized, roi, channels,
        data_state,
    ):
        started = time.perf_counter()
        if domain == "yuv":
            payload = compute_yuv_histogram_details(
                image_or_frame,
                rgb,
                mode="YUV 原始",
                roi=roi,
            )
        else:
            payload = compute_histogram_details(
                image_or_frame,
                domain,
                metadata,
                mode="RGB Overlay",
                bayer_normalized=normalized,
                data_state=data_state,
            )
        payload["curves"] = {
            key: value for key, value in payload["curves"].items()
            if key in channels
        }
        payload["curve_sizes"] = {
            key: value for key, value in payload["curve_sizes"].items()
            if key in channels
        }
        return payload, (time.perf_counter() - started) * 1000.0

    def _poll(self, future: Future, generation: int, key) -> None:
        if not self.winfo_exists():
            return
        if not future.done():
            callback_id = None

            def poll_again() -> None:
                self.poll_after_ids.discard(callback_id)
                self._poll(future, generation, key)

            callback_id = self.after(15, poll_again)
            self.poll_after_ids.add(callback_id)
            return
        if generation != self.generation or future.cancelled():
            return
        try:
            payload, elapsed_ms = future.result()
        except Exception as exc:
            self.summary_var.set(self.tr("hist.failed", error=exc))
            return
        payload["elapsed_ms"] = elapsed_ms
        self.cache[key] = payload
        while len(self.cache) > self.cache_limit:
            self.cache.pop(next(iter(self.cache)))
        self._apply(generation, key, payload)

    def _apply(self, generation: int, _key, payload) -> None:
        if generation != self.generation or not self.winfo_exists():
            return
        self.last_payload = payload
        self._redraw()

    def _redraw(self) -> None:
        payload = self.last_payload
        if payload is None or not self.winfo_exists():
            return
        self.canvas.delete("all")
        width = max(self.canvas.winfo_width(), 640)
        height = max(self.canvas.winfo_height(), 220)
        left, right = 48, width - 14
        top, bottom = 24, height - 30
        plot_width = max(1, right - left)
        plot_height = max(1, bottom - top)
        code_max = int(payload["code_max"])
        for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
            x = left + fraction * plot_width
            self.canvas.create_line(
                x, top, x, bottom, fill=COLORS["scope_grid"]
            )
            self.canvas.create_text(
                x, bottom + 5,
                text=str(int(round(code_max * fraction))),
                anchor="n", fill=COLORS["muted"], font=FONTS["small"],
            )
        self.canvas.create_line(
            left, bottom, right, bottom, fill=COLORS["border"]
        )
        markers = sorted({
            int(value)
            for limits in payload.get("legal_ranges", {}).values()
            for value in limits
        })
        for value in markers:
            x = left + value / max(code_max, 1) * plot_width
            self.canvas.create_line(
                x, top, x, bottom,
                fill=COLORS["warning"], dash=(3, 3),
            )
        transformed = {}
        for key, values in payload["curves"].items():
            values = np.asarray(values, np.float64)
            transformed[key] = (
                np.log1p(values) if self.scale_var.get() == "Log" else values
            )
        maximum = max(
            (float(values.max(initial=0.0)) for values in transformed.values()),
            default=1.0,
        )
        maximum = max(maximum, 1.0)
        for key, values in transformed.items():
            values = values / maximum
            points = []
            for index, value in enumerate(values):
                points.extend((
                    left + (index + 0.5) / len(values) * plot_width,
                    bottom - float(value) * plot_height,
                ))
            if len(points) >= 4:
                self.canvas.create_line(
                    *points,
                    fill=CHANNEL_COLORS[key],
                    width=2 if key in {"Y", "Gr", "Gb"} else 1,
                )
        legend = "  ".join(payload["curves"])
        self.canvas.create_text(
            left, 5,
            text=f"{legend}  ·  {self.scale_var.get()}  ·  0…{code_max}",
            anchor="nw", fill=COLORS["muted"], font=FONTS["small"],
        )
        stats = payload["stats"]
        summary = self.tr(
            "hist.summary",
            dark=stats["dark_ratio"] * 100,
            highlight=stats["highlight_ratio"] * 100,
            minimum=stats["minimum"],
            maximum=stats["maximum"],
        )
        if stats["underflow_ratio"] or stats["overflow_ratio"]:
            summary += (
                f" · <0 {stats['underflow_ratio'] * 100:.2f}%"
                f" · >{code_max} {stats['overflow_ratio'] * 100:.2f}%"
            )
        if markers:
            summary += " · " + self.tr("hist.legal")
        if self.roi_var.get():
            summary += (
                " · ROI"
                if self.app.roi is not None
                else " · " + self.tr("hist.roi_missing")
            )
        summary += f" · {payload.get('elapsed_ms', 0.0):.1f} ms"
        self.summary_var.set(summary)
        self.plot_bounds = (left, top, right, bottom)

    def _on_motion(self, event) -> None:
        payload = self.last_payload
        if payload is None or self.plot_bounds is None:
            return
        left, top, right, bottom = self.plot_bounds
        if not (left <= event.x <= right and top <= event.y <= bottom):
            self._on_leave()
            return
        edges = np.asarray(payload["bin_edges"], np.float32)
        bins = len(edges) - 1
        index = min(
            bins - 1,
            max(0, int((event.x - left) / max(right - left, 1) * bins)),
        )
        values = []
        for key, counts in payload["curves"].items():
            count = int(counts[index])
            total = max(1, int(payload["curve_sizes"].get(key, 0)))
            values.append(f"{key} {count:,} ({count / total * 100:.2f}%)")
        self.hover_var.set(
            self.tr(
                "hist.code_range",
                low=edges[index],
                high=edges[index + 1],
            ) + " · "
            + " · ".join(values)
        )
        self.canvas.delete("hist_cursor")
        self.canvas.create_line(
            event.x, top, event.x, bottom,
            fill=COLORS["foreground"], dash=(2, 2), tags="hist_cursor",
        )

    def _on_leave(self, _event=None) -> None:
        self.canvas.delete("hist_cursor")
        self.hover_var.set("")

    def close(self) -> None:
        if not self.winfo_exists():
            return
        self.generation += 1
        if self.pending_after is not None:
            try:
                self.after_cancel(self.pending_after)
            except tk.TclError:
                pass
            self.pending_after = None
        for callback_id in tuple(self.poll_after_ids):
            try:
                self.after_cancel(callback_id)
            except tk.TclError:
                pass
        self.poll_after_ids.clear()
        if self.future is not None and not self.future.done():
            self.future.cancel()
        self.app.histogram_window_geometry = self.geometry()
        self.app.histogram_scale = self.scale_var.get()
        self.app.histogram_use_roi = bool(self.roi_var.get())
        self.app.histogram_window = None
        if hasattr(self.app, "histogram_button"):
            self.app.histogram_button.configure(style="Secondary.TButton")
        self.destroy()
