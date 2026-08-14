from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from pathlib import Path
from typing import Optional

from ..models import RawMetadata
from ..yuv import (
    PIXEL_FORMATS,
    YUVMetadata,
    infer_yuv_filename,
    infer_yuv_metadata,
    validate_yuv_file,
)


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


class YUVMetadataDialog(tk.Toplevel):
    PRESETS = {
        "自定义": None,
        "1080p NV12 · BT.709 Limited": (1920, 1080, "NV12", 8, "BT.709", "Limited"),
        "1080p I420 · BT.709 Limited": (1920, 1080, "I420", 8, "BT.709", "Limited"),
        "4K P010 · BT.2020 Limited": (3840, 2160, "P010", 10, "BT.2020", "Limited"),
    }

    def __init__(self, parent, path, metadata: Optional[YUVMetadata] = None):
        super().__init__(parent)
        self.path = Path(path)
        self.result: Optional[YUVMetadata] = None
        inference = infer_yuv_filename(path, metadata)
        inferred = inference.metadata
        self.filename_inference_summary = inference.summary
        self.title("裸 YUV 元数据")
        self.transient(parent)
        self.resizable(False, False)
        self.vars = {
            "preset": tk.StringVar(value="自定义"),
            "width": tk.StringVar(value=str(inferred.width)),
            "height": tk.StringVar(value=str(inferred.height)),
            "pixel_format": tk.StringVar(value=inferred.pixel_format),
            "bit_depth": tk.StringVar(value=str(inferred.bit_depth)),
            "color_matrix": tk.StringVar(value=inferred.color_matrix),
            "color_range": tk.StringVar(value=inferred.color_range),
            "chroma_siting": tk.StringVar(value=inferred.chroma_siting),
            "chroma_upsampling": tk.StringVar(value=inferred.chroma_upsampling),
            "endianness": tk.StringVar(value=inferred.endianness),
            "y_stride": tk.StringVar(value=str(inferred.y_stride)),
            "uv_stride": tk.StringVar(value=str(inferred.uv_stride)),
            "data_offset": tk.StringVar(value=str(inferred.data_offset)),
            "frame_index": tk.StringVar(value=str(inferred.frame_index)),
        }
        self.info_var = tk.StringVar(value="")
        self._build()
        for key, variable in self.vars.items():
            if key != "preset":
                variable.trace_add("write", lambda *_args: self._refresh_validation())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self._refresh_validation()
        self.grab_set()
        self.wait_visibility()
        self.focus_set()

    def _build(self):
        body = ttk.Frame(self, padding=14)
        body.grid(sticky="nsew")
        ttk.Label(
            body,
            text=self.path.name,
            style="Title.TLabel",
            wraplength=430,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        fields = [
            ("preset", "Preset", tuple(self.PRESETS)),
            ("width", "Width", None),
            ("height", "Height", None),
            ("pixel_format", "Pixel Format", PIXEL_FORMATS),
            ("bit_depth", "Bit Depth", ("8", "10", "12", "16")),
            ("color_matrix", "Color Matrix", ("BT.601", "BT.709", "BT.2020")),
            ("color_range", "Color Range", ("Limited", "Full")),
            ("chroma_siting", "Chroma Siting", ("Center", "Left", "Top-left")),
            ("chroma_upsampling", "Chroma Upsampling", ("Bilinear", "Nearest")),
            ("endianness", "Endianness", ("little", "big")),
            ("y_stride", "Y Stride (0=自动)", None),
            ("uv_stride", "UV Stride (0=自动)", None),
            ("data_offset", "Data Offset", None),
            ("frame_index", "Frame Index (从 0 开始)", None),
        ]
        for index, (key, label, choices) in enumerate(fields, 1):
            ttk.Label(body, text=label).grid(
                row=index, column=0, sticky="w", padx=(0, 12), pady=3
            )
            if choices:
                widget = ttk.Combobox(
                    body,
                    textvariable=self.vars[key],
                    values=choices,
                    state="readonly",
                    width=29,
                )
                if key == "preset":
                    widget.bind("<<ComboboxSelected>>", self._apply_preset)
            else:
                widget = ttk.Entry(body, textvariable=self.vars[key], width=32)
            widget.grid(row=index, column=1, sticky="ew", pady=3)
        info_row = len(fields) + 1
        ttk.Label(
            body,
            textvariable=self.info_var,
            style="Muted.TLabel",
            wraplength=460,
        ).grid(row=info_row, column=0, columnspan=2, sticky="w", pady=(8, 10))
        actions = ttk.Frame(body)
        actions.grid(row=info_row + 1, column=0, columnspan=2, sticky="e")
        ttk.Button(actions, text="取消", command=self.destroy).pack(side="right")
        self.accept_button = ttk.Button(
            actions,
            text="导入",
            style="Primary.TButton",
            command=self._accept,
        )
        self.accept_button.pack(side="right", padx=(0, 8))

    def _apply_preset(self, _event=None):
        preset = self.PRESETS.get(self.vars["preset"].get())
        if preset is None:
            return
        width, height, fmt, depth, matrix, color_range = preset
        for key, value in {
            "width": width,
            "height": height,
            "pixel_format": fmt,
            "bit_depth": depth,
            "color_matrix": matrix,
            "color_range": color_range,
            "y_stride": 0,
            "uv_stride": 0,
            "data_offset": 0,
            "frame_index": 0,
        }.items():
            self.vars[key].set(str(value))

    def _metadata(self) -> YUVMetadata:
        return YUVMetadata(
            width=int(self.vars["width"].get()),
            height=int(self.vars["height"].get()),
            pixel_format=self.vars["pixel_format"].get(),
            bit_depth=int(self.vars["bit_depth"].get()),
            color_matrix=self.vars["color_matrix"].get(),
            color_range=self.vars["color_range"].get(),
            chroma_siting=self.vars["chroma_siting"].get(),
            chroma_upsampling=self.vars["chroma_upsampling"].get(),
            endianness=self.vars["endianness"].get(),
            y_stride=int(self.vars["y_stride"].get()),
            uv_stride=int(self.vars["uv_stride"].get()),
            data_offset=int(self.vars["data_offset"].get()),
            frame_index=int(self.vars["frame_index"].get()),
        )

    def _refresh_validation(self):
        try:
            metadata = self._metadata()
            info = validate_yuv_file(self.path, metadata)
            self.info_var.set(
                f"{self.filename_inference_summary}\n"
                f"每帧 {info.frame_size:,} 字节 · 共 {info.frame_count} 帧 · "
                f"文件 {info.file_size:,} 字节"
            )
            self.accept_button.configure(state="normal")
        except Exception as exc:
            self.info_var.set(
                f"{self.filename_inference_summary}\n参数尚不可用：{exc}"
            )
            self.accept_button.configure(state="disabled")

    def _accept(self):
        try:
            metadata = self._metadata()
            validate_yuv_file(self.path, metadata)
        except Exception as exc:
            messagebox.showerror("YUV 参数错误", str(exc), parent=self)
            return
        self.result = metadata
        self.destroy()


def ask_yuv_metadata(
    parent,
    path,
    metadata: Optional[YUVMetadata] = None,
) -> Optional[YUVMetadata]:
    dialog = YUVMetadataDialog(parent, path, metadata)
    parent.wait_window(dialog)
    return dialog.result
