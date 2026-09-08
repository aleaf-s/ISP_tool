from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Sequence, Tuple

import cv2
import numpy as np

from ..models import ISPError, ImageROI
from .colorchecker import colorchecker_reference


@dataclass
class ColorCheckerDetectionResult:
    """A reviewable ColorChecker location in canonical 6x4 orientation."""

    corners: np.ndarray
    confidence: float
    score: float
    patch_rgb: np.ndarray
    source: str
    diagnostics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class _Candidate:
    corners: np.ndarray
    score: float
    patch_rgb: np.ndarray
    diagnostics: Dict[str, float]


def _normalise_for_detection(image: np.ndarray) -> np.ndarray:
    values = np.asarray(image, dtype=np.float32)[..., :3]
    finite = values[np.all(np.isfinite(values), axis=2)]
    if finite.size == 0:
        raise ISPError("ColorChecker 检测输入没有有限 RGB 像素")
    low = float(np.percentile(finite, 0.5))
    high = float(np.percentile(finite, 99.5))
    if high <= low + 1e-6:
        raise ISPError("图像动态范围过小，无法检测 ColorChecker")
    normalised = np.clip((values - low) / (high - low), 0.0, 1.0)
    return normalised.astype(np.float32, copy=False)


def _order_quad(points: np.ndarray) -> np.ndarray:
    values = np.asarray(points, dtype=np.float32).reshape(4, 2)
    center = values.mean(axis=0)
    angles = np.arctan2(values[:, 1] - center[1], values[:, 0] - center[0])
    ordered = values[np.argsort(angles)]
    start = int(np.argmin(ordered[:, 0] + ordered[:, 1]))
    ordered = np.roll(ordered, -start, axis=0)
    # After angle sorting the order is normally TL,TR,BR,BL.  Correct the
    # mirrored case explicitly so later cyclic variants remain predictable.
    first = ordered[1] - ordered[0]
    second = ordered[2] - ordered[1]
    cross = float(first[0] * second[1] - first[1] * second[0])
    if cross < 0:
        ordered = ordered[[0, 3, 2, 1]]
    return ordered


def _quad_variants(points: np.ndarray):
    ordered = _order_quad(points)
    forward = ordered
    mirrored = ordered[[0, 3, 2, 1]]
    for values in (forward, mirrored):
        for shift in range(4):
            yield np.roll(values, -shift, axis=0)


def _quad_key(points: np.ndarray, width: int, height: int) -> Tuple[int, ...]:
    values = _order_quad(points)
    scale = max(min(width, height) * 0.025, 2.0)
    return tuple(np.rint(values.ravel() / scale).astype(int))


def _candidate_quads(display: np.ndarray, include_frame: bool) -> list[np.ndarray]:
    height, width = display.shape[:2]
    encoded = np.clip(np.power(display, 1.0 / 2.2) * 255.0, 0, 255).astype(np.uint8)
    gray = cv2.cvtColor(encoded, cv2.COLOR_RGB2GRAY)
    edges = np.zeros_like(gray)
    for plane in (gray, encoded[..., 0], encoded[..., 1], encoded[..., 2]):
        blurred = cv2.GaussianBlur(plane, (5, 5), 0)
        edges = cv2.bitwise_or(edges, cv2.Canny(blurred, 35, 120))
    edges = cv2.morphologyEx(
        edges,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7)),
        iterations=2,
    )
    contours, _hierarchy = cv2.findContours(
        edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE
    )
    frame_area = float(width * height)
    quads: list[np.ndarray] = []
    for contour in contours:
        area = abs(float(cv2.contourArea(contour)))
        if area < frame_area * 0.012 or area > frame_area * 0.985:
            continue
        perimeter = float(cv2.arcLength(contour, True))
        if perimeter <= 0:
            continue
        approximation = cv2.approxPolyDP(contour, 0.025 * perimeter, True)
        if len(approximation) == 4 and cv2.isContourConvex(approximation):
            points = approximation[:, 0, :].astype(np.float32)
        else:
            rectangle = cv2.minAreaRect(contour)
            points = cv2.boxPoints(rectangle).astype(np.float32)
        ordered = _order_quad(points)
        sides = np.linalg.norm(np.roll(ordered, -1, axis=0) - ordered, axis=1)
        short = max(float(np.min(sides)), 1e-6)
        long = float(np.max(sides))
        if not 1.15 <= long / short <= 2.6:
            continue
        quads.append(ordered)
    if include_frame:
        inset = 1.0
        quads.append(np.array([
            (inset, inset),
            (width - 1.0 - inset, inset),
            (width - 1.0 - inset, height - 1.0 - inset),
            (inset, height - 1.0 - inset),
        ], dtype=np.float32))
    unique: Dict[Tuple[int, ...], np.ndarray] = {}
    for quad in quads:
        unique.setdefault(_quad_key(quad, width, height), quad)
    # Largest candidates first; a ColorChecker outer frame is generally more
    # useful than the individual patch contours it contains.
    return sorted(
        unique.values(),
        key=lambda value: abs(float(cv2.contourArea(value))),
        reverse=True,
    )[:40]


