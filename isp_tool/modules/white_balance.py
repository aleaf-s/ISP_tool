from __future__ import annotations

import numpy as np

from ..bayer import channel_positions
from ..models import ParameterSpec
from .base import ISPModule


class WhiteBalance(ISPModule):
    module_id = "white_balance"
    name = "White Balance"
    input_domains = ("bayer", "rgb")

    def __init__(self) -> None:
        super().__init__([
            ParameterSpec("r_gain", "R Gain", "float", 2.0, 0, 8, 0.01),
            ParameterSpec("gr_gain", "Gr Gain", "float", 1.0, 0, 8, 0.01),
            ParameterSpec("gb_gain", "Gb Gain", "float", 1.0, 0, 8, 0.01),
            ParameterSpec("b_gain", "B Gain", "float", 1.7, 0, 8, 0.01),
            ParameterSpec("exposure_gain", "Exposure Gain", "float", 1.0, 0, 8, 0.01),
            ParameterSpec("gain_limit", "Gain Limit", "float", 8.0, 1, 16, 0.1),
        ])

    def process(self, image, domain, metadata):
        src = np.asarray(image, dtype=np.float32)
        limit = float(self.parameters["gain_limit"])
        exposure = min(float(self.parameters["exposure_gain"]), limit)
        if domain == "bayer":
            output = src.copy()
            gains = {
                "R": self.parameters["r_gain"],
                "Gr": self.parameters["gr_gain"],
                "Gb": self.parameters["gb_gain"],
                "B": self.parameters["b_gain"],
            }
            for name, (y, x) in channel_positions(metadata.bayer_pattern).items():
                gain = min(float(gains[name]) * exposure, limit)
                output[y::2, x::2] *= gain
        else:
            green = 0.5 * (float(self.parameters["gr_gain"]) + float(self.parameters["gb_gain"]))
            gains = np.array([
                self.parameters["r_gain"], green, self.parameters["b_gain"]
            ], np.float32)
            output = src * np.minimum(gains * exposure, limit)
        return output.astype(np.float32), domain, {"最大输出": float(output.max())}

