from __future__ import annotations

from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from .models import ISPError, LoadedImage, RawMetadata

try:
    import rawpy
except ImportError:  # pragma: no cover
    rawpy = None

try:
    import tifffile
except ImportError:  # pragma: no cover
    tifffile = None


PLAIN_EXTENSIONS = {".raw", ".bin", ".dat"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}
CAMERA_RAW_EXTENSIONS = {
    ".dng", ".nef", ".cr2", ".cr3", ".arw", ".raf", ".rw2", ".orf",
    ".pef", ".srw", ".x3f",
}


def packed_row_bytes(width: int, storage: str) -> int:
    if storage == "mipi_raw10":
        return (width * 10 + 7) // 8
    if storage == "mipi_raw12":
        return (width * 12 + 7) // 8
    if storage == "mipi_raw14":
        return (width * 14 + 7) // 8
    if storage == "uint8":
        return width
    return width * 2


def _unpack_mipi_row(row: np.ndarray, width: int, bits: int) -> np.ndarray:
    row = np.asarray(row, dtype=np.uint8)
    if bits == 10:
        groups = width // 4
        needed = groups * 5
        if len(row) < needed:
            raise ISPError("MIPI RAW10 行数据长度不足")
        block = row[:needed].reshape(-1, 5).astype(np.uint16)
        low = block[:, 4]
        values = np.stack([
            (block[:, 0] << 2) | (low & 0x03),
            (block[:, 1] << 2) | ((low >> 2) & 0x03),
            (block[:, 2] << 2) | ((low >> 4) & 0x03),
            (block[:, 3] << 2) | ((low >> 6) & 0x03),
        ], axis=1).reshape(-1)
    elif bits == 12:
        groups = width // 2
        needed = groups * 3
        if len(row) < needed:
            raise ISPError("MIPI RAW12 行数据长度不足")
        block = row[:needed].reshape(-1, 3).astype(np.uint16)
        low = block[:, 2]
        values = np.stack([
            (block[:, 0] << 4) | (low & 0x0F),
            (block[:, 1] << 4) | ((low >> 4) & 0x0F),
        ], axis=1).reshape(-1)
    elif bits == 14:
        groups = width // 4
        needed = groups * 7
        if len(row) < needed:
            raise ISPError("MIPI RAW14 行数据长度不足")
        block = row[:needed].reshape(-1, 7).astype(np.uint16)
        packed = (
            block[:, 4].astype(np.uint32)
            | (block[:, 5].astype(np.uint32) << 8)
            | (block[:, 6].astype(np.uint32) << 16)
        )
        values = np.stack([
            (block[:, 0] << 6) | (packed & 0x3F),
            (block[:, 1] << 6) | ((packed >> 6) & 0x3F),
            (block[:, 2] << 6) | ((packed >> 12) & 0x3F),
            (block[:, 3] << 6) | ((packed >> 18) & 0x3F),
        ], axis=1).reshape(-1)
    else:
        raise ISPError(f"不支持的 MIPI 位深：{bits}")
    if values.size < width:
        raise ISPError(f"图像宽度 {width} 必须满足 MIPI RAW{bits} 的打包分组")
    return values[:width]


def read_plain_raw(path: Path, metadata: RawMetadata) -> LoadedImage:
    metadata.validate()
    raw = np.fromfile(str(path), dtype=np.uint8)
    row_bytes = packed_row_bytes(metadata.width, metadata.storage)
    stride = metadata.row_stride_bytes or row_bytes
    required = metadata.offset_bytes + stride * metadata.height
    if raw.size < required:
        raise ISPError(
            f"文件数据不足：需要至少 {required} 字节，实际 {raw.size} 字节。"
            "请检查宽高、stride、offset 和存储格式。"
        )
    output = np.empty((metadata.height, metadata.width), dtype=np.float32)
    for y in range(metadata.height):
        start = metadata.offset_bytes + y * stride
        row = raw[start:start + row_bytes]
        if metadata.storage == "uint8":
            values = row[:metadata.width].astype(np.uint16)
        elif metadata.storage in {"uint16_le", "uint16_be"}:
            dtype = "<u2" if metadata.storage == "uint16_le" else ">u2"
            values = np.frombuffer(row.tobytes(), dtype=dtype, count=metadata.width)
        else:
            bits = int(metadata.storage[-2:])
            values = _unpack_mipi_row(row, metadata.width, bits)
        output[y] = values
    if metadata.flip_horizontal:
        output = output[:, ::-1]
    if metadata.flip_vertical:
        output = output[::-1]
    return LoadedImage(
        image=np.ascontiguousarray(output),
        domain="bayer",
        metadata=metadata,
        source_path=path,
        description=f"裸 RAW · {metadata.storage} · {metadata.bayer_pattern}",
    )


def _camera_pattern(raw: "rawpy.RawPy") -> str:
    desc = raw.color_desc.decode("ascii", errors="ignore")
    chars = []
    for y in range(2):
        for x in range(2):
            index = int(raw.raw_pattern[y, x])
            char = desc[index] if index < len(desc) else "G"
            chars.append("G" if char.upper() == "G" else char.upper())
    pattern = "".join(chars)
    return pattern if pattern in {"RGGB", "GRBG", "GBRG", "BGGR"} else "RGGB"


