"""Brightness-indexed chroma gain editor and approximate BT.709 preview.

The 256 exported coefficients follow the supplied decimal TXT layout. Hardware
ISO gain, Y quantisation, rounding and clipping are not inferred from that file.
"""
from dataclasses import dataclass, field
from pathlib import Path
import re

import numpy as np

from .clut import atomic_text


X_DEFAULT = tuple(range(0, 256, 16)) + (255,)
UNITY = 1024


def _validate_values(values):
    if len(values) != 256 or any(type(v) not in (int, np.int64, np.int32) or v < 0 or v > 2047 for v in values):
        raise ValueError('CA 表必须是 256 个 0～2047 的整数')
    return tuple(int(v) for v in values)


def _validate_points(points):
    if not 2 <= len(points) <= 64 or points[0][0] != 0 or points[-1][0] != 255:
        raise ValueError('CA 曲线须包含 X=0、255 两个端点，最多 64 个结点')
    prior = -1
    for x, y in points:
        if type(x) is not int or not prior < x <= 255 or type(y) not in (int, float) or not np.isfinite(y) or not 0 <= y <= 2047:
            raise ValueError('CA 结点 X 须严格递增，Y 须在 0～2047')
        prior = x


def smooth_lut(points):
    """Shape-preserving cubic Hermite interpolation; no overshoot at extrema."""
    points = tuple(points)
    _validate_points(points)
    x = np.asarray([p[0] for p in points], np.float64)
    y = np.asarray([p[1] for p in points], np.float64)
    h = np.diff(x)
    slope = np.diff(y) / h
    tangent = np.zeros(len(x), np.float64)
    if len(x) == 2:
        tangent[:] = slope[0]
    for i in range(1, len(x)-1):
        a, b = slope[i-1], slope[i]
        if a*b > 0:
            w1, w2 = 2*h[i]+h[i-1], h[i]+2*h[i-1]
            tangent[i] = (w1+w2)/(w1/a+w2/b)
    if len(x) > 2:
        for index in (0, -1):
            a, b = slope[index if index == 0 else -1], slope[1 if index == 0 else -2]
            hh, neighbor = h[index if index == 0 else -1], h[1 if index == 0 else -2]
            t = ((2*hh+neighbor)*a-hh*b)/(hh+neighbor)
            if t*a <= 0: t = 0
            elif a*b < 0 and abs(t) > 3*abs(a): t = 3*a
            tangent[index] = t
    query = np.arange(256, dtype=np.float64)
    segment = np.minimum(np.searchsorted(x, query, side='right')-1, len(x)-2)
    span = h[segment]
    t = (query-x[segment])/span
    values = ((2*t**3-3*t**2+1)*y[segment]
              +(t**3-2*t**2+t)*span*tangent[segment]
              +(-2*t**3+3*t**2)*y[segment+1]
              +(t**3-t**2)*span*tangent[segment+1])
    return _validate_values(tuple(np.rint(np.clip(values, 0, 2047)).astype(int)))


@dataclass(frozen=True)
class CACurve:
    points: tuple = field(default_factory=lambda: tuple((x, UNITY) for x in X_DEFAULT))
    values: tuple = field(default_factory=lambda: (UNITY,)*256)

    def __post_init__(self):
        _validate_points(self.points)
        _validate_values(self.values)

    @classmethod
    def from_values(cls, values):
        values = _validate_values(values)
        return cls(tuple((x, values[x]) for x in X_DEFAULT), values)

    def set_point(self, x, y):
        if type(x) is not int or not 0 <= x <= 255 or type(y) is not int or not 0 <= y <= 2047:
            raise ValueError('X 为 0～255 整数，Y 为 0～2047 整数')
        points = dict(self.points)
        if x not in points and len(points) >= 64:
            raise ValueError('CA 控制点最多 64 个')
        if points.get(x) == y:
            return self
        points[x] = y
        items = tuple(sorted(points.items()))
        return CACurve(items, smooth_lut(items))

    def remove_point(self, x):
        if x in (0, 255): raise ValueError('不能删除曲线端点')
        if x not in dict(self.points): raise ValueError('未选中控制点')
        items = tuple(p for p in self.points if p[0] != x)
        return CACurve(items, smooth_lut(items))


@dataclass
class CAState:
    curve: CACurve = field(default_factory=CACurve)
    applied: CACurve = field(default_factory=CACurve)
    selected_x: int = 128
    drafts: object = None
    undo_stack: list = field(default_factory=list)
    redo_stack: list = field(default_factory=list)

    def replace(self, curve):
        if curve == self.curve: return False
        self.undo_stack.append(self.curve)
        if len(self.undo_stack) > 40: self.undo_stack.pop(0)
        self.redo_stack.clear()
        self.curve = curve
        return True

    def travel(self, redo=False):
        source, target = (self.redo_stack, self.undo_stack) if redo else (self.undo_stack, self.redo_stack)
        if not source: return False
        target.append(self.curve)
        self.curve = source.pop()
        return True


def load_ca_text(path):
    path = Path(path)
    if path.stat().st_size > 16*1024: raise ValueError('CA 文件超过 16 KiB')
    text = path.read_text(encoding='utf-8-sig')
    if not re.fullmatch(r'\s*\d+(?:\s*,\s*\d+){255}\s*,?\s*', text):
        raise ValueError('CA TXT 需要 256 个逗号分隔的十进制整数')
    return CACurve.from_values(tuple(int(item) for item in text.strip().rstrip(',').split(',')))


def export_ca_text(path, curve):
    values = _validate_values(curve.values)
    text = '\n'.join(','.join(f'{value:10d}' for value in values[row:row+16])
                     + (',' if row < 240 else '') for row in range(0, 256, 16))
    atomic_text(path, text, newline='')


def apply_ca(image, curve):
    """Software approximation: BT.709 Y selects gain/1024 applied to UV.

    ISO gain is held at unity. The RGB input/output are encoded sRGB as in the
    manual grading workspace; clipping is done only after Y/chroma recombination.
    """
    rgb = np.asarray(image, dtype=np.float32)
    if rgb.ndim != 3 or rgb.shape[-1] != 3 or not np.all(np.isfinite(rgb)):
        raise ValueError('CA 预览需要有限的 RGB 图像')
    y = np.sum(rgb * np.array((.2126, .7152, .0722), np.float32), axis=-1)
    pos = np.clip(y*255, 0, 255)
    lo = np.floor(pos).astype(np.int16)
    hi = np.minimum(lo+1, 255)
    table = np.asarray(curve.values, np.float32)
    gain = (table[lo] + (table[hi]-table[lo])*(pos-lo))/UNITY
    out = np.clip(y[..., None] + (rgb-y[..., None])*gain[..., None], 0, 1)
    return out.astype(np.float32)
