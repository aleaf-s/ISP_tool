from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

import numpy as np

from .bayer import channel_positions
from .models import ImageROI, RawMetadata, StageDataState


Point = Tuple[int, int]


@dataclass(frozen=True)
class NeighborhoodStatistics:
    minimum: float
    maximum: float
    mean: float
    median: float
    stddev: float
    count: int


@dataclass(frozen=True)
class PixelSample:
    source_x: int
    source_y: int
    local_x: int
    local_y: int
    domain: str
    encoding: str
    code_max: int
    normalized: bool
    neighborhood_size: int
    center_channel: str = ""
    center_values: Dict[str, float] = field(default_factory=dict)
    absolute_values: Dict[str, int] = field(default_factory=dict)
    display_values: Dict[str, int] = field(default_factory=dict)
    statistics: Dict[str, NeighborhoodStatistics] = field(
        default_factory=dict
    )
    grid: Tuple[Tuple[str, ...], ...] = ()
    extra: Dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class LineProfile:
    source_start: Point
    source_end: Point
    local_start: Point
    local_end: Point
    domain: str
    encoding: str
    code_max: int
    distances: np.ndarray
    coordinates: np.ndarray
    channels: Dict[str, np.ndarray]

    @property
    def sample_count(self) -> int:
        return int(self.coordinates.shape[0])

    @property
    def length(self) -> float:
        return float(self.distances[-1]) if self.distances.size else 0.0


class ImageCoordinateMapper:
    """Pure coordinate transforms shared by canvas analysis tools."""

    @staticmethod
    def canvas_to_display(
        canvas_x: int,
        canvas_y: int,
        transform: Tuple[float, float, float, int, int],
    ) -> Optional[Point]:
        origin_x, origin_y, zoom, width, height = transform
        x = int((canvas_x - origin_x) / max(float(zoom), 1e-9))
        y = int((canvas_y - origin_y) / max(float(zoom), 1e-9))
        if 0 <= x < int(width) and 0 <= y < int(height):
            return x, y
        return None

    @staticmethod
    def display_to_source(
        point: Point,
        display_shape: Tuple[int, ...],
        source_shape: Tuple[int, ...],
        roi: Optional[ImageROI] = None,
    ) -> Point:
        x, y = map(int, point)
        if roi is not None:
            return x + roi.x, y + roi.y
        display_h, display_w = display_shape[:2]
        source_h, source_w = source_shape[:2]
        return (
            min(source_w - 1, max(0, int(x * source_w / display_w))),
            min(source_h - 1, max(0, int(y * source_h / display_h))),
        )

    @staticmethod
    def source_to_display(
        point: Point,
        display_shape: Tuple[int, ...],
        source_shape: Tuple[int, ...],
        roi: Optional[ImageROI] = None,
    ) -> Optional[Point]:
        source_x, source_y = map(int, point)
        display_h, display_w = display_shape[:2]
        source_h, source_w = source_shape[:2]
        if roi is not None:
            x, y = source_x - roi.x, source_y - roi.y
        else:
            if not (0 <= source_x < source_w and 0 <= source_y < source_h):
                return None
            x = int(source_x * display_w / source_w)
            y = int(source_y * display_h / source_h)
        if 0 <= x < display_w and 0 <= y < display_h:
            return x, y
        return None


def _stats(values: np.ndarray) -> NeighborhoodStatistics:
    array = np.asarray(values, dtype=np.float64).reshape(-1)
    array = array[np.isfinite(array)]
    if not array.size:
        return NeighborhoodStatistics(0, 0, 0, 0, 0, 0)
    return NeighborhoodStatistics(
        float(np.min(array)),
        float(np.max(array)),
        float(np.mean(array)),
        float(np.median(array)),
        float(np.std(array)),
        int(array.size),
    )


