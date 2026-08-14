from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..models import ISPError
from .formats import frame_size_bytes
from .metadata import YUVMetadata


@dataclass(frozen=True)
class YUVFileInfo:
    file_size: int
    frame_size: int
    frame_count: int
    remainder: int


def validate_yuv_file(
    path,
    metadata: YUVMetadata,
    *,
    require_complete_frames: bool = True,
) -> YUVFileInfo:
    source = Path(path)
    if not source.exists() or not source.is_file():
        raise ISPError(f"YUV 文件不存在：{source}")
    metadata.validate()
    size = source.stat().st_size
    if metadata.data_offset > size:
        raise ISPError(
            f"Data Offset {metadata.data_offset} 超出文件大小 {size} 字节"
        )
    frame_size = frame_size_bytes(metadata)
    available = size - metadata.data_offset
    frame_count, remainder = divmod(available, frame_size)
    if frame_count < 1:
        raise ISPError(
            f"文件数据不足：每帧需要 {frame_size} 字节，offset 后仅有 {available} 字节"
        )
    if require_complete_frames and remainder:
        raise ISPError(
            f"文件大小与参数不匹配：每帧 {frame_size} 字节，可解析 {frame_count} 帧，"
            f"末尾多出 {remainder} 字节"
        )
    if metadata.frame_index >= frame_count:
        raise ISPError(
            f"Frame Index {metadata.frame_index} 越界；有效范围 0…{frame_count - 1}"
        )
    metadata.frame_count = int(frame_count)
    return YUVFileInfo(size, frame_size, int(frame_count), int(remainder))
