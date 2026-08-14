from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional, Tuple

import numpy as np

from ..models import ISPError


@dataclass
class YUVMetadata:
    width: int = 1920
    height: int = 1080
    pixel_format: str = "NV12"
    bit_depth: int = 8
    color_matrix: str = "BT.709"
    color_range: str = "Limited"
    chroma_siting: str = "Center"
    chroma_upsampling: str = "Bilinear"
    endianness: str = "little"
    y_stride: int = 0
    uv_stride: int = 0
    data_offset: int = 0
    frame_index: int = 0
    frame_count: int = 0

    def validate(self) -> None:
        from .formats import (
            canonical_pixel_format,
            minimum_strides,
            validate_dimensions,
        )

        if self.width <= 0 or self.height <= 0:
            raise ISPError("YUV 宽度和高度必须大于 0")
        self.pixel_format = canonical_pixel_format(self.pixel_format)
        if self.bit_depth not in {8, 10, 12, 16}:
            raise ISPError("YUV 位深必须是 8/10/12/16")
        if self.color_matrix not in {"BT.601", "BT.709", "BT.2020"}:
            raise ISPError(f"不支持的 YUV Color Matrix：{self.color_matrix}")
        if self.color_range not in {"Limited", "Full"}:
            raise ISPError("YUV Range 必须是 Limited 或 Full")
        if self.chroma_siting not in {"Center", "Left", "Top-left"}:
            raise ISPError("不支持的 Chroma Siting")
        if self.chroma_upsampling not in {"Nearest", "Bilinear"}:
            raise ISPError("Chroma Upsampling 必须是 Nearest 或 Bilinear")
        if self.endianness not in {"little", "big"}:
            raise ISPError("Endianness 必须是 little 或 big")
        if self.data_offset < 0 or self.y_stride < 0 or self.uv_stride < 0:
            raise ISPError("YUV offset/stride 不能为负数")
        min_y, min_uv = minimum_strides(self)
        if self.y_stride and self.y_stride < min_y:
            raise ISPError(
                f"Y stride {self.y_stride} 小于格式要求的 {min_y} 字节"
            )
        if min_uv and self.uv_stride and self.uv_stride < min_uv:
            raise ISPError(
                f"UV stride {self.uv_stride} 小于格式要求的 {min_uv} 字节"
            )
        if self.frame_index < 0:
            raise ISPError("Frame Index 不能为负数")
        validate_dimensions(self)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "YUVMetadata":
        known = {field.name for field in cls.__dataclass_fields__.values()}
        return cls(**{key: value for key, value in data.items() if key in known})


@dataclass
class YUVFrame:
    y: np.ndarray
    u: np.ndarray
    v: np.ndarray
    metadata: YUVMetadata
    frame_index: int = 0
    source_size: int = 0
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    @property
    def shape(self) -> Tuple[int, int]:
        return self.metadata.height, self.metadata.width

    @property
    def bit_depth(self) -> int:
        return self.metadata.bit_depth

    @property
    def code_max(self) -> int:
        return (1 << self.bit_depth) - 1

    def sample(self, x: int, y: int) -> Tuple[int, int, int]:
        x = max(0, min(int(x), self.metadata.width - 1))
        y = max(0, min(int(y), self.metadata.height - 1))
        chroma_h, chroma_w = self.u.shape
        cx = min(chroma_w - 1, int(x * chroma_w / self.metadata.width))
        cy = min(chroma_h - 1, int(y * chroma_h / self.metadata.height))
        return int(self.y[y, x]), int(self.u[cy, cx]), int(self.v[cy, cx])
