from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from ...models import StageResult
from ...yuv import (
    YUVFrame,
    YUVMetadata,
    read_yuv_frame,
    yuv_to_rgb,
)


class YUVPreviewController:
    """Build YUV preview stages without depending on Tk or application state."""

    @staticmethod
    def cache_key(
        path: str,
        metadata: YUVMetadata,
        preview_max_side: int,
    ) -> tuple:
        source = Path(path)
        stat = source.stat()
        return (
            str(source.resolve()),
            int(stat.st_mtime_ns),
            int(stat.st_size),
            int(metadata.frame_index),
            metadata.pixel_format,
            int(metadata.bit_depth),
            metadata.color_matrix,
            metadata.color_range,
            metadata.chroma_siting,
            metadata.chroma_upsampling,
            metadata.endianness,
            int(metadata.y_stride),
            int(metadata.uv_stride),
            int(metadata.data_offset),
            int(preview_max_side),
        )

    @staticmethod
    def process(
        path: str,
        metadata: YUVMetadata,
        preview_max_side: int,
        cancelled: Callable[[], bool],
        existing_frame: Optional[YUVFrame] = None,
    ) -> dict:
        started = time.perf_counter()
        read_started = started
        if existing_frame is None:
            frame = read_yuv_frame(path, metadata, metadata.frame_index)
            read_ms = (time.perf_counter() - read_started) * 1000.0
        else:
            metadata.frame_count = existing_frame.metadata.frame_count
            frame = YUVFrame(
                existing_frame.y,
                existing_frame.u,
                existing_frame.v,
                metadata,
                metadata.frame_index,
                existing_frame.source_size,
                {**existing_frame.diagnostics, "reused_planes": True},
            )
            read_ms = 0.0
        if cancelled():
            raise RuntimeError("YUV request cancelled")

        height, width = frame.shape
        target_size = None
        if max(width, height) > preview_max_side:
            scale = preview_max_side / max(width, height)
            target_size = (
                max(1, int(round(width * scale))),
                max(1, int(round(height * scale))),
            )
        conversion_started = time.perf_counter()
        conversion = yuv_to_rgb(
            frame, target_size=target_size, clip=False
        )
        conversion_ms = (
            time.perf_counter() - conversion_started
        ) * 1000.0
        if cancelled():
            raise RuntimeError("YUV request cancelled")

        y_view = np.clip(conversion.y_normalized, 0.0, 1.0)
        u_view = np.clip(conversion.u_normalized + 0.5, 0.0, 1.0)
        v_view = np.clip(conversion.v_normalized + 0.5, 0.0, 1.0)
        y_rgb = np.repeat(y_view[..., None], 3, axis=2)
        channel_view = np.stack((y_view, u_view, v_view), axis=-1)
        artifacts = {
            "Y Plane": y_view,
            "U Plane": u_view,
            "V Plane": v_view,
            "RGB Preview": np.clip(conversion.rgb, 0.0, 1.0),
        }
        common = {
            "Pixel Format": metadata.pixel_format,
            "Color Matrix": metadata.color_matrix,
            "Range": metadata.color_range,
            "Chroma Siting": metadata.chroma_siting,
            "Frame": (
                f"{metadata.frame_index + 1}/{metadata.frame_count}"
            ),
            **conversion.diagnostics,
        }
        results = [
            StageResult(
                "yuv_input",
                "YUV Input",
                y_rgb,
                "yuv_rgb",
                read_ms,
                dict(common),
                artifacts,
            ),
            StageResult(
                "chroma_upsampling",
                "Chroma Upsampling",
                channel_view,
                "yuv_rgb",
                conversion_ms * 0.4,
                {**common, "Method": metadata.chroma_upsampling},
                artifacts,
            ),
            StageResult(
                "yuv_to_rgb",
                "YUV to RGB",
                conversion.rgb,
                "yuv_rgb",
                conversion_ms * 0.6,
                dict(common),
                artifacts,
            ),
            StageResult(
                "display_preview",
                "Display Preview",
                np.clip(conversion.rgb, 0.0, 1.0),
                "yuv_rgb",
                0.0,
                dict(common),
                artifacts,
            ),
        ]
        wall_ms = (time.perf_counter() - started) * 1000.0
        return {
            "frame": frame,
            "conversion": conversion,
            "results": results,
            "metrics": {
                "cache_hits": 0,
                "recomputed": 3,
                "elapsed_ms": read_ms + conversion_ms,
                "wall_elapsed_ms": wall_ms,
                "overhead_ms": max(
                    0.0, wall_ms - read_ms - conversion_ms
                ),
                "module_timings": {
                    "yuv_input": read_ms,
                    "chroma_upsampling": conversion_ms * 0.4,
                    "yuv_to_rgb": conversion_ms * 0.6,
                },
                "yuv_cache_key": (
                    str(path),
                    metadata.frame_index,
                    metadata.pixel_format,
                    metadata.color_matrix,
                    metadata.color_range,
                    metadata.chroma_siting,
                    metadata.chroma_upsampling,
                    preview_max_side,
                ),
            },
        }
