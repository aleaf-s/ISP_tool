"""Screenshot AWB simulation. Column-vector CCM, no intermediate clipping.

Screenshots are color-managed sRGB. We assume the player converted BT.709
to sRGB preserving relative linear light (not established for PotPlayer).
Reconstructing video with OETF709, undoing it, retuning, reapplying it and
converting back to sRGB algebraically cancels the paired 709 functions.
The screenshot path evaluates that equivalent transform without redundant
round trips. `retune_bt709` exposes the actual camera-coded reference path.
Sources: https://www.itu.int/rec/R-REC-BT.709/en
https://registry.color.org/rgb-registry/srgb
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np

MAX_GAIN = 65535  # Software safety limit, not a hardware register definition.
MAX_CONDITION = 1000.0


def validate_ccm(value):
    matrix=np.asarray(value,dtype=np.float64)
    if matrix.shape!=(3,3) or not np.all(np.isfinite(matrix)) or np.any(np.abs(matrix)>4):
        raise ValueError('CCM 必须为有限 3×3 矩阵，Float 范围 −4～4')
    condition=np.linalg.cond(matrix)
    if not np.isfinite(condition) or condition>MAX_CONDITION:
        raise ValueError(f'CCM 不可逆或不稳定（条件数 {condition:.3g}，上限 {MAX_CONDITION:g}）')
    return matrix


def _curve(values, threshold, slope, scale, offset, exponent, inverse=False):
    x = np.asarray(values, dtype=np.float32)
    magnitude = np.abs(x)
    result = np.empty_like(x)
    low = magnitude < threshold
    result[low] = magnitude[low] / slope if inverse else magnitude[low] * slope
    result[~low] = ((magnitude[~low] + offset) / scale) ** exponent if inverse else scale * magnitude[~low] ** exponent - offset
    # Signed extension for safe intermediate negative values, not a claim
    # that negative display codes are legal. Clip only at the output boundary.
    return np.copysign(result, x)


def encode_bt709(x):
    return _curve(x, .018, 4.5, 1.099, .099, .45)


def decode_bt709(x):
    return _curve(x, .081, 4.5, 1.099, .099, 1/.45, True)


def encode_srgb(x):
    return _curve(x, .0031308, 12.92, 1.055, .055, 1/2.4)


def decode_srgb(x):
    return _curve(x, .04045, 12.92, 1.055, .055, 2.4, True)


@dataclass(frozen=True)
class RetuneSettings:
    current: tuple = (1024, 1024)
    target: tuple = (1024, 1024)
    ccm: tuple = ((1.,0.,0.),(0.,1.,0.),(0.,0.,1.))
    target_ccm: tuple | None = None  # None preserves the V0.4.46 fixed-CCM API.
    context: tuple = ()  # Immutable source/table signature for applied snapshots.

    @property
    def is_identity(self):
        return self.current==self.target and np.array_equal(self.ccm,self.ccm if self.target_ccm is None else self.target_ccm)

    def transform(self):
        for gains in (self.current, self.target):
            if len(gains) != 2 or any(isinstance(v, bool) or not isinstance(v, (int,np.integer)) or not 1<=v<=MAX_GAIN for v in gains):
                raise ValueError(f'AWB Gain 必须是 1～{MAX_GAIN} 的整数（软件范围）')
        matrix=validate_ccm(self.ccm)
        target=validate_ccm(self.ccm if self.target_ccm is None else self.target_ccm)
        if self.is_identity:
            return np.eye(3,dtype=np.float32)
        ratio=np.array([self.target[0]/self.current[0],1.,self.target[1]/self.current[1]])
        # A M_original = M_target D; never normalize matrix rows.
        result=np.linalg.solve(matrix.T,(target*ratio).T).T
        if not np.all(np.isfinite(result)) or np.linalg.cond(result)>1e8:
            raise ValueError('组合颜色变换不稳定，请检查 Gain 与 CCM')
        return result.astype(np.float32)


def retune_bt709(image, settings):
    transform=settings.transform()
    source=np.asarray(image,dtype=np.float32)
    if settings.is_identity:
        return source.copy()
    return encode_bt709(decode_bt709(source) @ transform.T)


def retune_screenshot(image, settings):
    transform=settings.transform()
    source=np.asarray(image,dtype=np.float32)
    if settings.is_identity:
        return source.copy()
    return encode_srgb(decode_srgb(source) @ transform.T)
