from __future__ import annotations

from typing import Dict

import numpy as np

from ..models import RawMetadata
from ..preview import display_rgb


def compute_histogram(
    image: np.ndarray,
    domain: str,
    metadata: RawMetadata,
    bins: int = 256,
) -> Dict[str, np.ndarray]:
    rgb = display_rgb(image, domain, metadata)
    result = {}
    for index, name in enumerate(("R", "G", "B")):
        result[name] = np.histogram(rgb[:, :, index], bins=bins, range=(0, 1))[0]
    luminance = np.sum(
        rgb * np.array([0.2126, 0.7152, 0.0722], np.float32), axis=2
    )
    result["Y"] = np.histogram(luminance, bins=bins, range=(0, 1))[0]
    return result

