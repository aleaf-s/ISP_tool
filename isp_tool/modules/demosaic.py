from __future__ import annotations

from ..bayer import bayer_to_rgb_bilinear, bayer_to_rgb_edge_aware
from ..models import ParameterSpec
from .base import ISPModule


class Demosaic(ISPModule):
    module_id = "demosaic"
    name = "Demosaic"
    input_domains = ("bayer",)

    def __init__(self) -> None:
        super().__init__([
            ParameterSpec(
                "algorithm", "Algorithm", "choice", "Bilinear",
                choices=("Bilinear", "Edge-aware"),
            ),
            ParameterSpec("false_color_suppression", "False Color Suppression", "float", 0.0, 0, 1, 0.01),
        ])

    def process(self, image, domain, metadata):
        if self.parameters["algorithm"] == "Edge-aware":
            output = bayer_to_rgb_edge_aware(image, metadata.bayer_pattern)
        else:
            output = bayer_to_rgb_bilinear(image, metadata.bayer_pattern)
        strength = float(self.parameters["false_color_suppression"])
        if strength > 0:
            import cv2
            import numpy as np
            luminance = np.mean(output, axis=2, keepdims=True)
            chroma = output - luminance
            smooth = cv2.GaussianBlur(chroma, (0, 0), 0.7)
            output = luminance + (1.0 - strength) * chroma + strength * smooth
        return output, "rgb", {"算法": self.parameters["algorithm"]}

