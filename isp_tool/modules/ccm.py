from __future__ import annotations

import numpy as np

from ..models import ParameterSpec
from .base import ISPModule


class ColorCorrectionMatrix(ISPModule):
    module_id = "color_correction_matrix"
    name = "Color Correction Matrix"
    input_domains = ("rgb",)

    def __init__(self) -> None:
        identity = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
        specs = []
        for row in range(3):
            for col in range(3):
                specs.append(ParameterSpec(
                    f"m{row}{col}", f"M{row + 1}{col + 1}", "float",
                    identity[row * 3 + col], -4, 4, 0.001,
                ))
        specs.extend([
            ParameterSpec("offset_r", "R Offset", "float", 0.0, -1, 1, 0.001),
            ParameterSpec("offset_g", "G Offset", "float", 0.0, -1, 1, 0.001),
            ParameterSpec("offset_b", "B Offset", "float", 0.0, -1, 1, 0.001),
            ParameterSpec("strength", "Matrix Strength", "float", 1.0, 0, 1, 0.01),
        ])
        super().__init__(specs)

    def matrix(self) -> np.ndarray:
        return np.array([
            [self.parameters[f"m{r}{c}"] for c in range(3)]
            for r in range(3)
        ], dtype=np.float32)

    def process(self, image, domain, metadata):
        src = np.asarray(image, dtype=np.float32)
        matrix = self.matrix()
        offset = np.array([
            self.parameters["offset_r"],
            self.parameters["offset_g"],
            self.parameters["offset_b"],
        ], np.float32)
        corrected = np.einsum("...c,dc->...d", src, matrix) + offset
        strength = float(self.parameters["strength"])
        output = src * (1.0 - strength) + corrected * strength
        return output.astype(np.float32), "rgb", {
            "矩阵行列式": float(np.linalg.det(matrix)),
            "输出越界比例": float(np.mean((output < 0) | (output > 1))),
        }