def _sample_grid(warped: np.ndarray) -> tuple[np.ndarray, float]:
    height, width = warped.shape[:2]
    patches = []
    variations = []
    for row in range(4):
        for column in range(6):
            x0 = int(round((column + 0.28) * width / 6.0))
            x1 = int(round((column + 0.72) * width / 6.0))
            y0 = int(round((row + 0.28) * height / 4.0))
            y1 = int(round((row + 0.72) * height / 4.0))
            samples = warped[y0:y1, x0:x1, :3].reshape(-1, 3)
            median = np.median(samples, axis=0)
            mad = np.median(np.abs(samples - median), axis=0)
            patches.append(median)
            variations.append(float(np.mean(mad / np.maximum(median, 0.04))))
    return np.asarray(patches, dtype=np.float64), float(np.median(variations))


def _reference_fit_score(measured: np.ndarray, reference: np.ndarray) -> tuple[float, float]:
    design = np.column_stack([measured, np.ones(len(measured))])
    ridge = 0.02
    regularizer = np.zeros((4, 4), dtype=np.float64)
    regularizer[:3, :3] = np.eye(3) * np.sqrt(ridge)
    target_prior = np.zeros((4, 3), dtype=np.float64)
    target_prior[:3, :3] = np.eye(3) * np.sqrt(ridge)
    coefficients = np.linalg.lstsq(
        np.vstack([design, regularizer]),
        np.vstack([reference, target_prior]),
        rcond=None,
    )[0]
    predicted = design @ coefficients
    error = float(np.sqrt(np.mean(np.square(predicted - reference))))
    return float(np.exp(-error / 0.11)), error


def _score_warp(warped: np.ndarray, reference: np.ndarray) -> tuple[float, np.ndarray, Dict[str, float]]:
    patches, uniformity = _sample_grid(warped)
    if not np.all(np.isfinite(patches)):
        return 0.0, patches, {"fit_error": 1.0}
    fit_score, fit_error = _reference_fit_score(patches, reference)
    luma = patches @ np.array((0.2126, 0.7152, 0.0722))
    channel_mean = np.maximum(np.mean(patches, axis=1), 0.03)
    chroma = (np.max(patches, axis=1) - np.min(patches, axis=1)) / channel_mean
    row_chroma = chroma.reshape(4, 6).mean(axis=1)
    neutral_advantage = float(
        np.clip((np.median(row_chroma[:3]) - row_chroma[3]) / 0.45, 0.0, 1.0)
    )
    neutral_luma = luma[18:24]
    descending = float(np.mean(np.diff(neutral_luma) < 0.0))
    neutral_range = float(
        np.clip((neutral_luma[0] - neutral_luma[-1]) / 0.45, 0.0, 1.0)
    )
    neutral_score = 0.45 * neutral_advantage + 0.35 * descending + 0.20 * neutral_range
    diversity = float(np.mean(np.std(patches, axis=0)))
    diversity_score = float(np.clip(diversity / 0.18, 0.0, 1.0))
    uniformity_score = float(np.exp(-uniformity / 0.055))

    gray = cv2.cvtColor(warped.astype(np.float32), cv2.COLOR_RGB2GRAY)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    gradient = cv2.magnitude(gx, gy)
    boundary_values = []
    for column in range(1, 6):
        x = int(round(column * gradient.shape[1] / 6.0))
        boundary_values.append(np.mean(gradient[:, max(0, x - 2):x + 3]))
    for row in range(1, 4):
        y = int(round(row * gradient.shape[0] / 4.0))
        boundary_values.append(np.mean(gradient[max(0, y - 2):y + 3, :]))
    boundary_energy = float(np.mean(boundary_values))
    global_energy = float(np.mean(gradient)) + 1e-6
    grid_score = float(np.clip(boundary_energy / (global_energy * 1.8), 0.0, 1.0))
    score = (
        0.43 * fit_score
        + 0.22 * neutral_score
        + 0.14 * uniformity_score
        + 0.11 * diversity_score
        + 0.10 * grid_score
    )
    return float(score), patches, {
        "fit_score": fit_score,
        "fit_error": fit_error,
        "neutral_score": neutral_score,
        "uniformity_score": uniformity_score,
        "uniformity": uniformity,
        "diversity_score": diversity_score,
        "grid_score": grid_score,
    }


