from __future__ import annotations

from typing import Any, Dict, Tuple

import numpy as np

from ..bayer import channel_positions
from ..models import ParameterSpec, RawMetadata
from .base import ISPModule


class BlackLevelCorrection(ISPModule):
    module_id = "black_level_correction"
    name = "Black Level Correction"
    input_domains = ("bayer",)

    def __init__(self) -> None:
        specs = [
            ParameterSpec("r", "R Black", "float", 64.0, 0, 4095, 1),
            ParameterSpec("gr", "Gr Black", "float", 64.0, 0, 4095, 1),
            ParameterSpec("gb", "Gb Black", "float", 64.0, 0, 4095, 1),
            ParameterSpec("b", "B Black", "float", 64.0, 0, 4095, 1),
            ParameterSpec("global_offset", "Global Offset", "float", 0.0, -512, 512, 1),
            ParameterSpec("output_min", "Output Min", "float", 0.0, 0, 1, 0.001),
            ParameterSpec("output_max", "Output Max", "float", 1.0, 0, 2, 0.001),
        ]
        super().__init__(specs)

    def sync_metadata(self, metadata: RawMetadata) -> None:
        for key, value in zip(("r", "gr", "gb", "b"), metadata.black_level):
            self.parameters[key] = float(value)

    def process(self, image, domain, metadata) -> Tuple[np.ndarray, str, Dict[str, Any]]:
        src = np.asarray(image, dtype=np.float32)
        output = np.empty_like(src)
        clipped_low = 0
        total = src.size
        black_map = {
            "R": self.parameters["r"],
            "Gr": self.parameters["gr"],
            "Gb": self.parameters["gb"],
            "B": self.parameters["b"],
        }
        offset = float(self.parameters["global_offset"])
        for name, (y, x) in channel_positions(metadata.bayer_pattern).items():
            black = float(black_map[name]) + offset
            denominator = max(float(metadata.white_level) - black, 1e-6)
            plane = (src[y::2, x::2] - black) / denominator
            clipped_low += int(np.count_nonzero(plane < self.parameters["output_min"]))
            output[y::2, x::2] = plane
        output = np.clip(output, self.parameters["output_min"], self.parameters["output_max"])
        return output, "bayer", {"负值截断": clipped_low, "截断比例": clipped_low / max(total, 1)}