class PixelSamplingService:
    """Sample Bayer/RGB/YUV stages in absolute code-value space."""

    @staticmethod
    def _size(value: int) -> int:
        size = max(1, min(int(value), 15))
        return size if size % 2 else size + 1

    @staticmethod
    def _bounds(
        x: int, y: int, shape: Tuple[int, ...], size: int
    ) -> Tuple[int, int, int, int]:
        height, width = shape[:2]
        radius = size // 2
        return (
            max(0, x - radius),
            max(0, y - radius),
            min(width, x + radius + 1),
            min(height, y + radius + 1),
        )

    def sample(
        self,
        image: np.ndarray,
        domain: str,
        metadata: RawMetadata,
        local_point: Point,
        source_point: Optional[Point] = None,
        *,
        data_state: Optional[StageDataState] = None,
        neighborhood_size: int = 5,
        yuv_frame=None,
        yuv_rgb: Optional[np.ndarray] = None,
    ) -> PixelSample:
        src = np.asarray(image, dtype=np.float32)
        x, y = map(int, local_point)
        if not (0 <= y < src.shape[0] and 0 <= x < src.shape[1]):
            raise IndexError("Pixel sample is outside the stage image")
        source_x, source_y = source_point or (x, y)
        size = self._size(neighborhood_size)
        if yuv_frame is not None:
            return self._sample_yuv(
                source_x,
                source_y,
                x,
                y,
                metadata,
                size,
                yuv_frame,
                yuv_rgb,
            )
        state = data_state or StageDataState.for_input(domain, metadata)
        if domain == "bayer":
            return self._sample_bayer(
                src, x, y, source_x, source_y, metadata, state, size
            )
        return self._sample_rgb(
            src, x, y, source_x, source_y, state, size
        )

    @staticmethod
    def _line_coordinates(start: Point, end: Point) -> np.ndarray:
        x0, y0 = map(int, start)
        x1, y1 = map(int, end)
        count = max(abs(x1 - x0), abs(y1 - y0)) + 1
        coordinates = np.rint(np.column_stack((
            np.linspace(x0, x1, count, dtype=np.float64),
            np.linspace(y0, y1, count, dtype=np.float64),
        ))).astype(np.int32)
        if coordinates.shape[0] > 1:
            keep = np.ones(coordinates.shape[0], dtype=bool)
            keep[1:] = np.any(coordinates[1:] != coordinates[:-1], axis=1)
            coordinates = coordinates[keep]
        return coordinates

    def sample_line(
        self,
        image: np.ndarray,
        domain: str,
        metadata: RawMetadata,
        local_start: Point,
        local_end: Point,
        source_start: Optional[Point] = None,
        source_end: Optional[Point] = None,
        *,
        data_state: Optional[StageDataState] = None,
        yuv_frame=None,
    ) -> LineProfile:
        """Sample one rasterized line without changing pipeline data."""
        src = np.asarray(image, dtype=np.float32)
        local = self._line_coordinates(local_start, local_end)
        if not local.size:
            raise ValueError("Line profile requires at least one point")
        height, width = src.shape[:2]
        if (
            np.any(local[:, 0] < 0)
            or np.any(local[:, 0] >= width)
            or np.any(local[:, 1] < 0)
            or np.any(local[:, 1] >= height)
        ):
            raise IndexError("Line profile is outside the stage image")
        source_start = source_start or tuple(map(int, local_start))
        source_end = source_end or tuple(map(int, local_end))
        source = np.rint(np.column_stack((
            np.linspace(
                source_start[0], source_end[0], local.shape[0],
                dtype=np.float64,
            ),
            np.linspace(
                source_start[1], source_end[1], local.shape[0],
                dtype=np.float64,
            ),
        ))).astype(np.int32)
        delta = np.diff(source.astype(np.float64), axis=0)
        distances = np.concatenate((
            np.zeros(1, dtype=np.float64),
            np.cumsum(np.hypot(delta[:, 0], delta[:, 1])),
        ))
        if yuv_frame is not None:
            channels = self._sample_yuv_line(source, yuv_frame)
            bit_depth = max(1, min(int(metadata.bit_depth), 30))
            return LineProfile(
                tuple(map(int, source_start)), tuple(map(int, source_end)),
                tuple(map(int, local_start)), tuple(map(int, local_end)),
                "yuv", "YUV Native Codes", (1 << bit_depth) - 1,
                distances, source, channels,
            )
        state = data_state or StageDataState.for_input(domain, metadata)
        x = local[:, 0]
        y = local[:, 1]
        if domain == "bayer":
            if src.ndim != 2:
                raise ValueError("Bayer line sampling requires a 2D image")
            codes = src[y, x].astype(np.float64) * state.absolute_scale
            channels = {
                name: np.full(local.shape[0], np.nan, dtype=np.float64)
                for name in ("R", "Gr", "Gb", "B")
            }
            positions = channel_positions(metadata.bayer_pattern)
            for name, (row, column) in positions.items():
                mask = (
                    (source[:, 1] % 2 == row)
                    & (source[:, 0] % 2 == column)
                )
                channels[name][mask] = codes[mask]
        else:
            if src.ndim != 3 or src.shape[2] < 3:
                raise ValueError("RGB line sampling requires an H×W×3 image")
            codes = src[y, x, :3].astype(np.float64) * state.absolute_scale
            channels = {
                name: codes[:, index]
                for index, name in enumerate(("R", "G", "B"))
            }
        return LineProfile(
            tuple(map(int, source_start)), tuple(map(int, source_end)),
            tuple(map(int, local_start)), tuple(map(int, local_end)),
            domain, state.encoding, state.code_max,
            distances, source, channels,
        )

    @staticmethod
    def _sample_yuv_line(
        source: np.ndarray, frame
    ) -> Dict[str, np.ndarray]:
        height, width = frame.shape
        if (
            np.any(source[:, 0] < 0)
            or np.any(source[:, 0] >= width)
            or np.any(source[:, 1] < 0)
            or np.any(source[:, 1] >= height)
        ):
            raise IndexError("YUV line profile is outside the source frame")
        values = np.asarray(
            [frame.sample(int(x), int(y)) for x, y in source],
            dtype=np.float64,
        )
        return {
            name: values[:, index]
            for index, name in enumerate(("Y", "U", "V"))
        }

    def _sample_bayer(
        self,
        src: np.ndarray,
        x: int,
        y: int,
        source_x: int,
        source_y: int,
        metadata: RawMetadata,
        state: StageDataState,
        size: int,
    ) -> PixelSample:
        if src.ndim != 2:
            raise ValueError("Bayer sampling requires a 2D image")
        x0, y0, x1, y1 = self._bounds(x, y, src.shape, size)
        values = src[y0:y1, x0:x1]
        absolute = np.rint(values * state.absolute_scale).astype(np.int64)
        positions = channel_positions(metadata.bayer_pattern)
        by_position = {position: name for name, position in positions.items()}
        stats: Dict[str, NeighborhoodStatistics] = {}
        grid = []
        channel_values: Dict[str, list] = {name: [] for name in positions}
        for row_index, local_y in enumerate(range(y0, y1)):
            row = []
            global_y = source_y + local_y - y
            for column_index, local_x in enumerate(range(x0, x1)):
                global_x = source_x + local_x - x
                channel = by_position[(global_y % 2, global_x % 2)]
                code = int(absolute[row_index, column_index])
                channel_values[channel].append(code)
                row.append(f"{channel}:{code}")
            grid.append(tuple(row))
        for name in ("R", "Gr", "Gb", "B"):
            stats[name] = _stats(np.asarray(channel_values[name]))
        center_channel = by_position[(source_y % 2, source_x % 2)]
        raw_value = float(src[y, x])
        absolute_value = int(round(raw_value * state.absolute_scale))
        return PixelSample(
            source_x,
            source_y,
            x,
            y,
            "bayer",
            state.encoding,
            state.code_max,
            state.normalized,
            size,
            center_channel,
            {center_channel: raw_value},
            {center_channel: absolute_value},
            {center_channel: int(np.clip(absolute_value, 0, state.code_max))},
            stats,
            tuple(grid),
            {"bayer_pattern": metadata.bayer_pattern},
        )

    def _sample_rgb(
        self,
        src: np.ndarray,
        x: int,
        y: int,
        source_x: int,
        source_y: int,
        state: StageDataState,
        size: int,
    ) -> PixelSample:
        if src.ndim != 3 or src.shape[2] < 3:
            raise ValueError("RGB sampling requires an H×W×3 image")
        x0, y0, x1, y1 = self._bounds(x, y, src.shape, size)
        values = src[y0:y1, x0:x1, :3]
        absolute = np.rint(values * state.absolute_scale).astype(np.int64)
        center = src[y, x, :3]
        center_absolute = np.rint(
            center * state.absolute_scale
        ).astype(np.int64)
        center_display = np.rint(
            np.clip(center / state.display_divisor, 0.0, 1.0)
            * state.code_max
        ).astype(np.int64)
        names = ("R", "G", "B")
        stats = {
            name: _stats(absolute[..., index])
            for index, name in enumerate(names)
        }
        grid = tuple(
            tuple(
                f"({int(pixel[0])},{int(pixel[1])},{int(pixel[2])})"
                for pixel in row
            )
            for row in absolute
        )
        return PixelSample(
            source_x,
            source_y,
            x,
            y,
            "rgb",
            state.encoding,
            state.code_max,
            state.normalized,
            size,
            "RGB",
            {name: float(center[index]) for index, name in enumerate(names)},
            {name: int(center_absolute[index]) for index, name in enumerate(names)},
            {name: int(center_display[index]) for index, name in enumerate(names)},
            stats,
            grid,
        )

    def _sample_yuv(
        self,
        source_x: int,
        source_y: int,
        local_x: int,
        local_y: int,
        metadata: RawMetadata,
        size: int,
        frame,
        yuv_rgb: Optional[np.ndarray],
    ) -> PixelSample:
        height, width = frame.shape
        if not (0 <= source_x < width and 0 <= source_y < height):
            raise IndexError("YUV sample is outside the source frame")
        x0, y0, x1, y1 = self._bounds(
            source_x, source_y, (height, width), size
        )
        native = np.empty((y1 - y0, x1 - x0, 3), dtype=np.float32)
        for row, yy in enumerate(range(y0, y1)):
            for column, xx in enumerate(range(x0, x1)):
                native[row, column] = frame.sample(xx, yy)
        center_codes = frame.sample(source_x, source_y)
        names = ("Y", "U", "V")
        stats = {
            name: _stats(native[..., index])
            for index, name in enumerate(names)
        }
        grid = tuple(
            tuple(
                f"({int(pixel[0])},{int(pixel[1])},{int(pixel[2])})"
                for pixel in row
            )
            for row in native
        )
        bit_depth = max(1, min(int(metadata.bit_depth), 30))
        code_max = (1 << bit_depth) - 1
        extra: Dict[str, object] = {}
        if yuv_rgb is not None:
            rgb = np.asarray(yuv_rgb, dtype=np.float32)
            if (
                0 <= local_y < rgb.shape[0]
                and 0 <= local_x < rgb.shape[1]
                and rgb.ndim == 3
            ):
                value = rgb[local_y, local_x, :3]
                extra["rgb_absolute"] = tuple(
                    int(round(float(item) * code_max)) for item in value
                )
                extra["rgb_display"] = tuple(
                    int(round(float(item) * code_max))
                    for item in np.clip(value, 0.0, 1.0)
                )
        return PixelSample(
            source_x,
            source_y,
            local_x,
            local_y,
            "yuv",
            "YUV Native Codes",
            code_max,
            False,
            size,
            "YUV",
            {name: float(center_codes[index]) for index, name in enumerate(names)},
            {name: int(center_codes[index]) for index, name in enumerate(names)},
            {name: int(np.clip(center_codes[index], 0, code_max)) for index, name in enumerate(names)},
            stats,
            grid,
            extra,
        )


