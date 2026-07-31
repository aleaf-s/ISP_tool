from __future__ import annotations

import cv2
import numpy as np

from ..models import ParameterSpec
from .base import ISPModule


def evaluate_tone_curve(values: np.ndarray, parameters) -> np.ndarray:
    """Evaluate the exact transfer function used by the image module."""
    src = np.asarray(values, dtype=np.float32)
    black = float(parameters["black_point"])
    white = max(float(parameters["white_point"]), black + 1e-6)
    if black == 0.0 and white == 1.0:
        linear = np.clip(src, 0.0, 1.0)
    else:
        linear = np.clip((src - black) / (white - black), 0.0, 1.0)
    toe = float(parameters["toe_strength"])
    if toe > 0:
        lifted = linear * linear * (3.0 - 2.0 * linear)
        linear = linear * (1.0 - toe) + lifted * toe
    shoulder = float(parameters["shoulder_strength"])
    if shoulder > 0:
        compressed = linear / (linear + (1.0 - linear) * (1.0 + 2.0 * shoulder))
        linear = linear * (1.0 - shoulder) + compressed * shoulder
    contrast = float(parameters["contrast"])
    if contrast != 1.0:
        linear = np.clip(
            (linear - 0.18) * contrast + 0.18, 0.0, 1.0
        )
    gamma = max(float(parameters["gamma"]), 0.01)
    exponent = 1.0 / gamma
    # cv2.pow is vectorized for float32 images and is much faster than
    # np.power at preview resolutions. Keep NumPy for the one-dimensional
    # transfer-curve widget because OpenCV represents it as an Nx1 matrix.
    if linear.ndim >= 2:
        return cv2.pow(linear, exponent).astype(np.float32, copy=False)
    return np.power(linear, exponent).astype(np.float32)


class ToneMapping(ISPModule):
    module_id = "tone_mapping"
    name = "Gamma / Tone Mapping"
    input_domains = ("rgb",)

    def __init__(self) -> None:
        super().__init__([
            ParameterSpec("gamma", "Gamma", "float", 2.2, 0.1, 5, 0.01),
            ParameterSpec("black_point", "Black Point", "float", 0.0, 0, 0.5, 0.001),
            ParameterSpec("white_point", "White Point", "float", 1.0, 0.1, 4, 0.001),
            ParameterSpec("contrast", "Contrast", "float", 1.0, 0, 3, 0.01),
            ParameterSpec("toe_strength", "Toe Strength", "float", 0.0, 0, 1, 0.01),
            ParameterSpec("shoulder_strength", "Shoulder Strength", "float", 0.0, 0, 1, 0.01),
        ])

    def process(self, image, domain, metadata):
        src = np.asarray(image, dtype=np.float32)
        output = evaluate_tone_curve(src, self.parameters)
        return output.astype(np.float32, copy=False), "rgb", {
            "过曝比例": float(
                np.count_nonzero(output >= 0.999) / max(output.size, 1)
            ),
            "欠曝比例": float(
                np.count_nonzero(output <= 0.001) / max(output.size, 1)
            ),
        }