def read_camera_raw(path: Path) -> LoadedImage:
    if rawpy is None:
        raise ISPError("缺少 rawpy，无法读取相机 RAW")
    with rawpy.imread(str(path)) as raw:
        mosaic = raw.raw_image_visible.copy().astype(np.float32)
        pattern = _camera_pattern(raw)
        black = list(map(float, raw.black_level_per_channel[:4]))
        metadata = RawMetadata(
            width=mosaic.shape[1],
            height=mosaic.shape[0],
            bit_depth=16,
            storage="uint16_le",
            bayer_pattern=pattern,
            black_level=black,
            white_level=float(raw.white_level),
        )
    return LoadedImage(mosaic, "bayer", metadata, path, f"相机 RAW · {pattern}")


def read_standard_image(path: Path, bayer_metadata: Optional[RawMetadata] = None) -> LoadedImage:
    suffix = path.suffix.lower()
    if suffix in {".tif", ".tiff"} and tifffile is not None:
        data = tifffile.imread(str(path))
    else:
        data = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if data is None:
            raise ISPError(f"无法读取图像：{path}")
        if data.ndim == 3:
            if data.shape[2] == 4:
                data = cv2.cvtColor(data, cv2.COLOR_BGRA2RGBA)
            else:
                data = cv2.cvtColor(data, cv2.COLOR_BGR2RGB)
    data = np.asarray(data)
    maximum = float(np.iinfo(data.dtype).max) if np.issubdtype(data.dtype, np.integer) else 1.0
    normalized = data.astype(np.float32) / max(maximum, 1.0)
    if normalized.ndim == 2:
        meta = bayer_metadata or RawMetadata(
            width=normalized.shape[1],
            height=normalized.shape[0],
            bit_depth=16 if maximum > 255 else 8,
            black_level=[0.0] * 4,
            white_level=maximum,
        )
        meta.width, meta.height = normalized.shape[1], normalized.shape[0]
        # Convert normalized TIFF back to DN because BLC owns normalization.
        return LoadedImage(normalized * meta.white_level, "bayer", meta, path, "单通道图像（按 Bayer 解释）")
    if normalized.shape[2] > 3:
        normalized = normalized[:, :, :3]
    meta = RawMetadata(
        width=normalized.shape[1],
        height=normalized.shape[0],
        bit_depth=8 if maximum <= 255 else 16,
        black_level=[0.0] * 4,
        white_level=maximum,
    )
    return LoadedImage(normalized, "rgb", meta, path, "RGB 测试图")


def load_image(path: str, metadata: Optional[RawMetadata] = None) -> LoadedImage:
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix in PLAIN_EXTENSIONS:
        if metadata is None:
            raise ISPError("裸 RAW 需要提供宽高、位深和存储格式")
        return read_plain_raw(source, metadata)
    if suffix in CAMERA_RAW_EXTENSIONS:
        return read_camera_raw(source)
    if suffix in IMAGE_EXTENSIONS:
        return read_standard_image(source, metadata)
    raise ISPError(f"不支持的文件类型：{suffix}")


def synthetic_bayer(width: int = 3840, height: int = 2160, pattern: str = "RGGB") -> LoadedImage:
    """Create a deterministic scene with gradients, color patches and edges."""
    from .bayer import channel_positions
    

    width = max(64, width // 2 * 2)
    height = max(64, height // 2 * 2)
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    x = xx / max(width - 1, 1)
    y = yy / max(height - 1, 1)
    rgb = np.stack([
        0.08 + 0.70 * x,
        0.08 + 0.70 * y,
        0.12 + 0.58 * (1.0 - x),
    ], axis=-1)
    rgb *= (0.55 + 0.45 * (1.0 - ((x - 0.5) ** 2 + (y - 0.5) ** 2)))[..., None]
    colors = [
        (0.85, 0.15, 0.12), (0.15, 0.78, 0.20), (0.12, 0.28, 0.90),
        (0.90, 0.78, 0.10), (0.80, 0.18, 0.72), (0.10, 0.75, 0.80),
        (0.18, 0.18, 0.18), (0.50, 0.50, 0.50), (0.88, 0.88, 0.88),
    ]
    patch_w, patch_h = width // 11, height // 7
    for index, color in enumerate(colors):
        row, col = divmod(index, 3)
        x0 = width // 2 + col * patch_w
        y0 = height // 8 + row * (patch_h + 12)
        rgb[y0:y0 + patch_h, x0:x0 + patch_w] = color
    # Fine black/white bars make demosaic and sharpening differences visible.
    for offset in range(0, width // 3, 8):
        value = 0.92 if (offset // 8) % 2 else 0.03
        rgb[height * 3 // 4:height - 30, 25 + offset:29 + offset] = value
    mosaic = np.zeros((height, width), np.float32)
    positions = channel_positions(pattern)
    for name, (py, px) in positions.items():
        channel = {"R": 0, "Gr": 1, "Gb": 1, "B": 2}[name]
        mosaic[py::2, px::2] = rgb[py::2, px::2, channel]
    black, white = 64.0, 4095.0
    rng = np.random.default_rng(7)
    dn = mosaic * (white - black) + black + rng.normal(0, 2.0, mosaic.shape)
    metadata = RawMetadata(
        width=width,
        height=height,
        bit_depth=12,
        bayer_pattern=pattern,
        black_level=[black] * 4,
        white_level=white,
    )
    return LoadedImage(
        np.clip(dn, 0, white).astype(np.float32),
        "bayer",
        metadata,
        None,
        "内置合成 Bayer 测试图",
    )
