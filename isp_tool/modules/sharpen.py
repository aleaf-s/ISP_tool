from __future__ import annotations

import cv2
import numpy as np

from ..models import ParameterSpec
from .base import ISPModule


class Sharpen(ISPModule):
    module_id = "sharpen"
    name = "Sharpen"
    input_domains = ("rgb",)

    def __init__(self) -> None:
        super().__init__([
            ParameterSpec("strength", "Sharpen Strength", "float", 0.0, 0, 3, 0.01),
            ParameterSpec("radius", "Radius", "float", 1.0, 0.1, 5, 0.1),
            ParameterSpec("threshold", "Threshold", "float", 0.01, 0, 0.2, 0.001),
            ParameterSpec("halo_suppression", "Halo Suppression", "float", 0.5, 0, 1, 0.01),
        ])

    def process(self, image, domain, metadata):
        src = np.asarray(image, dtype=np.float32)
        strength = float(self.parameters["strength"])
        if strength <= 0:
            empty = np.zeros(src.shape[:2], dtype=np.uint8)
            return src, "rgb", {"边缘像素比例": 0.0}, {"Sharpen Edge Mask": empty}
        blur = cv2.GaussianBlur(src, (0, 0), float(self.parameters["radius"]))
        detail = src - blur
        magnitude = np.max(np.abs(detail), axis=2, keepdims=True)
        mask = magnitude >= float(self.parameters["threshold"])
        limit = 0.25 * (1.0 - 0.8 * float(self.parameters["halo_suppression"]))
        detail = np.clip(detail, -limit, limit)
        output = src + strength * detail * mask
        return output.astype(np.float32, copy=False), "rgb", {
            "边缘像素比例": float(mask.mean())
        }, {
            "Sharpen Edge Mask": mask[:, :, 0].astype(np.uint8)
        }
