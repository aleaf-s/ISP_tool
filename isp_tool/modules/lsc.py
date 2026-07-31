from __future__ import annotations

import hashlib
from collections import OrderedDict
from typing import Any, Dict, Optional

import numpy as np

from ..bayer import channel_positions
from ..calibration.lsc_mesh import interpolate_mesh_channels
from ..models import ISPError, LSCMesh, ParameterSpec
from .base import ISPModule


class LensShadingCorrection(ISPModule):
    module_id = "lens_shading_correction"
    name = "Lens Shading Correction"
    input_domains = ("bayer",)
    _gain_cache = OrderedDict()
    _gain_cache_limit = 8

    def __init__(self) -> None:
        super().__init__([
            ParameterSpec(
                "mode", "Mode", "choice", "Radial Model",
                choices=("Radial Model", "Mesh Model"),
            ),
            ParameterSpec("r_strength", "R Radial Strength", "float", 0.0, -1, 4, 0.01),
            ParameterSpec("gr_strength", "Gr Radial Strength", "float", 0.0, -1, 4, 0.01),
            ParameterSpec("gb_strength", "Gb Radial Strength", "float", 0.0, -1, 4, 0.01),
            ParameterSpec("b_strength", "B Radial Strength", "float", 0.0, -1, 4, 0.01),
            ParameterSpec("center_x", "Optical Center X", "float", 0.5, 0, 1, 0.001),
            ParameterSpec("center_y", "Optical Center Y", "float", 0.5, 0, 1, 0.001),
            ParameterSpec("mesh_strength", "Mesh Strength", "float", 1.0, 0, 1, 0.01),
            ParameterSpec(
                "interpolation", "Mesh Interpolation", "choice", "Bilinear",
                choices=("Bilinear",),
            ),
            ParameterSpec("normalize_center", "Normalize Mesh Center", "bool", False),
            ParameterSpec("preserve_mean", "Preserve Mean Brightness", "bool", False),
            ParameterSpec("max_gain", "Maximum Gain", "float", 3.0, 1, 8, 0.01),
        ])
        self.mesh: Optional[LSCMesh] = None

    def set_mesh(self, mesh: Optional[LSCMesh]) -> None:
        if mesh is not None:
            mesh.validate()
            self.mesh = mesh.copy()
        else:
            self.mesh = None

    def export_state(self) -> Dict[str, Any]:
        return {"lsc_mesh": self.mesh.to_dict() if self.mesh else None}

    def load_state(self, state: Dict[str, Any]) -> None:
        data = state.get("lsc_mesh") if state else None
        self.mesh = LSCMesh.from_dict(data) if data else None

    def _radial_gains(self, shape, metadata):
        h, w = shape
        frame_w = int(getattr(metadata, "_processing_frame_width", w))
        frame_h = int(getattr(metadata, "_processing_frame_height", h))
        origin_x = int(getattr(metadata, "_processing_origin_x", 0))
        origin_y = int(getattr(metadata, "_processing_origin_y", 0))
        cx = float(self.parameters["center_x"]) * max(frame_w - 1, 1)
        cy = float(self.parameters["center_y"]) * max(frame_h - 1, 1)
        gains = np.ones((h, w), np.float32)
        strengths = {
            "R": self.parameters["r_strength"],
            "Gr": self.parameters["gr_strength"],
            "Gb": self.parameters["gb_strength"],
            "B": self.parameters["b_strength"],
        }
        if not any(float(value) != 0.0 for value in strengths.values()):
            return gains, cx - origin_x, cy - origin_y, False
        nx = (
            np.arange(w, dtype=np.float32) + origin_x - cx
        ) / max(frame_w * 0.5, 1)
        ny = (
            np.arange(h, dtype=np.float32) + origin_y - cy
        ) / max(frame_h * 0.5, 1)
        radius2 = ny[:, None] * ny[:, None] + nx[None, :] * nx[None, :]
        for name, (y, x) in channel_positions(metadata.bayer_pattern).items():
            gain = 1.0 + float(strengths[name]) * radius2[y::2, x::2]
            gains[y::2, x::2] = np.clip(
                gain, 0.0, float(self.parameters["max_gain"])
            )
        return gains, cx - origin_x, cy - origin_y, False

    def _mesh_gains(self, shape, metadata):
        if self.mesh is None:
            raise ISPError("LSC 当前为 Mesh Model，但尚未加载或生成 Mesh")
        h, w = shape
        frame_w = int(getattr(metadata, "_processing_frame_width", w))
        frame_h = int(getattr(metadata, "_processing_frame_height", h))
        origin_x = int(getattr(metadata, "_processing_origin_x", 0))
        origin_y = int(getattr(metadata, "_processing_origin_y", 0))
        digest = hashlib.sha1()
        for array in self.mesh.channels().values():
            digest.update(np.ascontiguousarray(array).tobytes())
        key = (
            digest.hexdigest(), frame_h, frame_w, origin_x, origin_y, h, w,
            metadata.bayer_pattern,
            float(self.parameters["max_gain"]),
            float(self.parameters["mesh_strength"]),
            bool(self.parameters["normalize_center"]),
            bool(self.parameters["preserve_mean"]),
        )
        if key in self._gain_cache:
            gains = self._gain_cache.pop(key)
            self._gain_cache[key] = gains
            cx = float(self.parameters["center_x"]) * max(frame_w - 1, 1) - origin_x
            cy = float(self.parameters["center_y"]) * max(frame_h - 1, 1) - origin_y
            return gains, cx, cy, True
        maps = interpolate_mesh_channels(
            self.mesh,
            (frame_h, frame_w),
            origin=(origin_x, origin_y),
            output_shape=(h, w),
            gain_limit=float(self.parameters["max_gain"]),
            strength=float(self.parameters["mesh_strength"]),
            normalize_center=bool(self.parameters["normalize_center"]),
            preserve_mean=bool(self.parameters["preserve_mean"]),
        )
        gains = np.ones((h, w), np.float32)
        for name, (y, x) in channel_positions(metadata.bayer_pattern).items():
            gains[y::2, x::2] = maps[name][y::2, x::2]
        cx = float(self.parameters["center_x"]) * max(frame_w - 1, 1) - origin_x
        cy = float(self.parameters["center_y"]) * max(frame_h - 1, 1) - origin_y
        self._gain_cache[key] = gains
        while len(self._gain_cache) > self._gain_cache_limit:
            self._gain_cache.popitem(last=False)
        return gains, cx, cy, False

    def process(self, image, domain, metadata):
        src = np.asarray(image, dtype=np.float32)
        if self.parameters["mode"] == "Mesh Model":
            gains, cx, cy, cache_hit = self._mesh_gains(src.shape, metadata)
            neutral = False
        else:
            gains, cx, cy, cache_hit = self._radial_gains(src.shape, metadata)
            neutral = not any(
                float(self.parameters[key]) != 0.0
                for key in (
                    "r_strength", "gr_strength", "gb_strength", "b_strength"
                )
            )
        output = src if neutral else src * gains
        h, w = src.shape
        corners = (gains[0, 0], gains[0, -1], gains[-1, 0], gains[-1, -1])
        local_cx = min(max(int(cx), 0), w - 1)
        local_cy = min(max(int(cy), 0), h - 1)
        diagnostics = {
            "模式": self.parameters["mode"],
            "平均增益": float(gains.mean()),
            "最大增益": float(gains.max()),
            "中心增益": float(gains[local_cy, local_cx]),
            "四角平均": float(np.mean(corners)),
            "Gain Map Cache": "Hit" if cache_hit else "Miss",
        }
        if self.mesh:
            diagnostics["Mesh"] = f"{self.mesh.rows}×{self.mesh.cols}"
        return output, "bayer", diagnostics, {"LSC Gain Map": gains}
