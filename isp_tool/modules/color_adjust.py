from __future__ import annotations

import cv2
import numpy as np

from ..models import ParameterSpec
from .base import ISPModule


class ColorAdjustment(ISPModule):
    module_id = "color_adjustment"
    name = "Saturation / Contrast"
    input_domains = ("rgb",)

    def __init__(self) -> None:
        super().__init__([
            ParameterSpec("brightness", "Brightness", "float", 0.0, -1, 1, 0.01),
            ParameterSpec("contrast", "Contrast", "float", 1.0, 0, 3, 0.01),
            ParameterSpec("saturation", "Saturation", "float", 1.0, 0, 3, 0.01),
            ParameterSpec("hue", "Hue", "float", 0.0, -180, 180, 1),
            ParameterSpec("r_gain", "R Gain", "float", 1.0, 0, 3, 0.01),
            ParameterSpec("g_gain", "G Gain", "float", 1.0, 0, 3, 0.01),
            ParameterSpec("b_gain", "B Gain", "float", 1.0, 0, 3, 0.01),
        ])

    def process(self, image, domain, metadata):
        src = np.asarray(image, dtype=np.float32)
        output = src * np.array([
            self.parameters["r_gain"],
            self.parameters["g_gain"],
            self.parameters["b_gain"],
        ], np.float32)
        output = (output - 0.5) * float(self.parameters["contrast"]) + 0.5
        output += float(self.parameters["brightness"])
        clipped = np.clip(output, 0.0, 1.0)
        hsv = cv2.cvtColor(clipped, cv2.COLOR_RGB2HSV)
        hsv[:, :, 0] = (hsv[:, :, 0] + float(self.parameters["hue"])) % 360.0
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * float(self.parameters["saturation"]), 0, 1)
        output = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)
        return output.astype(np.float32), "rgb", {}