def detect_colorchecker(
    linear_rgb: np.ndarray,
    search_roi: Optional[ImageROI] = None,
    minimum_confidence: float = 0.45,
    max_search_side: int = 1100,
) -> ColorCheckerDetectionResult:
    """Locate a classic 24-patch ColorChecker and canonicalise its orientation.

    Detection is deliberately conservative.  It proposes geometry for user
    review; it never calculates or applies a CCM itself.
    """
    image = np.asarray(linear_rgb, dtype=np.float32)
    if image.ndim != 3 or image.shape[2] < 3:
        raise ISPError("ColorChecker 自动检测需要线性 RGB 图像")
    height, width = image.shape[:2]
    if search_roi is None:
        x0, y0, x1, y1 = 0, 0, width, height
        source = "full_image"
    else:
        search_roi.validate(image.shape)
        x0, y0 = int(search_roi.x), int(search_roi.y)
        x1, y1 = int(search_roi.x2), int(search_roi.y2)
        source = "current_roi"
    crop = _normalise_for_detection(image[y0:y1, x0:x1, :3])
    crop_height, crop_width = crop.shape[:2]
    scale = min(1.0, float(max_search_side) / max(crop_height, crop_width))
    if scale < 1.0:
        working = cv2.resize(
            crop,
            (max(8, round(crop_width * scale)), max(8, round(crop_height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    else:
        working = crop
    quads = _candidate_quads(working, include_frame=search_roi is not None)
    if not quads:
        raise ISPError("没有找到近似 ColorChecker 外框的四边形")
    _names, reference = colorchecker_reference(illuminant="D65")
    detection_width, detection_height = 360, 240
    destination = np.array(
        (
            (0, 0),
            (detection_width - 1, 0),
            (detection_width - 1, detection_height - 1),
            (0, detection_height - 1),
        ),
        dtype=np.float32,
    )
    ranked: list[_Candidate] = []
    for quad in quads:
        best_for_quad: Optional[_Candidate] = None
        for variant in _quad_variants(quad):
            transform = cv2.getPerspectiveTransform(
                variant.astype(np.float32), destination
            )
            warped = cv2.warpPerspective(
                working,
                transform,
                (detection_width, detection_height),
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REPLICATE,
            )
            score, patches, diagnostics = _score_warp(warped, reference)
            candidate = _Candidate(
                variant.copy(), score, patches, diagnostics
            )
            if best_for_quad is None or candidate.score > best_for_quad.score:
                best_for_quad = candidate
        if best_for_quad is not None:
            ranked.append(best_for_quad)
    if not ranked:
        raise ISPError("ColorChecker 候选区域无法完成 6×4 网格评分")
    ranked.sort(key=lambda item: item.score, reverse=True)
    best = ranked[0]
    runner_up = ranked[1].score if len(ranked) > 1 else 0.0
    margin = max(0.0, best.score - runner_up)
    absolute = np.clip((best.score - 0.42) / 0.36, 0.0, 1.0)
    margin_factor = 0.75 + 0.25 * np.clip(margin / 0.12, 0.0, 1.0)
    confidence = float(np.clip(absolute * margin_factor, 0.0, 1.0))
    diagnostics: Dict[str, Any] = dict(best.diagnostics)
    diagnostics.update({
        "candidate_count": len(ranked),
        "runner_up_score": float(runner_up),
        "score_margin": float(margin),
        "search_scale": float(scale),
        "search_bounds": [x0, y0, x1, y1],
    })
    if confidence < float(minimum_confidence):
        raise ISPError(
            "ColorChecker 检测置信度不足："
            f"{confidence * 100:.1f}%（得分 {best.score:.3f}）。"
            "请先用 ROI 缩小搜索范围，或手动微调四角。"
        )
    corners = best.corners.astype(np.float64) / scale
    corners[:, 0] += x0
    corners[:, 1] += y0
    return ColorCheckerDetectionResult(
        corners=corners.astype(np.float32),
        confidence=confidence,
        score=float(best.score),
        patch_rgb=best.patch_rgb.astype(np.float32),
        source=source,
        diagnostics=diagnostics,
    )


__all__ = ["ColorCheckerDetectionResult", "detect_colorchecker"]
