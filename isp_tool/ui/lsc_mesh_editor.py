from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

import cv2
import numpy as np
from PIL import Image, ImageTk

from ..calibration.lsc_mesh import normalize_mesh_center
from ..models import LSCMesh
from .theme import FONTS


class LSCMeshEditor(tk.Toplevel):
    def __init__(self, parent, mesh: LSCMesh, on_apply: Callable[[LSCMesh], None]):
        super().__init__(parent)
        self.title(f"LSC Mesh Editor · {mesh.rows}×{mesh.cols}")
        self.geometry("820x620")
        self.transient(parent)
        self.mesh = mesh.copy()
        self.on_apply = on_apply
        self.channel_var = tk.StringVar(value="R")
        self.photo = None
        self._build()
        self._load_channel()

    def _build(self):
        toolbar = ttk.Frame(self, padding=8)
        toolbar.pack(fill="x")
        ttk.Label(toolbar, text="Channel:").pack(side="left")
        combo = ttk.Combobox(
            toolbar, textvariable=self.channel_var,
            values=("R", "Gr", "Gb", "B"), state="readonly", width=7,
        )
        combo.pack(side="left", padx=5)
        combo.bind("<<ComboboxSelected>>", lambda _event: self._load_channel())
        ttk.Button(
            toolbar, text="Normalize Center", command=self._normalize
        ).pack(side="left", padx=8)
        ttk.Button(toolbar, text="Apply", command=self._apply).pack(side="right")
        ttk.Button(toolbar, text="Cancel", command=self.destroy).pack(side="right", padx=5)

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        text_frame = ttk.Frame(body)
        preview_frame = ttk.Frame(body)
        body.add(text_frame, weight=1)
        body.add(preview_frame, weight=1)
        ttk.Label(
            text_frame,
            text="每行一个 Mesh 行，数值使用空格、逗号或 Tab 分隔",
        ).pack(anchor="w")
        self.text = tk.Text(
            text_frame, bg="#11151b", fg="#e5e9ef", insertbackground="white",
            font=FONTS["mono"], wrap="none",
        )
        self.text.pack(fill="both", expand=True, pady=(5, 0))
        ttk.Button(
            text_frame, text="Update Channel", command=self._update_channel
        ).pack(fill="x", pady=(5, 0))
        self.canvas = tk.Canvas(
            preview_frame, bg="#080b0f", highlightthickness=0
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _event: self._draw_heatmap())

    def _channel_array(self):
        return self.mesh.channels()[self.channel_var.get()]

    def _load_channel(self):
        array = self._channel_array()
        self.text.delete("1.0", "end")
        self.text.insert(
            "1.0",
            "\n".join(" ".join(f"{value:.7g}" for value in row) for row in array),
        )
        self._draw_heatmap()

    def _parse_text(self):
        rows = []
        for line in self.text.get("1.0", "end").strip().splitlines():
            tokens = line.replace(",", " ").split()
            if tokens:
                rows.append([float(token) for token in tokens])
        array = np.asarray(rows, dtype=np.float32)
        if array.shape != (self.mesh.rows, self.mesh.cols):
            raise ValueError(
                f"需要 {self.mesh.rows}×{self.mesh.cols}，实际 {array.shape}"
            )
        if not np.all(np.isfinite(array)) or np.any(array <= 0):
            raise ValueError("Mesh 必须全部为正的有限数值")
        return array

    def _update_channel(self):
        try:
            array = self._parse_text()
        except Exception as exc:
            messagebox.showerror("Mesh 编辑错误", str(exc), parent=self)
            return False
        key = self.channel_var.get().lower()
        setattr(self.mesh, key, array)
        self._draw_heatmap()
        return True

    def _normalize(self):
        if not self._update_channel():
            return
        self.mesh = normalize_mesh_center(self.mesh)
        self._load_channel()

    def _draw_heatmap(self):
        if not self.winfo_exists():
            return
        array = self._channel_array()
        low, high = float(array.min()), float(array.max())
        normalized = (array - low) / max(high - low, 1e-8)
        colored = cv2.applyColorMap(
            np.round(normalized * 255).astype(np.uint8), cv2.COLORMAP_TURBO
        )
        colored = cv2.cvtColor(colored, cv2.COLOR_BGR2RGB)
        width = max(self.canvas.winfo_width(), 200)
        height = max(self.canvas.winfo_height(), 200)
        image = Image.fromarray(colored).resize(
            (width, height), Image.Resampling.NEAREST
        )
        self.photo = ImageTk.PhotoImage(image)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
        self.canvas.create_text(
            8, 8,
            text=f"{self.channel_var.get()}  min {low:.4f}  max {high:.4f}",
            anchor="nw", fill="white", font=FONTS["section"],
        )

    def _apply(self):
        if not self._update_channel():
            return
        try:
            self.mesh.validate()
            self.on_apply(self.mesh.copy())
        except Exception as exc:
            messagebox.showerror("Mesh 无效", str(exc), parent=self)
            return
        self.destroy()
