from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import cv2
import numpy as np

from ..bayer import channel_positions
from ..models import ImageROI, ISPError, ParameterRecommendation, RawMetadata
from .base import CancellationToken, ModuleAnalyzer


@dataclass
class DefectPixel:
    x: int
    y: int
    channel: str
    kind: str
    severity: float
    confidence: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "x": self.x,
            "y": self.y,
            "channel": self.channel,
            "type": self.kind,
            "severity": self.severity,
            "confidence": self.confidence,
        }


@dataclass
class DefectMap:
    width: int
    height: int
    bayer_pattern: str
    pixels: List[DefectPixel] = field(default_factory=list)
    source: str = ""

    def validate(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ISPError("坏点表尺寸无效")
        if self.bayer_pattern not in {"RGGB", "GRBG", "GBRG", "BGGR"}:
            raise ISPError("坏点表 Bayer Pattern 无效")
        for pixel in self.pixels:
            if not (0 <= pixel.x < self.width and 0 <= pixel.y < self.height):
                raise ISPError("坏点坐标超出图像范围")
            if pixel.kind not in {"hot", "dead"}:
                raise ISPError("坏点类型必须为 hot 或 dead")

    def to_array(self) -> np.ndarray:
        self.validate()
        result = np.zeros((self.height, self.width), np.uint8)
        for pixel in self.pixels:
            result[pixel.y, pixel.x] = 1 if pixel.kind == "hot" else 2
        return result

    def to_dict(self) -> Dict[str, Any]:
        self.validate()
        return {
            "version": 1,
            "width": self.width,
            "height": self.height,
            "bayer_pattern": self.bayer_pattern,
            "source": self.source,
            "pixels": [pixel.to_dict() for pixel in self.pixels],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DefectMap":
        result = cls(
            width=int(data["width"]),
            height=int(data["height"]),
            bayer_pattern=str(data["bayer_pattern"]),
            source=str(data.get("source", "")),
            pixels=[
                DefectPixel(
                    int(item["x"]),
                    int(item["y"]),
                    str(item.get("channel", "")),
                    str(item.get("type", item.get("kind", "hot"))),
                    float(item.get("severity", 0.0)),
                    float(item.get("confidence", 0.0)),
                )
                for item in data.get("pixels", [])
            ],
        )
        result.validate()
        return result


def save_defect_map(path: str, defect_map: DefectMap) -> None:
    target = Path(path)
    suffix = target.suffix.lower()
    defect_map.validate()
    if suffix == ".npz":
        np.savez_compressed(
            str(target),
            defect_map=defect_map.to_array(),
            bayer_pattern=np.array(defect_map.bayer_pattern),
            source=np.array(defect_map.source),
        )
    elif suffix == ".csv":
        with target.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=(
                    "x", "y", "channel", "type", "severity", "confidence"
                ),
            )
            writer.writeheader()
            for pixel in defect_map.pixels:
                writer.writerow(pixel.to_dict())
    else:
        target.write_text(
            json.dumps(defect_map.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def load_defect_map(
    path: str,
    metadata: Optional[RawMetadata] = None,
) -> DefectMap:
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix == ".npz":
        with np.load(str(source), allow_pickle=False) as values:
            array = np.asarray(values["defect_map"], np.uint8)
            pattern = str(values["bayer_pattern"].item())
            source_value = values["source"].item() if "source" in values else ""
        positions = _channel_lookup(pattern)
        pixels = []
        ys, xs = np.nonzero(array)
        for y, x in zip(ys, xs):
            pixels.append(DefectPixel(
                int(x), int(y), positions[(int(y) % 2, int(x) % 2)],
                "hot" if array[y, x] == 1 else "dead", 1.0, 1.0,
            ))
        return DefectMap(
            array.shape[1], array.shape[0], pattern, pixels, str(source_value)
        )
    if suffix == ".csv":
        if metadata is None:
            raise ISPError("CSV 坏点表需要提供 RAW 元数据")
        with source.open("r", newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
        return DefectMap.from_dict({
            "width": metadata.width,
            "height": metadata.height,
            "bayer_pattern": metadata.bayer_pattern,
            "source": str(source),
            "pixels": rows,
        })
    return DefectMap.from_dict(
        json.loads(source.read_text(encoding="utf-8"))
    )


def _channel_lookup(pattern: str) -> Dict[tuple[int, int], str]:
    return {
        tuple(position): name
        for name, position in channel_positions(pattern).items()
    }


def _normalize_bayer(image: np.ndarray, metadata: RawMetadata) -> np.ndarray:
    src = np.asarray(image, np.float32)
    if src.ndim != 2:
        raise ISPError("DPC 标定需要单通道 Bayer 图像")
    if not np.all(np.isfinite(src)):
        raise ISPError("DPC 标定输入包含 NaN/Infinity")
    if float(src.max(initial=0.0)) <= 2.0:
        return src.copy()
    output = src.copy()
    for name, (py, px) in channel_positions(metadata.bayer_pattern).items():
        index = {"R": 0, "Gr": 1, "Gb": 2, "B": 3}[name]
        black = float(metadata.black_level[index])
        output[py::2, px::2] = (
            output[py::2, px::2] - black
        ) / max(float(metadata.white_level) - black, 1.0)
    return output


def _median_residual(image: np.ndarray, kernel: int = 3) -> np.ndarray:
    residual = np.zeros_like(image, np.float32)
    for py in range(2):
        for px in range(2):
            plane = np.ascontiguousarray(image[py::2, px::2])
            median = cv2.medianBlur(plane, kernel)
            residual[py::2, px::2] = plane - median
    return residual


def _mask_overlay(mask: np.ndarray) -> np.ndarray:
    overlay = np.zeros((*mask.shape, 3), np.float32)
    overlay[mask == 1] = (1.0, 0.12, 0.05)
    overlay[mask == 2] = (0.05, 0.35, 1.0)
    return overlay


class DPCAnalyzer(ModuleAnalyzer):
    module_id = "auto_dpc"
    target_module_id = "defective_pixel_correction"
    name = "DPC Single-frame Analysis"

    def analyze(
        self,
        image: np.ndarray,
        metadata: RawMetadata,
        current_parameters: Dict[str, Any],
        roi: Optional[ImageROI] = None,
        cancel_token: Optional[CancellationToken] = None,
        source_description: str = "Current BLC output",
        **_options: Any,
    ) -> ParameterRecommendation:
        token = cancel_token or CancellationToken()
        src = _normalize_bayer(image, metadata)
        selected_roi = roi
        if selected_roi is not None:
            selected_roi = selected_roi.align_for_bayer(src.shape)
            ys, xs = selected_roi.slices()
            working = src[ys, xs]
        else:
            working = src
        token.check()
        residual = _median_residual(working)
        center = float(np.median(residual))
        sigma = max(
            1.4826 * float(np.median(np.abs(residual - center))), 1e-5
        )
        positive = residual[residual > 0]
        negative = -residual[residual < 0]
        suggested = float(np.clip(max(
            6.0 * sigma,
            np.percentile(positive, 99.5) if positive.size else 0.005,
            np.percentile(negative, 99.5) if negative.size else 0.005,
        ), 0.005, 0.5))
        hot = residual > suggested
        dark = residual < -suggested
        mask = hot.astype(np.uint8) + dark.astype(np.uint8) * 2
        count = int(np.count_nonzero(mask))
        ratio = count / max(mask.size, 1)
        warnings = []
        if ratio > 0.01:
            warnings.append("候选坏点比例偏高，建议提高阈值或使用多帧标定")
        if mask.size < 1024:
            warnings.append("分析区域较小，自动阈值置信度有限")
        confidence = min(1.0, mask.size / 65536.0) * float(
            np.clip(1.0 - ratio * 20.0, 0.2, 1.0)
        )
        return ParameterRecommendation(
            module_id=self.module_id,
            target_module_id=self.target_module_id,
            current_parameters=dict(current_parameters),
            suggested_parameters={"threshold": suggested},
            measurements={
                "robust_noise_sigma": sigma,
                "suggested_threshold": suggested,
                "hot_candidates": int(hot.sum()),
                "dark_candidates": int(dark.sum()),
                "candidate_ratio": ratio,
            },
            confidence=confidence,
            warnings=warnings,
            artifacts={
                "Hot Pixel Mask": hot.astype(np.uint8),
                "Dead Pixel Mask": dark.astype(np.uint8),
                "Defect Overlay": _mask_overlay(mask),
                "Residual Magnitude": np.abs(residual),
            },
            source_description=source_description,
            roi=selected_roi,
            method="Single Frame Robust Residual",
        )


class DPCCalibrator(ModuleAnalyzer):
    module_id = "dpc_calibration"
    target_module_id = "defective_pixel_correction"
    name = "DPC Multi-frame Calibration"

    def analyze(
        self,
        image: np.ndarray,
        metadata: RawMetadata,
        current_parameters: Dict[str, Any],
        roi: Optional[ImageROI] = None,
        cancel_token: Optional[CancellationToken] = None,
        dark_frames: Optional[Sequence[np.ndarray]] = None,
        flat_frames: Optional[Sequence[np.ndarray]] = None,
        persistence_threshold: float = 0.8,
        sigma_threshold: float = 7.0,
        source_description: str = "Multi-frame calibration",
        **_options: Any,
    ) -> ParameterRecommendation:
        del image, roi
        token = cancel_token or CancellationToken()
        dark = list(dark_frames or [])
        flat = list(flat_frames or [])
        if len(dark) + len(flat) < 2:
            raise ISPError("多帧 DPC 标定至少需要两张暗场或平场")
        normalized_dark = self._prepare_frames(dark, metadata, token)
        normalized_flat = self._prepare_frames(flat, metadata, token)
        all_frames = normalized_dark or normalized_flat
        shape = all_frames[0].shape
        if normalized_dark and normalized_flat:
            if normalized_dark[0].shape != normalized_flat[0].shape:
                raise ISPError("DPC 暗场与平场标定帧尺寸不一致")

        hot_frequency = np.zeros(shape, np.float32)
        dark_frequency = np.zeros(shape, np.float32)
        severity = np.zeros(shape, np.float32)
        if normalized_dark:
            for frame in normalized_dark:
                token.check()
                residual = _median_residual(frame)
                sigma = max(
                    1.4826 * float(np.median(np.abs(residual))), 1e-5
                )
                threshold = max(float(sigma_threshold) * sigma, 0.003)
                hot_frequency += (residual > threshold).astype(np.float32)
                severity = np.maximum(severity, np.maximum(residual, 0.0))
            hot_frequency /= len(normalized_dark)
        if normalized_flat:
            flat_hot_frequency = np.zeros(shape, np.float32)
            for frame in normalized_flat:
                token.check()
                residual = _median_residual(frame)
                sigma = max(
                    1.4826 * float(np.median(np.abs(residual))), 1e-5
                )
                threshold = max(float(sigma_threshold) * sigma, 0.003)
                dark_frequency += (residual < -threshold).astype(np.float32)
                flat_hot_frequency += (residual > threshold).astype(np.float32)
                severity = np.maximum(severity, np.abs(residual))
            dark_frequency /= len(normalized_flat)
            flat_hot_frequency /= len(normalized_flat)
            hot_frequency = np.maximum(hot_frequency, flat_hot_frequency)

        persistence = float(np.clip(persistence_threshold, 0.5, 1.0))
        hot_mask = hot_frequency >= persistence
        dark_mask = dark_frequency >= persistence
        hot_mask &= ~dark_mask
        defect_array = hot_mask.astype(np.uint8) + dark_mask.astype(np.uint8) * 2
        lookup = _channel_lookup(metadata.bayer_pattern)
        pixels: List[DefectPixel] = []
        ys, xs = np.nonzero(defect_array)
        for y, x in zip(ys, xs):
            kind = "hot" if defect_array[y, x] == 1 else "dead"
            frequency = (
                hot_frequency[y, x] if kind == "hot" else dark_frequency[y, x]
            )
            pixels.append(DefectPixel(
                int(x),
                int(y),
                lookup[(int(y) % 2, int(x) % 2)],
                kind,
                float(severity[y, x]),
                float(np.clip(frequency, 0.0, 1.0)),
            ))
        defect_map = DefectMap(
            shape[1], shape[0], metadata.bayer_pattern, pixels, source_description
        )
        channel_counts = {name: 0 for name in ("R", "Gr", "Gb", "B")}
        for pixel in pixels:
            channel_counts[pixel.channel] += 1
        total_frames = len(normalized_dark) + len(normalized_flat)
        warnings = []
        if total_frames < 4:
            warnings.append("标定帧数量较少，建议使用至少 4 张图像")
        if len(pixels) > shape[0] * shape[1] * 0.01:
            warnings.append("固定坏点比例超过 1%，请检查曝光和标定阈值")
        confidence = float(
            np.clip((total_frames - 1) / 5.0, 0.2, 1.0)
            * np.clip(
                1.2 - len(pixels) / max(shape[0] * shape[1] * 0.02, 1),
                0.4,
                1.0,
            )
        )
        nonzero_severity = severity[severity > 0]
        threshold_suggestion = float(np.clip(
            max(
                0.01,
                np.percentile(nonzero_severity, 50) * 0.5
                if nonzero_severity.size else 0.02,
            ),
            0.005,
            0.5,
        ))
        state = {
            "shape": [shape[0], shape[1]],
            "defect_pixels": [
                [pixel.x, pixel.y, 1 if pixel.kind == "hot" else 2]
                for pixel in pixels
            ],
        }
        return ParameterRecommendation(
            module_id=self.module_id,
            target_module_id=self.target_module_id,
            current_parameters=dict(current_parameters),
            suggested_parameters={
                "mode": "Hybrid",
                "threshold": threshold_suggestion,
            },
            state_updates=state,
            measurements={
                "dark_frame_count": len(normalized_dark),
                "flat_frame_count": len(normalized_flat),
                "persistence_threshold": persistence,
                "hot_pixels": int(hot_mask.sum()),
                "dead_pixels": int(dark_mask.sum()),
                "total_defects": len(pixels),
                "channel_distribution": channel_counts,
                "defect_map": defect_map.to_dict(),
            },
            confidence=confidence,
            warnings=warnings,
            artifacts={
                "Hot Pixel Mask": hot_mask.astype(np.uint8),
                "Dead Pixel Mask": dark_mask.astype(np.uint8),
                "Persistent Defect Mask": defect_array,
                "Defect Overlay": _mask_overlay(defect_array),
                "Defect Confidence Map": np.maximum(
                    hot_frequency, dark_frequency
                ),
            },
            source_description=source_description,
            method="Temporal Persistence",
        )

    @staticmethod
    def _prepare_frames(
        frames: Iterable[np.ndarray],
        metadata: RawMetadata,
        token: CancellationToken,
    ) -> List[np.ndarray]:
        result = []
        expected_shape = None
        for frame in frames:
            token.check()
            normalized = _normalize_bayer(frame, metadata)
            if expected_shape is None:
                expected_shape = normalized.shape
            elif normalized.shape != expected_shape:
                raise ISPError("DPC 标定帧尺寸不一致")
            result.append(normalized)
        return result
