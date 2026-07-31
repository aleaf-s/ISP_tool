from __future__ import annotations

from ..backends import get_default_backend
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
                choices=(
                    "Nearest Neighbor",
                    "Bilinear",
                    "Adaptive Interpolation",
                    "Constant Color Difference",
                ),
            ),
            ParameterSpec("false_color_suppression", "False Color Suppression", "float", 0.0, 0, 1, 0.01),
        ])

    def process(self, image, domain, metadata):
        backend = self.processing_backend or get_default_backend()
        kernel_result = backend.demosaic(
            image,
            metadata.bayer_pattern,
            self.parameters["algorithm"],
        )
        output = kernel_result.image
        strength = float(self.parameters["false_color_suppression"])
        if strength > 0:
            import cv2
            import numpy as np
            luminance = np.mean(output, axis=2, keepdims=True)
            chroma = output - luminance
            smooth = cv2.GaussianBlur(chroma, (0, 0), 0.7)
            output = luminance + (1.0 - strength) * chroma + strength * smooth
        return output, "rgb", {
            "算法": self.parameters["algorithm"],
            "Backend": kernel_result.implementation,
        }
