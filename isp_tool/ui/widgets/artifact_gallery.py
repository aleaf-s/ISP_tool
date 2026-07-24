from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Dict, Optional

import cv2
import numpy as np
from PIL import Image, ImageTk

from ...preview import artifact_to_rgb
from ..theme import ARTIFACT_RGB, COLORS
from .action_menu import ActionMenu


def artifact_to_display_rgb(name: str, value: np.ndarray) -> np.ndarray:
    array = np.asarray(value)
    if array.ndim == 1:
        array = array[:, None]
    if array.ndim == 3 and array.shape[2] >= 3:
        rgb = array[:, :, :3].astype(np.float32)
        low = float(np.nanmin(rgb)) if rgb.size else 0.0
        high = float(np.nanmax(rgb)) if rgb.size else 1.0
        if low < 0.0 or high > 1.0:
            rgb = (rgb - low) / max(high - low, 1e-8)
        return np.clip(rgb, 0.0, 1.0)
    scalar = array.astype(np.float32)
    lower_name = name.lower()
    if "hot" in lower_name:
        rgb = np.zeros((*scalar.shape[:2], 3), np.float32)
        rgb[scalar > 0] = ARTIFACT_RGB["hot"]
        return rgb
    if "dead" in lower_name or "dark pixel" in lower_name:
        rgb = np.zeros((*scalar.shape[:2], 3), np.float32)
        rgb[scalar > 0] = ARTIFACT_RGB["dead"]
        return rgb
    if "candidate" in lower_name:
        rgb = np.zeros((*scalar.shape[:2], 3), np.float32)
        rgb[scalar > 0] = ARTIFACT_RGB["candidate"]
        return rgb
    if "accepted" in lower_name:
        rgb = np.zeros((*scalar.shape[:2], 3), np.float32)
        rgb[scalar > 0] = ARTIFACT_RGB["accepted"]
        return rgb
    if "rejected" in lower_name:
        rgb = np.zeros((*scalar.shape[:2], 3), np.float32)
        rgb[scalar > 0] = ARTIFACT_RGB["rejected"]
        return rgb
    if "overexposure" in lower_name or "overexposed" in lower_name:
        rgb = np.zeros((*scalar.shape[:2], 3), np.float32)
        rgb[scalar > 0] = ARTIFACT_RGB["overexposure"]
        return rgb
    if "underexposure" in lower_name or "underexposed" in lower_name:
        rgb = np.zeros((*scalar.shape[:2], 3), np.float32)
        rgb[scalar > 0] = ARTIFACT_RGB["underexposure"]
        return rgb
    return artifact_to_rgb(name, scalar)


