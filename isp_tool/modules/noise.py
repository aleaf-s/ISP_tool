from __future__ import annotations

import cv2
import numpy as np

from ..models import ParameterSpec
from .base import ISPModule


class NoiseReduction(ISPModule):
    module_id = "noise_reduction"
    name = "Noise Reduction"
    input_domains = ("rgb",)

    def __init__(self) -> None:
        super().__init__([
            ParameterSpec("algorithm", "Algorithm", "choice", "Bilateral", choices=("Gaussian", "Bilateral")),
            ParameterSpec("spatial_strength", "Spatial Strength", "float", 0.0, 0, 1, 0.01),
            ParameterSpec("chroma_strength", "Chroma Strength", "float", 0.0, 0, 1, 0.01),
            ParameterSpec("edge_protection", "Edge Protection", "float", 0.5, 0, 1, 0.01),
            ParameterSpec("radius", "Radius", "int", 3, 1, 9, 2),
        ])

    def process(self, image, domain, metadata):
        src = np.asarray(image, dtype=np.float32)
        strength = float(self.parameters["spatial_strength"])
        radius = int(self.parameters["radius"])
        if radius % 2 == 0:
            radius += 1
        if strength <= 0 and float(self.parameters["chroma_strength"]) <= 0:
            return src.copy(), "rgb", {"算法": "Bypass strength=0"}
        if self.parameters["algorithm"] == "Gaussian":
            filtered = cv2.GaussianBlur(src, (radius, radius), 0)
        else:
            sigma_color = 0.02 + 0.18 * strength
            filtered = cv2.bilateralFilter(src, radius, sigma_color, max(radius, 1))
        edge = float(self.parameters["edge_protection"])
        mix = strength * (1.0 - 0.7 * edge)
        output = src * (1.0 - mix) + filtered * mix
        chroma_strength = float(self.parameters["chroma_strength"])
        if chroma_strength > 0:
            y = np.sum(output * np.array([0.2126, 0.7152, 0.0722], np.float32), axis=2, keepdims=True)
            chroma = output - y
            chroma_smooth = cv2.GaussianBlur(chroma, (radius, radius), 0)
            output = y + chroma * (1.0 - chroma_strength) + chroma_smooth * chroma_strength
        return output.astype(np.float32), "rgb", {"算法": self.parameters["algorithm"]}

