from __future__ import annotations

import cv2
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
        data_state = getattr(metadata, "_stage_data_state", None)
        offset_scale = (
            1.0
            if data_state is None or data_state.normalized
            else max(float(data_state.white_level), 1.0)
        )
        strength = float(self.parameters["strength"])
        effective_matrix = (
            np.eye(3, dtype=np.float32) * (1.0 - strength)
            + matrix * strength
        )
        effective_offset = offset * (strength * offset_scale)
        if (
            np.array_equal(effective_matrix, np.eye(3, dtype=np.float32))
            and not np.any(effective_offset)
        ):
            output = src
        else:
            output = cv2.transform(src, effective_matrix)
            if np.any(effective_offset):
                output = output + effective_offset
        range_max = (
            1.0
            if data_state is None or data_state.normalized
            else max(float(data_state.white_level), 1.0)
        )
        out_of_range = (
            np.count_nonzero(output < 0)
            + np.count_nonzero(output > range_max)
        ) / max(output.size, 1)
        return output.astype(np.float32, copy=False), "rgb", {
            "矩阵行列式": float(np.linalg.det(matrix)),
            "输出越界比例": float(out_of_range),
            "Offset Scale": float(offset_scale),
        }
