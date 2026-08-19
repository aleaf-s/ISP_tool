from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np


class ISPError(RuntimeError):
    """A user-facing input or processing error."""


@dataclass
class RawMetadata:
    width: int = 1920
    height: int = 1080
    bit_depth: int = 12
    storage: str = "uint16_le"
    bayer_pattern: str = "RGGB"
    byte_order: str = "little"
    row_stride_bytes: int = 0
    offset_bytes: int = 0
    black_level: List[float] = field(default_factory=lambda: [64.0] * 4)
    white_level: float = 4095.0
    flip_horizontal: bool = False
    flip_vertical: bool = False

    def validate(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ISPError("RAW 宽度和高度必须大于 0")
        if self.bit_depth not in {8, 10, 12, 14, 16}:
            raise ISPError("位深必须是 8/10/12/14/16")
        if self.storage not in {
            "uint8", "uint16_le", "uint16_be",
            "mipi_raw10", "mipi_raw12", "mipi_raw14",
        }:
            raise ISPError(f"不支持的 RAW 存储方式：{self.storage}")
        if self.bayer_pattern not in {"RGGB", "GRBG", "GBRG", "BGGR"}:
            raise ISPError(f"不支持的 Bayer Pattern：{self.bayer_pattern}")
        if self.offset_bytes < 0 or self.row_stride_bytes < 0:
            raise ISPError("offset 和 row stride 不能为负数")
        if len(self.black_level) != 4:
            raise ISPError("Black Level 必须包含 R/Gr/Gb/B 四个值")
        if self.white_level <= max(self.black_level):
            raise ISPError("White Level 必须大于 Black Level")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RawMetadata":
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{key: value for key, value in data.items() if key in known})


@dataclass
class LoadedImage:
    image: np.ndarray
    domain: str
    metadata: RawMetadata
    source_path: Optional[Path] = None
    description: str = ""
    # YUV state is intentionally separate from RawMetadata.  ``metadata`` is
    # retained as a small compatibility shell for shared image-size/display
    # code; no pixel-format or colour-range setting is stored in it.
    yuv_metadata: Any = None
    yuv_frame: Any = None
    yuv_conversion: Any = None
    yuv_original_metadata: Any = None


