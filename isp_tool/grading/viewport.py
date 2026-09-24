"""Full-resolution visible-region processing, independent of Tk.

Process original pixels before display resampling, as full-size export does.
Only the visible crop is computed; float working buffers are limited to rows.
"""
import math
from concurrent.futures import CancelledError
import numpy as np
from PIL import Image
from .model import raster8


def render_viewport(document, process, proxy_size, zoom, offset, size, cancel):
    width, height = size
    ph, pw = document.rgb.shape[:2]
    sx, sy = zoom * proxy_size[0] / pw, zoom * proxy_size[1] / ph
    ox, oy = offset
    x0 = max(0, math.floor(-ox / sx))
    y0 = max(0, math.floor(-oy / sy))
    x1 = min(pw, math.ceil((width - ox) / sx))
    y1 = min(ph, math.ceil((height - oy) / sy))
    before = Image.new('RGB', size, (112, 112, 112))
    after = before.copy()
    if x1 <= x0 or y1 <= y0:
        return before, after
    crops = [np.empty((y1-y0, x1-x0, 3), np.uint8) for _ in range(2)]
    for y in range(y0, y1, 128):
        if cancel.is_set():
            raise CancelledError()
        end = min(y+128, y1)
        source = document.rgb[y:end, x0:x1]
        output = process(source)
        if not np.all(np.isfinite(output)):
            raise ValueError('预览输出存在 NaN/Infinity')
        # Match PNG export's clipping/quantization before resampling.
        for destination, pixels in zip(crops, (source, output)):
            pixels = raster8(pixels)
            if document.alpha is not None:
                alpha = document.alpha[y:end, x0:x1, None]
                pixels = np.rint(pixels*alpha + (1-alpha)*112).astype(np.uint8)
            destination[y-y0:end-y0] = pixels
    resample = Image.Resampling.NEAREST if min(sx, sy) >= 1 else Image.Resampling.LANCZOS
    target_size = (max(1, round((x1-x0)*sx)), max(1, round((y1-y0)*sy)))
    position = (round(ox+x0*sx), round(oy+y0*sy))
    for view, crop in zip((before, after), crops):
        if cancel.is_set():
            raise CancelledError()
        view.paste(Image.fromarray(crop).resize(target_size, resample), position)
    return before, after
