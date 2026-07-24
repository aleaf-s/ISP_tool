from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Sequence

import numpy as np
from PIL import Image, ImageTk

from ..calibration.colorchecker import generate_colorchecker_grid
from .theme import FONTS


class ColorCheckerCornerEditor(tk.Toplevel):
    def __init__(
        self,
        parent,
        linear_rgb: np.ndarray,
        corners: Sequence[Sequence[float]],
        rotation: int,
        on_apply: Callable,
    ):
        super().__init__(parent)
        self.title("ColorChecker Corner Editor")
        self.geometry("980x700")
        self.transient(parent)
        self.image = np.asarray(linear_rgb, dtype=np.float32)
        self.corners = np.asarray(corners, dtype=np.float64)
        self.rotation = int(rotation)
        self.on_apply = on_apply
        self.photo = None
        self.active_corner = None
        self.scale = 1.0
        self.origin = (0.0, 0.0)
        self._build()

    def _build(self):
        toolbar = ttk.Frame(self, padding=8)
        toolbar.pack(fill="x")
        ttk.Label(
            toolbar,
            text="拖动 TL / TR / BR / BL，使外框贴合色卡边界",
        ).pack(side="left")
        ttk.Button(toolbar, text="Apply", command=self._apply).pack(side="right")
        ttk.Button(toolbar, text="Cancel", command=self.destroy).pack(side="right", padx=5)
        self.canvas = tk.Canvas(self, bg="#080b0f", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _event: self._draw())
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", lambda _event: setattr(self, "active_corner", None))

    def _draw(self):
        canvas_w = max(self.canvas.winfo_width(), 50)
        canvas_h = max(self.canvas.winfo_height(), 50)
        image_h, image_w = self.image.shape[:2]
        self.scale = min(canvas_w / image_w, canvas_h / image_h)
        target_w, target_h = int(image_w * self.scale), int(image_h * self.scale)
        self.origin = ((canvas_w - target_w) / 2, (canvas_h - target_h) / 2)
        display = np.power(np.clip(self.image, 0, 1), 1 / 2.2)
        pil = Image.fromarray(np.round(display * 255).astype(np.uint8), "RGB")
        pil = pil.resize((target_w, target_h), Image.Resampling.LANCZOS)
        self.photo = ImageTk.PhotoImage(pil)
        self.canvas.delete("all")
        self.canvas.create_image(*self.origin, image=self.photo, anchor="nw")
        columns, rows = ((4, 6) if self.rotation in {90, 270} else (6, 4))
        polygons = generate_colorchecker_grid(
            self.corners, columns=columns, rows=rows, inner_scale=0.88
        )
        for index, polygon in enumerate(polygons):
            points = []
            for x, y in polygon:
                points.extend(self._image_to_canvas(x, y))
            self.canvas.create_polygon(
                *points, outline="#54f0c0", fill="", width=1
            )
        labels = ("TL", "TR", "BR", "BL")
        for index, ((x, y), label) in enumerate(zip(self.corners, labels)):
            cx, cy = self._image_to_canvas(x, y)
            self.canvas.create_oval(
                cx - 7, cy - 7, cx + 7, cy + 7,
                fill="#ffd84d", outline="black", width=1,
            )
            self.canvas.create_text(
                cx + 10, cy - 10, text=label, anchor="sw",
                fill="#ffd84d", font=FONTS["section"],
            )

    def _image_to_canvas(self, x, y):
        return (
            self.origin[0] + x * self.scale,
            self.origin[1] + y * self.scale,
        )

    def _canvas_to_image(self, x, y):
        image_h, image_w = self.image.shape[:2]
        ix = np.clip((x - self.origin[0]) / max(self.scale, 1e-8), 0, image_w - 1)
        iy = np.clip((y - self.origin[1]) / max(self.scale, 1e-8), 0, image_h - 1)
        return np.array([ix, iy], np.float64)

    def _press(self, event):
        canvas_points = np.array([
            self._image_to_canvas(x, y) for x, y in self.corners
        ])
        distance = np.linalg.norm(canvas_points - [event.x, event.y], axis=1)
        index = int(np.argmin(distance))
        if distance[index] <= 18:
            self.active_corner = index

    def _drag(self, event):
        if self.active_corner is None:
            return
        self.corners[self.active_corner] = self._canvas_to_image(event.x, event.y)
        self._draw()

    def _apply(self):
        self.on_apply([tuple(map(float, point)) for point in self.corners])
        self.destroy()