@dataclass(frozen=True)
class ImageROI:
    """An image-space rectangle using a half-open [x, x+w) convention."""

    x: int
    y: int
    width: int
    height: int

    @property
    def x2(self) -> int:
        return self.x + self.width

    @property
    def y2(self) -> int:
        return self.y + self.height

    def validate(self, image_shape: Tuple[int, ...]) -> None:
        image_height, image_width = image_shape[:2]
        if self.width <= 0 or self.height <= 0:
            raise ISPError("ROI 宽度和高度必须大于 0")
        if self.x < 0 or self.y < 0 or self.x2 > image_width or self.y2 > image_height:
            raise ISPError(
                f"ROI ({self.x}, {self.y}, {self.width}, {self.height}) "
                f"超出图像 {image_width}×{image_height}"
            )

    def align_for_bayer(self, image_shape: Tuple[int, ...]) -> "ImageROI":
        """Expand to even boundaries without changing the CFA phase."""
        image_height, image_width = image_shape[:2]
        x0 = max(0, self.x // 2 * 2)
        y0 = max(0, self.y // 2 * 2)
        x1 = min(image_width, ((self.x2 + 1) // 2) * 2)
        y1 = min(image_height, ((self.y2 + 1) // 2) * 2)
        # Odd-sized sources cannot always provide an even far boundary.
        if (x1 - x0) % 2 and x1 > x0:
            x1 -= 1
        if (y1 - y0) % 2 and y1 > y0:
            y1 -= 1
        aligned = ImageROI(x0, y0, x1 - x0, y1 - y0)
        aligned.validate(image_shape)
        return aligned

    def expanded(
        self,
        margin: int,
        image_shape: Tuple[int, ...],
        bayer_aligned: bool = False,
    ) -> "ImageROI":
        image_height, image_width = image_shape[:2]
        margin = max(0, int(margin))
        if bayer_aligned and margin % 2:
            margin += 1
        x0 = max(0, self.x - margin)
        y0 = max(0, self.y - margin)
        x1 = min(image_width, self.x2 + margin)
        y1 = min(image_height, self.y2 + margin)
        expanded = ImageROI(x0, y0, x1 - x0, y1 - y0)
        return expanded.align_for_bayer(image_shape) if bayer_aligned else expanded

    def relative_to(self, outer: "ImageROI") -> "ImageROI":
        return ImageROI(self.x - outer.x, self.y - outer.y, self.width, self.height)

    def slices(self) -> Tuple[slice, slice]:
        return slice(self.y, self.y2), slice(self.x, self.x2)

    def to_dict(self) -> Dict[str, int]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ImageROI":
        return cls(*(int(data[key]) for key in ("x", "y", "width", "height")))


@dataclass(frozen=True)
class ParameterSpec:
    key: str
    label: str
    kind: str = "float"
    default: Any = 0.0
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    step: Optional[float] = None
    choices: Sequence[str] = ()
    tooltip: str = ""


def _json_safe(value: Any) -> Any:
    """Convert NumPy-heavy analysis output to JSON-safe Python values."""
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, ImageROI):
        return value.to_dict()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _compact_large_data(value: Any) -> Any:
    """Keep configuration JSON small while retaining useful summaries."""
    if isinstance(value, dict):
        output = {}
        for key, item in value.items():
            if key in {"pixels", "defect_pixels"} and isinstance(item, list):
                output[f"{key}_count"] = len(item)
                output[f"{key}_externalized"] = True
            else:
                output[str(key)] = _compact_large_data(item)
        return output
    if isinstance(value, np.ndarray):
        return {
            "shape": list(value.shape),
            "dtype": str(value.dtype),
            "externalized": True,
        }
    if isinstance(value, (list, tuple)):
        # Ordinary diagnostic lists are retained; masks and tables should be
        # passed as artifacts, where they are exported to NPZ.
        return [_compact_large_data(item) for item in value]
    return _json_safe(value)


@dataclass
class ParameterRecommendation:
    """A measured, reviewable parameter suggestion.

    Artifacts are deliberately excluded from normal JSON serialization.  They
    can be large and are exported to NPZ by the persistence helper instead.
    """

    module_id: str
    current_parameters: Dict[str, Any]
    suggested_parameters: Dict[str, Any]
    measurements: Dict[str, Any]
    confidence: float
    warnings: List[str] = field(default_factory=list)
    artifacts: Dict[str, np.ndarray] = field(default_factory=dict)
    source_description: str = ""
    roi: Optional[ImageROI] = None
    method: str = ""
    target_module_id: str = ""
    state_updates: Dict[str, Any] = field(default_factory=dict)
    elapsed_ms: float = 0.0
    applied: bool = False
    created_at: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )

    @property
    def target(self) -> str:
        return self.target_module_id or self.module_id

    def artifact_metadata(self) -> Dict[str, Dict[str, Any]]:
        output: Dict[str, Dict[str, Any]] = {}
        for name, artifact in self.artifacts.items():
            array = np.asarray(artifact)
            item: Dict[str, Any] = {
                "shape": list(array.shape),
                "dtype": str(array.dtype),
            }
            if array.size and np.issubdtype(array.dtype, np.number):
                finite = array[np.isfinite(array)]
                if finite.size:
                    item.update({
                        "minimum": float(np.min(finite)),
                        "maximum": float(np.max(finite)),
                    })
            output[name] = item
        return output

    def to_dict(self, include_artifacts: bool = False) -> Dict[str, Any]:
        data = {
            "module_id": self.module_id,
            "target_module_id": self.target,
            "current_parameters": _json_safe(self.current_parameters),
            "suggested_parameters": _json_safe(self.suggested_parameters),
            "measurements": _compact_large_data(self.measurements),
            "confidence": float(np.clip(self.confidence, 0.0, 1.0)),
            "warnings": list(self.warnings),
            "source_description": self.source_description,
            "roi": self.roi.to_dict() if self.roi else None,
            "method": self.method,
            "state_updates": _compact_large_data(self.state_updates),
            "elapsed_ms": float(self.elapsed_ms),
            "applied": bool(self.applied),
            "created_at": self.created_at,
            "artifacts": self.artifact_metadata(),
        }
        if include_artifacts:
            data["artifact_values"] = {
                name: _json_safe(value) for name, value in self.artifacts.items()
            }
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ParameterRecommendation":
        artifact_values = data.get("artifact_values", {})
        return cls(
            module_id=str(data["module_id"]),
            target_module_id=str(
                data.get("target_module_id", data.get("module_id", ""))
            ),
            current_parameters=dict(data.get("current_parameters", {})),
            suggested_parameters=dict(data.get("suggested_parameters", {})),
            measurements=dict(data.get("measurements", {})),
            confidence=float(data.get("confidence", 0.0)),
            warnings=list(data.get("warnings", [])),
            artifacts={
                name: np.asarray(value)
                for name, value in artifact_values.items()
            },
            source_description=str(data.get("source_description", "")),
            roi=ImageROI.from_dict(data["roi"]) if data.get("roi") else None,
            method=str(data.get("method", "")),
            state_updates=dict(data.get("state_updates", {})),
            elapsed_ms=float(data.get("elapsed_ms", 0.0)),
            applied=bool(data.get("applied", False)),
            created_at=str(data.get("created_at", "")),
        )


@dataclass
class StageDataState:
    """Explicit numeric representation carried beside every stage image."""

    color_domain: str
    encoding: str
    value_min: float
    value_max: float
    normalized: bool
    black_level_applied: bool
    bit_depth: int
    black_level: Tuple[float, float, float, float]
    white_level: float

    @classmethod
    def for_input(
        cls, domain: str, metadata: RawMetadata
    ) -> "StageDataState":
        black = tuple(float(value) for value in metadata.black_level)
        if domain == "bayer":
            return cls(
                "bayer", "Bayer RAW DN", 0.0,
                float(metadata.white_level), False, False,
                int(metadata.bit_depth), black,
                float(metadata.white_level),
            )
        return cls(
            "rgb", "RGB Linear Normalized", 0.0, 1.0,
            True, False, int(metadata.bit_depth), black,
            float(metadata.white_level),
        )

    def with_domain(self, domain: str) -> "StageDataState":
        domain = str(domain)
        if domain == self.color_domain:
            return self
        if domain == "rgb":
            encoding = (
                "RGB Linear Normalized" if self.normalized else "RGB DN"
            )
        elif domain == "bayer":
            encoding = (
                "Bayer Linear Normalized"
                if self.normalized else "Bayer RAW DN"
            )
        else:
            encoding = self.encoding
        return StageDataState(
            domain, encoding, self.value_min, self.value_max,
            self.normalized, self.black_level_applied, self.bit_depth,
            self.black_level, self.white_level,
        )

    @property
    def code_max(self) -> int:
        return (1 << max(1, min(int(self.bit_depth), 30))) - 1

    @property
    def absolute_scale(self) -> float:
        return float(self.code_max) if self.normalized else 1.0

    @property
    def display_divisor(self) -> float:
        return 1.0 if self.normalized else max(float(self.white_level), 1.0)


@dataclass
class StageResult:
    module_id: str
    name: str
    image: np.ndarray
    domain: str
    elapsed_ms: float
    diagnostics: Dict[str, Any] = field(default_factory=dict)
    artifacts: Dict[str, np.ndarray] = field(default_factory=dict)
    data_state: Optional[StageDataState] = None


@dataclass
class LSCMesh:
    rows: int
    cols: int
    r: np.ndarray
    gr: np.ndarray
    gb: np.ndarray
    b: np.ndarray
    center_normalized: bool = True
    source: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def validate(self, gain_limit: Optional[float] = None) -> None:
        if self.rows < 2 or self.cols < 2:
            raise ISPError("LSC Mesh 至少需要 2×2 个节点")
        for name, value in self.channels().items():
            array = np.asarray(value, dtype=np.float32)
            if array.shape != (self.rows, self.cols):
                raise ISPError(
                    f"LSC Mesh {name} 尺寸应为 {self.rows}×{self.cols}，"
                    f"实际为 {array.shape}"
                )
            if not np.all(np.isfinite(array)):
                raise ISPError(f"LSC Mesh {name} 包含 NaN 或 Infinity")
            if np.any(array <= 0):
                raise ISPError(f"LSC Mesh {name} 包含非正增益")
            if gain_limit is not None and np.any(array > float(gain_limit)):
                raise ISPError(
                    f"LSC Mesh {name} 存在超过 Gain Limit {gain_limit} 的节点"
                )

    def channels(self) -> Dict[str, np.ndarray]:
        return {
            "R": np.asarray(self.r, dtype=np.float32),
            "Gr": np.asarray(self.gr, dtype=np.float32),
            "Gb": np.asarray(self.gb, dtype=np.float32),
            "B": np.asarray(self.b, dtype=np.float32),
        }

    def copy(self) -> "LSCMesh":
        return LSCMesh.from_dict(self.to_dict())

    def to_dict(self) -> Dict[str, Any]:
        self.validate()
        return {
            "schema_version": 1,
            "rows": self.rows,
            "cols": self.cols,
            "channels": {
                name: value.astype(float).tolist()
                for name, value in self.channels().items()
            },
            "center_normalized": self.center_normalized,
            "source": self.source,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LSCMesh":
        channels = data.get("channels", data)
        mesh = cls(
            rows=int(data["rows"]),
            cols=int(data["cols"]),
            r=np.asarray(channels.get("R", channels.get("r")), dtype=np.float32),
            gr=np.asarray(channels.get("Gr", channels.get("gr")), dtype=np.float32),
            gb=np.asarray(channels.get("Gb", channels.get("gb")), dtype=np.float32),
            b=np.asarray(channels.get("B", channels.get("b")), dtype=np.float32),
            center_normalized=bool(
                data.get("center_normalized", data.get("normalized", True))
            ),
            source=str(data.get("source", "")),
            metadata=dict(data.get("metadata", {})),
        )
        mesh.validate()
        return mesh


@dataclass
class AWBResult:
    r_gain: float
    gr_gain: float
    gb_gain: float
    b_gain: float
    confidence: float
    method: str
    sample_count: int
    diagnostics: Dict[str, Any] = field(default_factory=dict)
    artifacts: Dict[str, np.ndarray] = field(default_factory=dict)

    def gains(self) -> Dict[str, float]:
        return {
            "R": self.r_gain,
            "Gr": self.gr_gain,
            "Gb": self.gb_gain,
            "B": self.b_gain,
        }

    def to_dict(self, include_artifacts: bool = False) -> Dict[str, Any]:
        data = {
            "r_gain": self.r_gain,
            "gr_gain": self.gr_gain,
            "gb_gain": self.gb_gain,
            "b_gain": self.b_gain,
            "confidence": self.confidence,
            "method": self.method,
            "sample_count": self.sample_count,
            "diagnostics": dict(self.diagnostics),
        }
        if include_artifacts:
            data["artifacts"] = {
                key: np.asarray(value).tolist() for key, value in self.artifacts.items()
            }
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AWBResult":
        return cls(
            r_gain=float(data["r_gain"]),
            gr_gain=float(data.get("gr_gain", 1.0)),
            gb_gain=float(data.get("gb_gain", 1.0)),
            b_gain=float(data["b_gain"]),
            confidence=float(data.get("confidence", 0.0)),
            method=str(data.get("method", "")),
            sample_count=int(data.get("sample_count", 0)),
            diagnostics=dict(data.get("diagnostics", {})),
            artifacts={
                key: np.asarray(value)
                for key, value in data.get("artifacts", {}).items()
            },
        )


@dataclass
class AEResult:
    current_level: float
    target_level: float
    suggested_gain: float
    clipped_ratio_before: float
    predicted_clipped_ratio: float
    method: str
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AEResult":
        return cls(
            current_level=float(data["current_level"]),
            target_level=float(data["target_level"]),
            suggested_gain=float(data["suggested_gain"]),
            clipped_ratio_before=float(data.get("clipped_ratio_before", 0.0)),
            predicted_clipped_ratio=float(data.get("predicted_clipped_ratio", 0.0)),
            method=str(data.get("method", "")),
            diagnostics=dict(data.get("diagnostics", {})),
        )


@dataclass
class ColorCheckerPatch:
    patch_id: int
    name: str
    polygon: List[Tuple[float, float]]
    measured_rgb: np.ndarray
    reference_rgb: np.ndarray
    measured_lab: np.ndarray = field(default_factory=lambda: np.zeros(3, np.float32))
    reference_lab: np.ndarray = field(default_factory=lambda: np.zeros(3, np.float32))
    delta_e: float = 0.0
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "patch_id": self.patch_id,
            "name": self.name,
            "polygon": [list(point) for point in self.polygon],
            "measured_rgb": np.asarray(self.measured_rgb).tolist(),
            "reference_rgb": np.asarray(self.reference_rgb).tolist(),
            "measured_lab": np.asarray(self.measured_lab).tolist(),
            "reference_lab": np.asarray(self.reference_lab).tolist(),
            "delta_e": self.delta_e,
            "diagnostics": _json_safe(self.diagnostics),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ColorCheckerPatch":
        return cls(
            patch_id=int(data["patch_id"]),
            name=str(data.get("name", f"Patch {data['patch_id']}")),
            polygon=[tuple(map(float, point)) for point in data["polygon"]],
            measured_rgb=np.asarray(data["measured_rgb"], dtype=np.float32),
            reference_rgb=np.asarray(data["reference_rgb"], dtype=np.float32),
            measured_lab=np.asarray(data.get("measured_lab", [0, 0, 0]), dtype=np.float32),
            reference_lab=np.asarray(data.get("reference_lab", [0, 0, 0]), dtype=np.float32),
            delta_e=float(data.get("delta_e", 0.0)),
            diagnostics=dict(data.get("diagnostics", {})),
        )


@dataclass
class CCMCalibrationResult:
    matrix: np.ndarray
    offset: np.ndarray
    method: str
    condition_number: float
    delta_e_before: Dict[str, float]
    delta_e_after: Dict[str, float]
    patches: List[ColorCheckerPatch] = field(default_factory=list)
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "matrix": np.asarray(self.matrix).tolist(),
            "offset": np.asarray(self.offset).tolist(),
            "method": self.method,
            "condition_number": self.condition_number,
            "delta_e_before": dict(self.delta_e_before),
            "delta_e_after": dict(self.delta_e_after),
            "patches": [patch.to_dict() for patch in self.patches],
            "diagnostics": dict(self.diagnostics),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CCMCalibrationResult":
        return cls(
            matrix=np.asarray(data["matrix"], dtype=np.float32).reshape(3, 3),
            offset=np.asarray(data.get("offset", [0, 0, 0]), dtype=np.float32),
            method=str(data.get("method", "")),
            condition_number=float(data.get("condition_number", 0.0)),
            delta_e_before=dict(data.get("delta_e_before", {})),
            delta_e_after=dict(data.get("delta_e_after", {})),
            patches=[
                ColorCheckerPatch.from_dict(item)
                for item in data.get("patches", [])
            ],
            diagnostics=dict(data.get("diagnostics", {})),
        )


@dataclass
class CalibrationSession:
    name: str = ""
    sensor_name: str = ""
    illuminant: str = "D65"
    raw_metadata: RawMetadata = field(default_factory=RawMetadata)
    lsc_mesh: Optional[LSCMesh] = None
    awb_result: Optional[AWBResult] = None
    ae_result: Optional[AEResult] = None
    ccm_result: Optional[CCMCalibrationResult] = None
    notes: str = ""
    auto_recommendations: Dict[str, ParameterRecommendation] = field(
        default_factory=dict
    )
    calibration_history: List[Dict[str, Any]] = field(default_factory=list)
    noise_profile: Optional[Dict[str, Any]] = None
    external_assets: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "sensor_name": self.sensor_name,
            "illuminant": self.illuminant,
            "raw_metadata": self.raw_metadata.to_dict(),
            "lsc_mesh": self.lsc_mesh.to_dict() if self.lsc_mesh else None,
            "awb": self.awb_result.to_dict() if self.awb_result else None,
            "ae": self.ae_result.to_dict() if self.ae_result else None,
            "ccm": self.ccm_result.to_dict() if self.ccm_result else None,
            "notes": self.notes,
            "auto_recommendations": {
                key: value.to_dict()
                for key, value in self.auto_recommendations.items()
            },
            "calibration_history": _json_safe(self.calibration_history),
            "noise_profile": _json_safe(self.noise_profile),
            "external_assets": dict(self.external_assets),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CalibrationSession":
        return cls(
            name=str(data.get("name", "")),
            sensor_name=str(data.get("sensor_name", "")),
            illuminant=str(data.get("illuminant", "D65")),
            raw_metadata=RawMetadata.from_dict(data.get("raw_metadata", data.get("raw", {}))),
            lsc_mesh=LSCMesh.from_dict(data["lsc_mesh"]) if data.get("lsc_mesh") else None,
            awb_result=AWBResult.from_dict(data["awb"]) if data.get("awb") else None,
            ae_result=AEResult.from_dict(data["ae"]) if data.get("ae") else None,
            ccm_result=(
                CCMCalibrationResult.from_dict(data["ccm"])
                if data.get("ccm") else None
            ),
            notes=str(data.get("notes", "")),
            auto_recommendations={
                key: ParameterRecommendation.from_dict(value)
                for key, value in data.get("auto_recommendations", {}).items()
            },
            calibration_history=list(data.get("calibration_history", [])),
            noise_profile=(
                dict(data["noise_profile"])
                if isinstance(data.get("noise_profile"), dict)
                else None
            ),
            external_assets={
                str(key): str(value)
                for key, value in data.get("external_assets", {}).items()
            },
        )
