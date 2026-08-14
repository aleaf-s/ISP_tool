from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from .metadata import YUVMetadata


@dataclass(frozen=True)
class YUVFilenameInference:
    """Metadata inferred from a filename, with explicit uncertainty notes."""

    metadata: YUVMetadata
    recognized: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()

    @property
    def summary(self) -> str:
        if not self.recognized:
            return "文件名未提供可靠的 YUV 参数，请手动确认。"
        text = "文件名识别：" + " · ".join(self.recognized)
        if self.warnings:
            text += "\n需确认：" + "；".join(self.warnings)
        return text


_EXPLICIT_FORMATS = (
    ("YUV420P10LE", "YUV420P10LE"),
    ("YUV444P", "YUV444P"),
    ("YUV422P", "YUV422P"),
    ("YUV420P", "I420"),
    ("YUY2", "YUYV"),
    ("YUYV", "YUYV"),
    ("UYVY", "UYVY"),
    ("NV12", "NV12"),
    ("NV21", "NV21"),
    ("I420", "I420"),
    ("YV12", "YV12"),
    ("P010", "P010"),
    ("GRAY", "GRAY"),
)


def infer_yuv_filename(
    path,
    fallback: Optional[YUVMetadata] = None,
) -> YUVFilenameInference:
    """Infer common YUV metadata tokens without pretending ambiguity is fact."""

    metadata = copy.deepcopy(fallback or YUVMetadata())
    name = Path(path).stem.upper()
    recognized = []
    warnings = []

    size = re.search(
        r"(?<!\d)(\d{2,5})\s*[X×]\s*(\d{2,5})(?!\d)", name
    )
    if size is None:
        size = re.search(
            r"(?<!\d)(\d{2,5})[_-](\d{2,5})(?!\d)", name
        )
    if size:
        metadata.width = int(size.group(1))
        metadata.height = int(size.group(2))
        recognized.append(f"{metadata.width}×{metadata.height}")

    bit_depth = re.search(
        r"(?<!\d)(8|10|12|16)\s*(?:BITS?|BIT|B)(?![A-Z0-9])",
        name,
    )
    if bit_depth:
        metadata.bit_depth = int(bit_depth.group(1))
        recognized.append(f"{metadata.bit_depth}-bit")

    explicit_format = False
    for token, pixel_format in _EXPLICIT_FORMATS:
        if token in name:
            metadata.pixel_format = pixel_format
            if pixel_format in {"P010", "YUV420P10LE"}:
                metadata.bit_depth = 10
            recognized.append(pixel_format)
            explicit_format = True
            break

    if not explicit_format and re.search(r"(?:YUV)?420[_-]?SP", name):
        # 420SP describes interleaved chroma but not whether it is UV or VU.
        metadata.pixel_format = "NV12"
        recognized.append("420SP → NV12（推测）")
        warnings.append(
            "420SP 无法区分 UV/VU 顺序，当前暂按 NV12；"
            "若颜色明显异常请改为 NV21"
        )
    elif not explicit_format and re.search(r"(?:YUV)?420[_-]?P", name):
        metadata.pixel_format = "I420"
        recognized.append("420P → I420（推测）")
        warnings.append(
            "420P 未声明 U/V 平面顺序，当前暂按 I420；"
            "如为 Y-V-U 请改为 YV12"
        )

    if "BT2020" in name or "BT.2020" in name:
        metadata.color_matrix = "BT.2020"
        recognized.append("BT.2020")
    elif "BT709" in name or "BT.709" in name:
        metadata.color_matrix = "BT.709"
        recognized.append("BT.709")
    elif "BT601" in name or "BT.601" in name:
        metadata.color_matrix = "BT.601"
        recognized.append("BT.601")

    if re.search(r"(?:^|[_\-.])FULL(?:[_\-.]|$)", name):
        metadata.color_range = "Full"
        recognized.append("Full Range")
    elif re.search(r"(?:^|[_\-.])LIMITED(?:[_\-.]|$)", name):
        metadata.color_range = "Limited"
        recognized.append("Limited Range")

    if re.search(r"(?:^|[_\-.])BE(?:[_\-.]|$)", name):
        metadata.endianness = "big"
        recognized.append("Big-endian")
    elif re.search(r"(?:^|[_\-.])LE(?:[_\-.]|$)", name):
        metadata.endianness = "little"
        recognized.append("Little-endian")

    if re.search(r"(?:^|[_\-.])LINEAR(?:[_\-.]|$)", name):
        recognized.append("Linear Layout")

    if metadata.bit_depth > 8 and metadata.pixel_format == "NV12":
        warnings.append(
            "高位深 420SP 的对齐方式无法从文件名确定，"
            "请确认是 P010 还是低位对齐的 16-bit 容器"
        )

    return YUVFilenameInference(
        metadata=metadata,
        recognized=tuple(recognized),
        warnings=tuple(warnings),
    )


def infer_yuv_metadata(
    path,
    fallback: Optional[YUVMetadata] = None,
) -> YUVMetadata:
    """Compatibility helper returning only the inferred metadata."""

    return infer_yuv_filename(path, fallback).metadata
