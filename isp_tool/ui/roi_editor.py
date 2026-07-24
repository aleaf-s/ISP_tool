from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, List

from ..models import ImageROI
from ..roi_tools import clamp_roi, generate_grid_rois


class ROIEditor(tk.Toplevel):
    """Manage up to 24 sampling rectangles with exact coordinate editing."""

    MAX_ROIS = 24

    def __init__(
        self,
        parent,
        rois: List[ImageROI],
        active_index: int,
        image_shape,
        bayer_aligned: bool,
        on_change: Callable[[List[ImageROI], int], None],
    ):
        super().__init__(parent)
        self.title("ROI 管理与微调")
        self.geometry("640x480")
        self.minsize(560, 420)
        self.transient(parent)
        self.rois = list(rois)
        self.active_index = active_index
        self.image_shape = image_shape
        self.bayer_aligned = bayer_aligned
        self.on_change = on_change
        self.vars = {
            key: tk.StringVar()
            for key in ("x", "y", "width", "height")
        }
        self._build()
        self._refresh()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _build(self) -> None:
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        ttk.Label(
            body,
            text="ROI LIST · 最多 24 个框",
            style="Title.TLabel",
        ).pack(anchor="w")
        ttk.Label(
            body,
            text="可精确输入坐标，也可用 ±1 / ±2 微调位置和尺寸。",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(2, 8))

        self.tree = ttk.Treeview(
            body,
            columns=("id", "x", "y", "width", "height"),
            show="headings",
            height=10,
            selectmode="browse",
        )
        for key, label, width in (
            ("id", "#", 42),
            ("x", "X", 85),
            ("y", "Y", 85),
            ("width", "Width", 95),
            ("height", "Height", 95),
        ):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, anchor="center")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._selected)

        fields = ttk.Frame(body)
        fields.pack(fill="x", pady=(10, 6))
        for column, (key, label) in enumerate(
            (("x", "X"), ("y", "Y"), ("width", "W"), ("height", "H"))
        ):
            group = ttk.Frame(fields)
            group.grid(row=0, column=column, sticky="ew", padx=3)
            fields.columnconfigure(column, weight=1)
            ttk.Label(group, text=label).pack(anchor="w")
            ttk.Entry(
                group, textvariable=self.vars[key], width=9
            ).pack(fill="x")

        nudge = ttk.Frame(body)
        nudge.pack(fill="x", pady=(0, 8))
        for label, dx, dy, dw, dh in (
            ("← 1", -1, 0, 0, 0),
            ("→ 1", 1, 0, 0, 0),
            ("↑ 1", 0, -1, 0, 0),
            ("↓ 1", 0, 1, 0, 0),
            ("W −2", 0, 0, -2, 0),
            ("W +2", 0, 0, 2, 0),
            ("H −2", 0, 0, 0, -2),
            ("H +2", 0, 0, 0, 2),
        ):
            ttk.Button(
                nudge,
                text=label,
                command=lambda values=(dx, dy, dw, dh):
                self._nudge(*values),
            ).pack(side="left", padx=(0, 3))

        actions = ttk.Frame(body)
        actions.pack(fill="x")
        ttk.Button(
            actions, text="生成 4×6 小框", command=self._generate_24
        ).pack(side="left")
        ttk.Button(
            actions, text="新增", command=self._add
        ).pack(side="left", padx=4)
        ttk.Button(
            actions, text="删除", command=self._delete
        ).pack(side="left")
        ttk.Button(
            actions, text="应用坐标", command=self._apply_fields,
            style="Primary.TButton",
        ).pack(side="right")

    def _refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for index, roi in enumerate(self.rois):
            self.tree.insert(
                "", "end", iid=str(index),
                values=(
                    index + 1, roi.x, roi.y, roi.width, roi.height
                ),
            )
        if self.rois:
            self.active_index = min(
                max(self.active_index, 0), len(self.rois) - 1
            )
            self.tree.selection_set(str(self.active_index))
            self.tree.see(str(self.active_index))
            self._load_fields()
        else:
            self.active_index = -1
            for variable in self.vars.values():
                variable.set("")
        self.on_change(list(self.rois), self.active_index)

    def _selected(self, _event=None) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        self.active_index = int(selection[0])
        self._load_fields()
        self.on_change(list(self.rois), self.active_index)

    def _load_fields(self) -> None:
        if not (0 <= self.active_index < len(self.rois)):
            return
        roi = self.rois[self.active_index]
        for key in self.vars:
            self.vars[key].set(str(getattr(roi, key)))

    def _apply_fields(self) -> None:
        if not (0 <= self.active_index < len(self.rois)):
            return
        try:
            roi = ImageROI(
                int(self.vars["x"].get()),
                int(self.vars["y"].get()),
                int(self.vars["width"].get()),
                int(self.vars["height"].get()),
            )
        except ValueError:
            self._load_fields()
            return
        self.rois[self.active_index] = clamp_roi(
            roi, self.image_shape, self.bayer_aligned
        )
        self._refresh()

    def _nudge(self, dx: int, dy: int, dw: int, dh: int) -> None:
        if not (0 <= self.active_index < len(self.rois)):
            return
        roi = self.rois[self.active_index]
        self.rois[self.active_index] = clamp_roi(
            ImageROI(
                roi.x + dx,
                roi.y + dy,
                roi.width + dw,
                roi.height + dh,
            ),
            self.image_shape,
            self.bayer_aligned,
        )
        self._refresh()

    def _generate_24(self) -> None:
        height, width = self.image_shape[:2]
        if 0 <= self.active_index < len(self.rois):
            bounds = self.rois[self.active_index]
        else:
            bounds = ImageROI(
                round(width * 0.1),
                round(height * 0.1),
                max(1, round(width * 0.8)),
                max(1, round(height * 0.8)),
            )
        self.rois = generate_grid_rois(
            bounds,
            self.image_shape,
            rows=4,
            cols=6,
            bayer_aligned=self.bayer_aligned,
        )
        self.active_index = 0
        self._refresh()

    def _add(self) -> None:
        if len(self.rois) >= self.MAX_ROIS:
            return
        height, width = self.image_shape[:2]
        size = max(8, min(width, height) // 8)
        offset = len(self.rois) * 6
        roi = clamp_roi(
            ImageROI(
                min(width - 1, width // 2 - size // 2 + offset),
                min(height - 1, height // 2 - size // 2 + offset),
                size,
                size,
            ),
            self.image_shape,
            self.bayer_aligned,
        )
        self.rois.append(roi)
        self.active_index = len(self.rois) - 1
        self._refresh()

    def _delete(self) -> None:
        if not (0 <= self.active_index < len(self.rois)):
            return
        self.rois.pop(self.active_index)
        self.active_index = min(
            self.active_index, len(self.rois) - 1
        )
        self._refresh()
