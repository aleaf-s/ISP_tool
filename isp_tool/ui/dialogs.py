from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from ..models import RawMetadata


class RawMetadataDialog(tk.Toplevel):
    STORAGE_CHOICES = (
        "uint8", "uint16_le", "uint16_be",
        "mipi_raw10", "mipi_raw12", "mipi_raw14",
    )

    def __init__(self, parent, metadata: RawMetadata, title: str = "裸 RAW 元数据"):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.resizable(False, False)
        self.result: Optional[RawMetadata] = None
        self.vars = {
            "width": tk.StringVar(value=str(metadata.width)),
            "height": tk.StringVar(value=str(metadata.height)),
            "bit_depth": tk.StringVar(value=str(metadata.bit_depth)),
            "storage": tk.StringVar(value=metadata.storage),
            "bayer_pattern": tk.StringVar(value=metadata.bayer_pattern),
            "row_stride_bytes": tk.StringVar(value=str(metadata.row_stride_bytes)),
            "offset_bytes": tk.StringVar(value=str(metadata.offset_bytes)),
            "black_r": tk.StringVar(value=str(metadata.black_level[0])),
            "black_gr": tk.StringVar(value=str(metadata.black_level[1])),
            "black_gb": tk.StringVar(value=str(metadata.black_level[2])),
            "black_b": tk.StringVar(value=str(metadata.black_level[3])),
            "white_level": tk.StringVar(value=str(metadata.white_level)),
            "flip_horizontal": tk.BooleanVar(value=metadata.flip_horizontal),
            "flip_vertical": tk.BooleanVar(value=metadata.flip_vertical),
        }
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.grab_set()
        self.wait_visibility()
        self.focus_set()

    def _build(self) -> None:
        body = ttk.Frame(self, padding=16)
        body.grid(sticky="nsew")
        fields = [
            ("width", "Width"),
            ("height", "Height"),
            ("bit_depth", "Bit Depth"),
            ("storage", "Storage"),
            ("bayer_pattern", "Bayer Pattern"),
            ("row_stride_bytes", "Row Stride (0=自动)"),
            ("offset_bytes", "Data Offset"),
            ("black_r", "Black R"),
            ("black_gr", "Black Gr"),
            ("black_gb", "Black Gb"),
            ("black_b", "Black B"),
            ("white_level", "White Level"),
        ]
        for row, (key, label) in enumerate(fields):
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=4)
            if key == "storage":
                widget = ttk.Combobox(
                    body, textvariable=self.vars[key], values=self.STORAGE_CHOICES,
                    state="readonly", width=20,
                )
            elif key == "bayer_pattern":
                widget = ttk.Combobox(
                    body, textvariable=self.vars[key],
                    values=("RGGB", "GRBG", "GBRG", "BGGR"),
                    state="readonly", width=20,
                )
            elif key == "bit_depth":
                widget = ttk.Combobox(
                    body, textvariable=self.vars[key],
                    values=("8", "10", "12", "14", "16"),
                    state="readonly", width=20,
                )
            else:
                widget = ttk.Entry(body, textvariable=self.vars[key], width=23)
            widget.grid(row=row, column=1, sticky="ew", pady=4)
        row = len(fields)
        ttk.Checkbutton(
            body, text="水平翻转", variable=self.vars["flip_horizontal"]
        ).grid(row=row, column=0, sticky="w", pady=5)
        ttk.Checkbutton(
            body, text="垂直翻转", variable=self.vars["flip_vertical"]
        ).grid(row=row, column=1, sticky="w", pady=5)
        note = ttk.Label(
            body,
            text="提示：MIPI RAW10 宽度应为 4 的倍数，RAW12 为 2 的倍数，RAW14 为 4 的倍数。",
            foreground="#9aa4b2",
            wraplength=420,
        )
        note.grid(row=row + 1, column=0, columnspan=2, sticky="w", pady=(8, 12))
        buttons = ttk.Frame(body)
        buttons.grid(row=row + 2, column=0, columnspan=2, sticky="e")
        ttk.Button(buttons, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="确定", command=self._accept).pack(side="right", padx=(0, 8))

    def _accept(self) -> None:
        try:
            metadata = RawMetadata(
                width=int(self.vars["width"].get()),
                height=int(self.vars["height"].get()),
                bit_depth=int(self.vars["bit_depth"].get()),
                storage=self.vars["storage"].get(),
                bayer_pattern=self.vars["bayer_pattern"].get(),
                row_stride_bytes=int(self.vars["row_stride_bytes"].get()),
                offset_bytes=int(self.vars["offset_bytes"].get()),
                black_level=[
                    float(self.vars["black_r"].get()),
                    float(self.vars["black_gr"].get()),
                    float(self.vars["black_gb"].get()),
                    float(self.vars["black_b"].get()),
                ],
                white_level=float(self.vars["white_level"].get()),
                flip_horizontal=bool(self.vars["flip_horizontal"].get()),
                flip_vertical=bool(self.vars["flip_vertical"].get()),
            )
            metadata.validate()
        except Exception as exc:
            messagebox.showerror("参数错误", str(exc), parent=self)
            return
        self.result = metadata
        self.destroy()


def ask_raw_metadata(parent, metadata: RawMetadata, title: str = "裸 RAW 元数据") -> Optional[RawMetadata]:
    dialog = RawMetadataDialog(parent, metadata, title)
    parent.wait_window(dialog)
    return dialog.result