class ArtifactGallery(ttk.Frame):
    MODES = (
        "Main Image", "Artifact", "Overlay",
        "Side by Side", "Flicker Compare",
    )

    def __init__(self, parent):
        super().__init__(parent)
        self.artifacts: Dict[str, np.ndarray] = {}
        self.base_image: Optional[np.ndarray] = None
        self.selected = ""
        self.photos: Dict[str, ImageTk.PhotoImage] = {}
        self.preview_photo: Optional[ImageTk.PhotoImage] = None
        self.fit = True
        self.flicker = False
        self.flicker_after_id: Optional[str] = None
        self._build()

    def _build(self) -> None:
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x")
        self.mode_var = tk.StringVar(value="Artifact")
        mode = ttk.Combobox(
            toolbar, textvariable=self.mode_var, values=self.MODES,
            state="readonly", width=16,
        )
        mode.pack(side="left")
        mode.bind("<<ComboboxSelected>>", lambda _event: self.render())
        self.opacity_var = tk.DoubleVar(value=0.65)
        ttk.Label(toolbar, text="Opacity").pack(side="left", padx=(8, 3))
        ttk.Scale(
            toolbar, from_=0.0, to=1.0, variable=self.opacity_var,
            command=lambda _value: self.render(),
        ).pack(side="left", fill="x", expand=True)
        ttk.Button(toolbar, text="Fit", command=self._fit).pack(side="left", padx=4)
        ttk.Button(toolbar, text="1:1", command=self._actual).pack(side="left")

        thumbnail_shell = ttk.Frame(self)
        thumbnail_shell.pack(fill="x", pady=(5, 0))
        self.thumbnail_canvas = tk.Canvas(
            thumbnail_shell,
            bg=COLORS["panel"],
            height=82,
            highlightthickness=0,
        )
        thumbnail_scrollbar = ttk.Scrollbar(
            thumbnail_shell,
            orient="horizontal",
            command=self.thumbnail_canvas.xview,
        )
        self.thumbnail_canvas.configure(
            xscrollcommand=thumbnail_scrollbar.set
        )
        self.thumbnail_canvas.pack(fill="x", expand=True)
        thumbnail_scrollbar.pack(fill="x")
        self.thumbnail_frame = ttk.Frame(self.thumbnail_canvas)
        self.thumbnail_window = self.thumbnail_canvas.create_window(
            (0, 0), window=self.thumbnail_frame, anchor="nw"
        )
        self.thumbnail_frame.bind(
            "<Configure>",
            lambda _event: self.thumbnail_canvas.configure(
                scrollregion=self.thumbnail_canvas.bbox("all")
            ),
        )
        self.canvas = tk.Canvas(
            self, bg=COLORS["canvas"], highlightthickness=1,
            highlightbackground=COLORS["border"], height=260,
        )
        self.canvas.pack(fill="both", expand=True, pady=(5, 0))
        self.canvas.bind("<Configure>", lambda _event: self.render())
        exports = ttk.Frame(self)
        exports.pack(fill="x", pady=(4, 0))
        export_menu = ActionMenu(exports, "Export")
        export_menu.add_command(
            "Current artifact…", self.export_current,
            enabled=lambda: self.selected in self.artifacts,
        )
        export_menu.add_command(
            "All artifacts (NPZ)…", self.export_all,
            enabled=lambda: bool(self.artifacts),
        )
        export_menu.pack(side="left")
        self.info_var = tk.StringVar(value="No artifact")
        ttk.Label(exports, textvariable=self.info_var, style="Muted.TLabel").pack(
            side="right"
        )

    def set_artifacts(
        self,
        artifacts: Dict[str, np.ndarray],
        base_image: Optional[np.ndarray] = None,
    ) -> None:
        self.artifacts = {
            str(name): np.asarray(value) for name, value in artifacts.items()
        }
        self.base_image = (
            None if base_image is None else np.asarray(base_image, np.float32)
        )
        for child in self.thumbnail_frame.winfo_children():
            child.destroy()
        self.photos = {}
        for index, (name, value) in enumerate(self.artifacts.items()):
            rgb = artifact_to_display_rgb(name, value)
            image = Image.fromarray(
                np.round(np.clip(rgb, 0, 1) * 255).astype(np.uint8)
            )
            image.thumbnail((86, 54), Image.Resampling.NEAREST)
            photo = ImageTk.PhotoImage(image)
            self.photos[name] = photo
            button = ttk.Button(
                self.thumbnail_frame, text=name, image=photo,
                compound="top", command=lambda key=name: self.select(key),
                width=14,
            )
            button.grid(row=0, column=index, padx=2, pady=2, sticky="ew")
        self.selected = next(iter(self.artifacts), "")
        self.render()

    def select(self, name: str) -> None:
        if name in self.artifacts:
            self.selected = name
            self.render()

    def current_rgb(self) -> Optional[np.ndarray]:
        mode = self.mode_var.get()
        base = self.base_image
        if mode == "Main Image" and base is not None and base.ndim == 3:
            return np.clip(base[:, :, :3], 0.0, 1.0)
        if self.selected not in self.artifacts:
            return None
        artifact = artifact_to_display_rgb(
            self.selected, self.artifacts[self.selected]
        )
        if base is None or base.ndim != 3:
            return artifact
        if base.shape[:2] != artifact.shape[:2]:
            base = cv2.resize(base[:, :, :3], (artifact.shape[1], artifact.shape[0]))
        base = np.clip(base[:, :, :3], 0.0, 1.0)
        if mode == "Main Image":
            return base
        if mode == "Overlay":
            alpha = float(self.opacity_var.get())
            mask = np.any(artifact > 0.02, axis=2, keepdims=True)
            return np.where(mask, base * (1.0 - alpha) + artifact * alpha, base)
        if mode == "Side by Side":
            return np.concatenate([base, artifact], axis=1)
        if mode == "Flicker Compare":
            return base if self.flicker else artifact
        return artifact

    def render(self) -> None:
        if self.flicker_after_id is not None:
            try:
                self.after_cancel(self.flicker_after_id)
            except tk.TclError:
                pass
            self.flicker_after_id = None
        self.canvas.delete("all")
        rgb = self.current_rgb()
        if rgb is None:
            self.info_var.set("No artifact")
            return
        image = Image.fromarray(
            np.round(np.clip(rgb, 0, 1) * 255).astype(np.uint8)
        )
        width = max(self.canvas.winfo_width(), 100)
        height = max(self.canvas.winfo_height(), 100)
        if self.fit:
            scale = min(width / image.width, height / image.height)
            image = image.resize(
                (max(1, int(image.width * scale)), max(1, int(image.height * scale))),
                Image.Resampling.NEAREST,
            )
        self.preview_photo = ImageTk.PhotoImage(image)
        self.canvas.create_image(
            width // 2, height // 2, image=self.preview_photo, anchor="center"
        )
        value = self.artifacts[self.selected]
        self.info_var.set(f"{self.selected} · {tuple(value.shape)} · {value.dtype}")
        if self.mode_var.get() == "Flicker Compare":
            self.flicker = not self.flicker
            self.flicker_after_id = self.after(450, self.render)

    def _fit(self) -> None:
        self.fit = True
        self.render()

    def _actual(self) -> None:
        self.fit = False
        self.render()

    def export_current(self) -> None:
        if self.selected not in self.artifacts:
            return
        path = filedialog.asksaveasfilename(
            parent=self, defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("NumPy", "*.npy")],
        )
        if not path:
            return
        if Path(path).suffix.lower() == ".npy":
            np.save(path, self.artifacts[self.selected])
        else:
            rgb = artifact_to_display_rgb(
                self.selected, self.artifacts[self.selected]
            )
            bgr = cv2.cvtColor(
                np.round(np.clip(rgb, 0, 1) * 255).astype(np.uint8),
                cv2.COLOR_RGB2BGR,
            )
            cv2.imwrite(path, bgr)

    def export_all(self) -> None:
        if not self.artifacts:
            return
        path = filedialog.asksaveasfilename(
            parent=self, defaultextension=".npz",
            filetypes=[("NPZ", "*.npz")],
        )
        if path:
            np.savez_compressed(path, **self.artifacts)

    def destroy(self) -> None:
        if self.flicker_after_id is not None:
            try:
                self.after_cancel(self.flicker_after_id)
            except tk.TclError:
                pass
            self.flicker_after_id = None
        super().destroy()
