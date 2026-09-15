"""D65 Lab colour guide and a true fixed-L* sRGB gamut section."""
from functools import lru_cache
import numpy as np
import colour
from .delta_e import D65_XY, SRGB_TO_XYZ


def lab_to_linear_srgb(lab):
    xyz = colour.Lab_to_XYZ(np.asarray(lab, dtype=np.float64), illuminant=D65_XY)
    return np.asarray(xyz) @ np.linalg.inv(SRGB_TO_XYZ).T


@lru_cache(maxsize=8)
def srgb_ab_boundary(lightness=70.0, samples=361):
    """Intersect radial rays with the RGB cube at the requested L*.

    Values remain unclipped while testing the RGB cube. The returned closed
    contour is a section, not a projection or a per-patch gamut verdict.
    """
    if not 0 < lightness < 100 or samples < 32:
        raise ValueError("L* must be in (0,100); samples >= 32")
    theta = np.linspace(0, 2*np.pi, samples)
    directions = np.stack((np.cos(theta), np.sin(theta)), axis=-1)
    low, high = np.zeros(samples), np.full(samples, 220.0)
    for _ in range(32):
        radius = (low + high) / 2
        lab = np.column_stack((np.full(samples, lightness), directions * radius[:, None]))
        rgb = lab_to_linear_srgb(lab)
        inside = np.all((rgb >= 0) & (rgb <= 1), axis=-1)
        low = np.where(inside, radius, low)
        high = np.where(inside, high, radius)
    boundary = directions * low[:, None]
    boundary[-1] = boundary[0]
    boundary.setflags(write=False)
    return boundary


@lru_cache(maxsize=8)
def ab_background(amin, amax, bmin, bmax, lightness=70.0):
    from ..preview import encode_display_uint8
    aa, bb = np.meshgrid(np.linspace(amin, amax, 240), np.linspace(bmax, bmin, 280))
    lab = np.stack((np.full_like(aa, lightness), aa, bb), axis=-1)
    rgb = encode_display_uint8(lab_to_linear_srgb(lab))
    rgb.setflags(write=False)
    return rgb
