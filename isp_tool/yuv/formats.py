from __future__ import annotations

from typing import Dict, Tuple

from ..models import ISPError
from .metadata import YUVMetadata


PIXEL_FORMATS = (
    "I420",
    "YV12",
    "NV12",
    "NV21",
    "YUYV",
    "UYVY",
    "YUV444P",
    "YUV422P",
    "GRAY",
    "P010",
    "YUV420P10LE",
)

_ALIASES: Dict[str, str] = {
    "I420": "I420",
    "YU12": "I420",
    "YUV420P": "I420",
    "YV12": "YV12",
    "NV12": "NV12",
    "NV21": "NV21",
    "YUYV": "YUYV",
    "YUY2": "YUYV",
    "UYVY": "UYVY",
    "YUV444P": "YUV444P",
    "I444": "YUV444P",
    "YUV422P": "YUV422P",
    "I422": "YUV422P",
    "GRAY": "GRAY",
    "Y": "GRAY",
    "YONLY": "GRAY",
    "P010": "P010",
    "YUV420P10LE": "YUV420P10LE",
}


def canonical_pixel_format(value: str) -> str:
    key = str(value).upper().replace(" ", "").replace("-", "")
    if key not in _ALIASES:
        raise ISPError(
            f"不支持的 YUV Pixel Format：{value}；支持 {', '.join(PIXEL_FORMATS)}"
        )
    return _ALIASES[key]


def bytes_per_sample(metadata: YUVMetadata) -> int:
    return 2 if metadata.bit_depth > 8 or metadata.pixel_format in {
        "P010", "YUV420P10LE"
    } else 1


def minimum_strides(metadata: YUVMetadata) -> Tuple[int, int]:
    fmt = canonical_pixel_format(metadata.pixel_format)
    sample_bytes = bytes_per_sample(metadata)
    width = metadata.width
    if fmt in {"YUYV", "UYVY"}:
        return width * 2, 0
    y_stride = width * sample_bytes
    if fmt in {"NV12", "NV21", "P010"}:
        return y_stride, width * sample_bytes
    if fmt in {"I420", "YV12", "YUV420P10LE", "YUV422P"}:
        return y_stride, ((width + 1) // 2) * sample_bytes
    if fmt == "YUV444P":
        return y_stride, width * sample_bytes
    return y_stride, 0


def validate_dimensions(metadata: YUVMetadata) -> None:
    fmt = canonical_pixel_format(metadata.pixel_format)
    if fmt in {"I420", "YV12", "NV12", "NV21", "P010", "YUV420P10LE"}:
        if metadata.width % 2 or metadata.height % 2:
            raise ISPError(f"{fmt} 要求宽度和高度均为偶数")
    if fmt in {"YUYV", "UYVY", "YUV422P"} and metadata.width % 2:
        raise ISPError(f"{fmt} 要求宽度为偶数")
    if fmt in {"YUYV", "UYVY"} and metadata.bit_depth != 8:
        raise ISPError(f"{fmt} 第一版仅支持 8-bit")
    if fmt in {"P010", "YUV420P10LE"} and metadata.bit_depth != 10:
        raise ISPError(f"{fmt} 必须选择 10-bit")
    if fmt in {"P010", "YUV420P10LE"} and metadata.endianness != "little":
        raise ISPError(f"{fmt} 必须使用 little-endian")


def plane_layout(metadata: YUVMetadata):
    metadata.validate()
    validate_dimensions(metadata)
    fmt = canonical_pixel_format(metadata.pixel_format)
    min_y, min_uv = minimum_strides(metadata)
    y_stride = metadata.y_stride or min_y
    uv_stride = metadata.uv_stride or min_uv
    h, w = metadata.height, metadata.width
    if fmt in {"YUYV", "UYVY"}:
        return (("PACKED", h, y_stride),)
    layout = [("Y", h, y_stride)]
    if fmt == "GRAY":
        return tuple(layout)
    chroma_h = h // 2 if fmt in {
        "I420", "YV12", "NV12", "NV21", "P010", "YUV420P10LE"
    } else h
    if fmt in {"NV12", "NV21", "P010"}:
        layout.append(("UV", chroma_h, uv_stride))
    else:
        layout.extend((("U", chroma_h, uv_stride), ("V", chroma_h, uv_stride)))
    return tuple(layout)


def frame_size_bytes(metadata: YUVMetadata) -> int:
    return sum(rows * stride for _, rows, stride in plane_layout(metadata))
