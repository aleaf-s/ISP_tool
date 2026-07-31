from __future__ import annotations

import numpy as np

from ..backends import get_default_backend
from ..models import ParameterSpec
from .base import ISPModule


class DefectivePixelCorrection(ISPModule):
    module_id = "defective_pixel_correction"
    name = "Defective Pixel Correction"
    input_domains = ("bayer",)

    def __init__(self) -> None:
        super().__init__([
            ParameterSpec(
                "mode", "Correction Mode", "choice", "Dynamic",
                choices=("Dynamic", "Static Map", "Hybrid"),
            ),
            ParameterSpec("threshold", "Detection Threshold", "float", 0.08, 0, 0.5, 0.001),
            ParameterSpec("neighborhood", "Neighborhood", "choice", "3×3", choices=("3×3", "5×5")),
            ParameterSpec("detect_hot", "Detect Hot Pixels", "bool", True),
            ParameterSpec("detect_dark", "Detect Dark Pixels", "bool", True),
        ])
        self.defect_map = None

    def set_defect_map(self, defect_map):
        if defect_map is None:
            self.defect_map = None
            return
        value = np.asarray(defect_map, dtype=np.uint8)
        if value.ndim != 2 or np.any(value > 2):
            raise ValueError("DPC defect map must be a 2-D array with values 0/1/2")
        self.defect_map = value.copy()

    def export_state(self):
        if self.defect_map is None:
            return {"defect_pixels": [], "shape": None}
        ys, xs = np.nonzero(self.defect_map)
        return {
            "shape": list(self.defect_map.shape),
            "defect_pixels": [
                [int(x), int(y), int(self.defect_map[y, x])]
                for y, x in zip(ys, xs)
            ],
        }

    def load_state(self, state):
        if not state:
            self.defect_map = None
            return
        shape = state.get("shape")
        pixels = state.get("defect_pixels", [])
        if not shape:
            self.defect_map = None
            return
        defect_map = np.zeros(tuple(map(int, shape)), np.uint8)
        for item in pixels:
            x, y, kind = map(int, item[:3])
            if 0 <= y < defect_map.shape[0] and 0 <= x < defect_map.shape[1]:
                defect_map[y, x] = np.uint8(np.clip(kind, 1, 2))
        self.defect_map = defect_map

    def process(self, image, domain, metadata):
        src = np.asarray(image, dtype=np.float32)
        kernel = 3 if self.parameters["neighborhood"] == "3×3" else 5
        static_map = self.defect_map
        if static_map is not None and static_map.shape != src.shape:
            origin_x = int(getattr(metadata, "_processing_origin_x", 0))
            origin_y = int(getattr(metadata, "_processing_origin_y", 0))
            y2 = origin_y + src.shape[0]
            x2 = origin_x + src.shape[1]
            if (
                origin_x >= 0 and origin_y >= 0
                and y2 <= static_map.shape[0] and x2 <= static_map.shape[1]
            ):
                static_map = static_map[origin_y:y2, origin_x:x2]
            else:
                raise ValueError(
                    "Static DPC map shape does not match the current image"
                )
        mode = self.parameters.get("mode", "Dynamic")
        dynamic_enabled = (
            mode in {"Dynamic", "Hybrid"}
            and (
                bool(self.parameters["detect_hot"])
                or bool(self.parameters["detect_dark"])
            )
        )
        static_enabled = (
            static_map is not None
            and mode in {"Static Map", "Hybrid"}
            and bool(np.any(static_map))
        )
        if not dynamic_enabled and not static_enabled:
            defect_mask = np.zeros(src.shape, dtype=np.uint8)
            return src, "bayer", {
                "坏点数量": 0,
                "亮坏点": 0,
                "暗坏点": 0,
                "坏点比例": 0.0,
                "Mode": mode,
                "Backend": "bypass",
            }, {
                "Defect Mask": defect_mask,
            }
        backend = self.processing_backend or get_default_backend()
        kernel_result = backend.correct_defective_pixels(
            src,
            kernel=kernel,
            threshold=float(self.parameters["threshold"]),
            detect_hot=bool(self.parameters["detect_hot"]),
            detect_dark=bool(self.parameters["detect_dark"]),
            static_map=static_map,
            dynamic_enabled=dynamic_enabled,
            static_enabled=static_enabled,
        )
        return kernel_result.corrected, "bayer", {
            "坏点数量": kernel_result.corrected_count,
            "亮坏点": kernel_result.hot_count,
            "暗坏点": kernel_result.dark_count,
            "坏点比例": kernel_result.corrected_count / max(src.size, 1),
            "Mode": self.parameters.get("mode", "Dynamic"),
            "Backend": kernel_result.implementation,
        }, {
            "Defect Mask": kernel_result.defect_mask,
        }