def format_pixel_status(
    sample: PixelSample,
    *,
    gray_pick_mode: bool = False,
    yuv_metadata=None,
) -> str:
    prefix = f"x={sample.source_x}, y={sample.source_y} · "
    gray = " · 点击此处估算白平衡" if gray_pick_mode else ""
    if sample.domain == "yuv":
        yuv = tuple(sample.absolute_values[name] for name in ("Y", "U", "V"))
        rgb_absolute = sample.extra.get("rgb_absolute", (0, 0, 0))
        rgb_display = sample.extra.get("rgb_display", (0, 0, 0))
        detail = ""
        if yuv_metadata is not None:
            detail = (
                f" · {yuv_metadata.pixel_format} · "
                f"{yuv_metadata.color_matrix} · {yuv_metadata.color_range}"
            )
        return (
            f"{prefix}YUV={yuv} · RGB裁剪前≈{rgb_absolute} · "
            f"显示RGB={rgb_display}/{sample.code_max}{detail}"
        )
    if sample.domain == "bayer":
        channel = sample.center_channel
        raw_value = sample.center_values[channel]
        absolute = sample.absolute_values[channel]
        if sample.normalized:
            value = (
                f"{sample.code_max.bit_length()}-bit计算值≈{absolute} · "
                f"显示值={sample.display_values[channel]}/{sample.code_max}"
            )
        else:
            value = (
                f"DN={raw_value:.2f} · "
                f"{sample.code_max.bit_length()}-bit范围=0…{sample.code_max}"
            )
        pattern = sample.extra.get("bayer_pattern", "")
        return (
            f"{prefix}RAW {channel} {value} · "
            f"{pattern} CFA（未去马赛克）{gray}"
        )
    absolute = tuple(sample.absolute_values[name] for name in ("R", "G", "B"))
    display = tuple(sample.display_values[name] for name in ("R", "G", "B"))
    return (
        f"{prefix}RGB裁剪前≈{absolute} · "
        f"显示RGB={display}/{sample.code_max}{gray}"
    )
