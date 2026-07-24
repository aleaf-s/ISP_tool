from __future__ import annotations

from typing import List, Tuple

from .models import ImageROI


def generate_grid_rois(
    bounds: ImageROI,
    image_shape: Tuple[int, ...],
    rows: int = 4,
    cols: int = 6,
    inset_fraction: float = 0.12,
    bayer_aligned: bool = False,
) -> List[ImageROI]:
    """Generate inset sampling boxes, e.g. a 4×6 ColorChecker grid."""

    bounds.validate(image_shape)
    rows = max(1, int(rows))
    cols = max(1, int(cols))
    inset_fraction = min(0.4, max(0.0, float(inset_fraction)))
    output: List[ImageROI] = []
    for row in range(rows):
        y0 = bounds.y + round(bounds.height * row / rows)
        y1 = bounds.y + round(bounds.height * (row + 1) / rows)
        for col in range(cols):
            x0 = bounds.x + round(bounds.width * col / cols)
            x1 = bounds.x + round(bounds.width * (col + 1) / cols)
            inset_x = round((x1 - x0) * inset_fraction)
            inset_y = round((y1 - y0) * inset_fraction)
            roi = ImageROI(
                x0 + inset_x,
                y0 + inset_y,
                max(1, x1 - x0 - 2 * inset_x),
                max(1, y1 - y0 - 2 * inset_y),
            )
            if bayer_aligned:
                roi = roi.align_for_bayer(image_shape)
            else:
                roi.validate(image_shape)
            output.append(roi)
    return output


def clamp_roi(
    roi: ImageROI,
    image_shape: Tuple[int, ...],
    bayer_aligned: bool = False,
) -> ImageROI:
    """Clamp an edited rectangle to the image and optionally CFA-align it."""

    height, width = image_shape[:2]
    x = min(max(int(roi.x), 0), max(width - 1, 0))
    y = min(max(int(roi.y), 0), max(height - 1, 0))
    roi_width = min(max(int(roi.width), 1), width - x)
    roi_height = min(max(int(roi.height), 1), height - y)
    result = ImageROI(x, y, roi_width, roi_height)
    return (
        result.align_for_bayer(image_shape)
        if bayer_aligned
        else result
    )
