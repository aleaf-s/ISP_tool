from __future__ import annotations

from pathlib import Path

import numpy as np

from ..models import ISPError
from .formats import (
    bytes_per_sample,
    canonical_pixel_format,
    frame_size_bytes,
    minimum_strides,
)
from .metadata import YUVFrame, YUVMetadata
from .validation import validate_yuv_file


def _rows(buffer, offset, rows, stride, active_bytes):
    view = np.ndarray(
        (rows, stride),
        dtype=np.uint8,
        buffer=buffer,
        offset=offset,
    )
    return np.ascontiguousarray(view[:, :active_bytes]), offset + rows * stride


def _samples(row_bytes, width, metadata, *, p010=False):
    if bytes_per_sample(metadata) == 1:
        return row_bytes[:, :width].copy()
    dtype = "<u2" if metadata.endianness == "little" else ">u2"
    values = np.frombuffer(row_bytes.tobytes(), dtype=dtype).reshape(
        row_bytes.shape[0], -1
    )[:, :width].astype(np.uint16, copy=False)
    if p010:
        if np.any(values & np.uint16(0x003F)):
            raise ISPError("P010 数据低 6 bit 非零，可能不是 MSB 对齐的 P010")
        values = values >> np.uint16(6)
    elif np.any(values > ((1 << metadata.bit_depth) - 1)):
        raise ISPError(
            f"{metadata.pixel_format} 存在超出 {metadata.bit_depth}-bit 范围的码值"
        )
    return np.ascontiguousarray(values)


def read_yuv_frame(
    path,
    metadata: YUVMetadata,
    frame_index: int | None = None,
) -> YUVFrame:
    source = Path(path)
    info = validate_yuv_file(source, metadata)
    index = metadata.frame_index if frame_index is None else int(frame_index)
    if not 0 <= index < info.frame_count:
        raise ISPError(
            f"Frame Index {index} 越界；有效范围 0…{info.frame_count - 1}"
        )
    frame_offset = metadata.data_offset + index * info.frame_size
    mapped = np.memmap(
        source,
        mode="r",
        dtype=np.uint8,
        offset=frame_offset,
        shape=(info.frame_size,),
    )
    fmt = canonical_pixel_format(metadata.pixel_format)
    sample_bytes = bytes_per_sample(metadata)
    min_y, min_uv = minimum_strides(metadata)
    y_stride = metadata.y_stride or min_y
    uv_stride = metadata.uv_stride or min_uv
    h, w = metadata.height, metadata.width
    diagnostics = {
        "frame_size": info.frame_size,
        "frame_count": info.frame_count,
        "mapped_bytes": info.frame_size,
    }

    if fmt in {"YUYV", "UYVY"}:
        packed, _ = _rows(mapped, 0, h, y_stride, w * 2)
        groups = packed.reshape(h, w // 2, 4)
        if fmt == "YUYV":
            y = np.empty((h, w), np.uint8)
            y[:, 0::2], y[:, 1::2] = groups[..., 0], groups[..., 2]
            u, v = groups[..., 1].copy(), groups[..., 3].copy()
        else:
            y = np.empty((h, w), np.uint8)
            y[:, 0::2], y[:, 1::2] = groups[..., 1], groups[..., 3]
            u, v = groups[..., 0].copy(), groups[..., 2].copy()
    else:
        y_bytes, offset = _rows(mapped, 0, h, y_stride, w * sample_bytes)
        y = _samples(y_bytes, w, metadata, p010=(fmt == "P010"))
        if fmt == "GRAY":
            neutral = 1 << (metadata.bit_depth - 1)
            u = np.full((h, w), neutral, dtype=y.dtype)
            v = np.full((h, w), neutral, dtype=y.dtype)
        elif fmt in {"NV12", "NV21", "P010"}:
            chroma_h = h // 2
            uv_bytes, _ = _rows(
                mapped,
                offset,
                chroma_h,
                uv_stride,
                w * sample_bytes,
            )
            uv = _samples(
                uv_bytes,
                w,
                metadata,
                p010=(fmt == "P010"),
            ).reshape(chroma_h, w // 2, 2)
            first, second = uv[..., 0].copy(), uv[..., 1].copy()
            u, v = (first, second) if fmt in {"NV12", "P010"} else (second, first)
        else:
            chroma_h = h // 2 if fmt in {"I420", "YV12", "YUV420P10LE"} else h
            chroma_w = w if fmt == "YUV444P" else w // 2
            active = chroma_w * sample_bytes
            first_bytes, offset = _rows(
                mapped, offset, chroma_h, uv_stride, active
            )
            second_bytes, _ = _rows(
                mapped, offset, chroma_h, uv_stride, active
            )
            first = _samples(first_bytes, chroma_w, metadata)
            second = _samples(second_bytes, chroma_w, metadata)
            u, v = (second, first) if fmt == "YV12" else (first, second)

    copied_metadata = YUVMetadata.from_dict(metadata.to_dict())
    copied_metadata.frame_index = index
    copied_metadata.frame_count = info.frame_count
    return YUVFrame(
        np.ascontiguousarray(y),
        np.ascontiguousarray(u),
        np.ascontiguousarray(v),
        copied_metadata,
        index,
        info.file_size,
        diagnostics,
    )
