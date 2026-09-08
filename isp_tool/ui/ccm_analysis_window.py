from __future__ import annotations

import math
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

import cv2
import numpy as np
from PIL import Image, ImageTk

from ..calibration.ccm_analysis import lab_errors
from .theme import COLORS, FONTS


class CCMAnalysisWindow(tk.Toplevel):
    """Compact corrected-only chart analysis; opening never executes ISP."""

    def __init__(self, parent, *, on_patch_selected=None, on_toggle_patch=None):
        super().__init__(parent)
        self.title("Color Analysis · CCM")
        self.geometry("1400x820")
        self.minsize(980, 600)
        self.configure(background=COLORS["panel"])
        self.transient(parent)
        self.on_patch_selected = on_patch_selected
        self.on_toggle_patch = on_toggle_patch
        self.measurements = {}
        self.patch_rows = []
        self.selected_patch_id = 0
        self.summary_var = tk.StringVar(value="")
        self.patch_detail_var = tk.StringVar(value="")
        self._draw_after_id = None
        self._background_key = None
        self._background_photo = None
        self._result_source = None
        self._sash_positioned = False
        self._last_notified = None
        self._configure_styles()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.withdraw)

    def _configure_styles(self):
        style = ttk.Style(self)
        try:
            self.body_font = tkfont.Font(root=self, name=FONTS["body"], exists=True)
        except tk.TclError:
            self.body_font = tkfont.Font(root=self, name="TkDefaultFont", exists=True)
        style.configure(
            "CCMAnalysis.Treeview", background=COLORS["panel_alt"],
            fieldbackground=COLORS["panel_alt"], foreground=COLORS["foreground"],
            font=self.body_font, rowheight=max(30, self.body_font.metrics("linespace") + 10),
        )
        style.configure(
            "CCMAnalysis.Treeview.Heading", background=COLORS["panel"],
            foreground=COLORS["foreground"], font=self.body_font, padding=(4, 7),
        )
        style.map("CCMAnalysis.Treeview", background=[("selected", COLORS["selection"])],
                  foreground=[("selected", "white")])

    def _build(self):
        ttk.Label(self, text="ColorChecker 24 · Corrected", style="Title.TLabel",
                  padding=(12, 8)).pack(anchor="w")
        self.summary_label = ttk.Label(self, textvariable=self.summary_var,
                                      padding=(12, 0, 12, 8), justify="left")
        self.summary_label.pack(fill="x")
        self.summary_label.bind("<Configure>", self._wrap_summary)
        self.panes = ttk.Panedwindow(self, orient="horizontal")
        self.panes.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        table_frame = ttk.Frame(self.panes)
        plot_frame = ttk.Frame(self.panes)
        self.panes.add(table_frame, weight=1)
        self.panes.add(plot_frame, weight=1)
        self.panes.bind("<Configure>", self._position_initial_sash)
        columns = ("id", "deab", "dcab", "dl", "dc", "dh", "da", "db")
        labels = ("#", "DEab", "DCab", "DL", "DC", "Dh (°)", "Da", "Db")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings",
                                 style="CCMAnalysis.Treeview", selectmode="browse")
        for column, label in zip(columns, labels):
            width = max(65, self.body_font.measure("-123.45") + 20) if column != "id" else 45
            self.tree.column(column, width=width, minwidth=width, stretch=False, anchor="center")
            self.tree.heading(column, text=label, command=lambda c=column: self._sort_by(c))
        self.tree.tag_configure("excluded", foreground=COLORS["muted"])
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(table_frame, command=self.tree.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", self._tree_selected)
        self.detail_label = ttk.Label(table_frame, textvariable=self.patch_detail_var,
                                     justify="left", padding=(0, 8), wraplength=550)
        self.detail_label.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.ab_canvas = tk.Canvas(plot_frame, bg="#dddddd", highlightthickness=0)
        self.ab_canvas.pack(fill="both", expand=True)
        self.ab_canvas.bind("<Configure>", lambda e: self._request_draw())
        self.ab_canvas.bind("<Button-1>", self._plot_clicked)
        ttk.Label(self, text=(
            "DEab = √(DL²+Da²+Db²)   DCab = √(Da²+Db²)   DC = C_out − C_ref\n"
            "DL / Da / Db = Output Lab − Standard Lab   Dh = shortest hue angle (°); "
            "— = low chroma / unavailable   * = excluded from fit\n"
            "Plot background: Lab L*=70, D65 → clipped sRGB (visual guide)"
        ), style="Muted.TLabel", padding=(12, 0, 12, 10), justify="left").pack(anchor="w")

    def _wrap_summary(self, event):
        width = max(300, event.width - 24)
        if int(float(self.summary_label.cget("wraplength") or 0)) != width:
            self.summary_label.configure(wraplength=width)

    @staticmethod
    def _number(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return float("nan")

    @classmethod
    def _format_number(cls, value):
        value = cls._number(value)
        return f"{value:.2f}" if math.isfinite(value) else "—"

    def set_result(self, measurements):
        if measurements is self._result_source:
            return
        self._result_source = measurements
        self.measurements = measurements or {}
        self.patch_rows = list(self.measurements.get("patches", []) or [])
        self.selected_patch_id = 0
        self._last_notified = None
        self.tree.delete(*self.tree.get_children())
        metrics = []
        for patch in self.patch_rows:
            d = patch.get("diagnostics", {})
            lab, target = d.get("corrected_lab"), d.get("reference_lab")
            errors = None
            if lab is not None and target is not None:
                errors = lab_errors(lab, target)
            valid = d.get("valid", True)
            if errors is not None and valid:
                metrics.append(errors)
            patch_id = int(patch["patch_id"])
            values = [str(patch_id) + ("" if valid else "*")]
            values += [self._format_number(errors[k] if errors is not None else None)
                       for k in ("deab", "dcab", "dl", "dc", "dh", "da", "db")]
            self.tree.insert("", "end", iid=f"patch-{patch_id}", values=values,
                             tags=() if valid else ("excluded",))
        parts = []
        for key, label in (("deab", "DEab"), ("dcab", "DCab"), ("dl", "|DL|"),
                           ("dc", "|DC|"), ("dh", "|Dh|°")):
            values = np.array([float(m[key]) for m in metrics])
            values = np.abs(values[np.isfinite(values)])
            parts.append(f"{label} {np.mean(values):.2f}" if values.size else f"{label} —")
        self.summary_var.set("Mean · " + "   ·   ".join(parts))
        self.patch_detail_var.set("Select a patch to inspect Output / Standard Lab.")
        self._request_draw()

    def _sort_by(self, column):
        def key(item):
            value = self.tree.set(item, column).rstrip("*")
            numeric = self._number(value)
            return (0, numeric) if math.isfinite(numeric) else (1, value)
        for i, item in enumerate(sorted(self.tree.get_children(), key=key)):
            self.tree.move(item, "", i)

    def _tree_selected(self, _event=None):
        selection = self.tree.selection()
        if selection:
            self.focus_patch(int(selection[0].split("-")[-1]), notify=True)

    def focus_patch(self, patch_id, notify=False):
        patch_id = int(patch_id)
        changed = patch_id != self.selected_patch_id
        self.selected_patch_id = patch_id
        iid = f"patch-{patch_id}"
        if self.tree.exists(iid) and self.tree.selection() != (iid,):
            self.tree.selection_set(iid)
            self.tree.see(iid)
        if changed:
            patch = next((p for p in self.patch_rows if int(p["patch_id"]) == patch_id), None)
            if patch:
                d = patch.get("diagnostics", {})
                fmt = lambda v: " / ".join(self._format_number(x) for x in v) if v is not None else "—"
                self.patch_detail_var.set(
                    f"#{patch_id} · {patch.get('name', '')}\n"
                    f"Output Lab:   {fmt(d.get('corrected_lab'))}\n"
                    f"Standard Lab: {fmt(d.get('reference_lab'))}"
                )
            self._request_draw()
        if notify and patch_id != self._last_notified:
            self._last_notified = patch_id
            if self.on_patch_selected:
                self.on_patch_selected(patch_id)

    def _toggle_selected(self):
        if self.selected_patch_id and self.on_toggle_patch:
            self.on_toggle_patch(self.selected_patch_id)

    def _plot_points(self):
        points = []
        for patch in self.patch_rows:
            d = patch.get("diagnostics", {})
            for role, key in (("target", "reference_lab"), ("after", "corrected_lab")):
                lab = d.get(key)
                if lab is not None and len(lab) == 3 and np.all(np.isfinite(lab)):
                    points.append((int(patch["patch_id"]), role, float(lab[1]), float(lab[2])))
        return points

    def _draw_ab(self):
        self._draw_after_id = None
        c = self.ab_canvas
        c.delete("all")
        width, height = c.winfo_width(), c.winfo_height()
        if width < 100 or height < 100:
            return
        points = self._plot_points()
        # Fixed default axes aid comparison between corrections. Expand for
        # valid outlying values, while keeping equal distance per Lab unit.
        amin, amax, bmin, bmax = -70., 85., -75., 110.
        if points:
            amin = min(amin, min(p[2] for p in points) - 8)
            amax = max(amax, max(p[2] for p in points) + 8)
            bmin = min(bmin, min(p[3] for p in points) - 8)
            bmax = max(bmax, max(p[3] for p in points) + 8)
        scale = min((width - 76) / (amax - amin), (height - 75) / (bmax - bmin))
        pw, ph = max(1, int((amax-amin)*scale)), max(1, int((bmax-bmin)*scale))
        left, top = (width-pw)/2, 30
        transform = lambda a, b: (left+(a-amin)*scale, top+(bmax-b)*scale)
        key = (pw, ph, amin, amax, bmin, bmax)
        if self._background_key != key:
            # Bounded raster, independent of source RAW resolution.
            aa, bb = np.meshgrid(np.linspace(amin, amax, 240), np.linspace(bmax, bmin, 280))
            lab = np.stack((np.full_like(aa, 70), aa, bb), axis=-1).astype(np.float32)
            rgb = cv2.cvtColor(lab, cv2.COLOR_Lab2RGB)
            raster = Image.fromarray(np.uint8(np.clip(rgb, 0, 1)*255))
            self._background_photo = ImageTk.PhotoImage(raster.resize((pw, ph), Image.Resampling.BILINEAR), master=self)
            self._background_key = key
        c.create_image(left, top, image=self._background_photo, anchor="nw")
        c.create_rectangle(left, top, left+pw, top+ph, outline="#303030")
        for a in np.arange(math.ceil(amin/20)*20, amax, 20):
            x, y = transform(a, 0)
            c.create_line(x, top, x, top+ph, fill="#b6b6b6", dash=(2, 6))
            c.create_text(x, top+ph+15, text=f"{a:g}", fill="#252525")
        for b in np.arange(math.ceil(bmin/20)*20, bmax, 20):
            x, y = transform(0, b)
            c.create_line(left, y, left+pw, y, fill="#b6b6b6", dash=(2, 6))
            c.create_text(left-8, y, text=f"{b:g}", anchor="e", fill="#252525")
        c.create_text(left+pw/2, top+ph+38, text="a*", fill="#252525")
        c.create_text(left-34, top+ph/2, text="b*", fill="#252525")
        c.create_text(left+10, top+13, text="■ Standard    ● Output", anchor="w", fill="#202020")
        self._canvas_patch_points = []
        for patch in self.patch_rows:
            d = patch.get("diagnostics", {})
            target, output = d.get("reference_lab"), d.get("corrected_lab")
            if target is None or output is None or not np.all(np.isfinite([target, output])):
                continue
            patch_id = int(patch["patch_id"])
            tx, ty = transform(*target[1:3])
            ox, oy = transform(*output[1:3])
            c.create_line(tx, ty, ox, oy, fill="#303030", width=1.5)
            selected = patch_id == self.selected_patch_id
            for lab, x, y, circle in ((target, tx, ty, False), (output, ox, oy, True)):
                rgb = cv2.cvtColor(np.array([[lab]], np.float32), cv2.COLOR_Lab2RGB)[0, 0]
                color = "#%02x%02x%02x" % tuple(np.uint8(np.clip(rgb, 0, 1)*255))
                radius = (7 if circle else 4) + (2 if selected else 0)
                draw = c.create_oval if circle else c.create_rectangle
                draw(x-radius, y-radius, x+radius, y+radius, fill=color,
                     outline="#111111", width=2 if selected else 1)
                self._canvas_patch_points.append((patch_id, x, y))
            if patch_id <= 18 or selected:
                c.create_text(tx+7, ty+9, text=str(patch_id), anchor="nw", fill="#303030")

    def _plot_clicked(self, event):
        points = getattr(self, "_canvas_patch_points", [])
        if not points:
            return
        patch_id, x, y = min(points, key=lambda p: (p[1]-event.x)**2+(p[2]-event.y)**2)
        if (x-event.x)**2+(y-event.y)**2 <= 225:
            self.focus_patch(patch_id, notify=True)

    def _request_draw(self):
        if self._draw_after_id is None and self.winfo_exists():
            self._draw_after_id = self.after(24, self._draw_ab)

    def _position_initial_sash(self, _event=None):
        width = self.panes.winfo_width()
        if width > 800 and not self._sash_positioned:
            self._sash_positioned = True
            self.panes.sashpos(0, int(width * 0.50))

    def destroy(self):
        if self._draw_after_id is not None:
            self.after_cancel(self._draw_after_id)
            self._draw_after_id = None
        super().destroy()
