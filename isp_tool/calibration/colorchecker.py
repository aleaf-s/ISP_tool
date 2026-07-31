from __future__ import annotations

import warnings
from typing import List, Sequence, Tuple

import cv2
import numpy as np

from ..models import ColorCheckerPatch, ISPError
from .delta_e import delta_e_values

try:
    import colour
except ImportError:  # pragma: no cover
    colour = None


def colorchecker_reference(
    dataset: str = "ColorChecker N Ohta",
    illuminant: str = "D65",
) -> Tuple[List[str], np.ndarray]:
    """Return spectral ColorChecker references as linear sRGB."""
    if colour is None:
        raise ISPError("缺少 colour-science，无法生成 ColorChecker 参考值")
    if dataset not in colour.SDS_COLOURCHECKERS:
        raise ISPError(f"未知 ColorChecker 数据集：{dataset}")
    if illuminant not in colour.SDS_ILLUMINANTS:
        raise ISPError(f"未知参考光源：{illuminant}")
    checker = colour.SDS_COLOURCHECKERS[dataset]
    illuminant_sd = colour.SDS_ILLUMINANTS[illuminant]
    cmfs = colour.MSDS_CMFS["CIE 1931 2 Degree Standard Observer"]
    names = list(checker.keys())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        xyz = np.asarray([
            colour.sd_to_XYZ(sd, cmfs=cmfs, illuminant=illuminant_sd) / 100.0
            for sd in checker.values()
        ], dtype=np.float64)
    rgb = np.asarray(
        colour.XYZ_to_sRGB(xyz, apply_cctf_encoding=False),
        dtype=np.float32,
    )
    if len(names) != 24 or rgb.shape != (24, 3):
        raise ISPError("ColorChecker 参考数据不是标准 24 色块")
    return names, rgb


def _bilinear_point(corners: np.ndarray, u: float, v: float) -> np.ndarray:
    tl, tr, br, bl = corners
    return (
        tl * (1 - u) * (1 - v)
        + tr * u * (1 - v)
        + br * u * v
        + bl * (1 - u) * v
    )


def generate_colorchecker_grid(
    corners: Sequence[Sequence[float]],
    columns: int = 6,
    rows: int = 4,
    inner_scale: float = 0.62,
) -> List[List[Tuple[float, float]]]:
    points = np.asarray(corners, dtype=np.float64)
    if points.shape != (4, 2):
        raise ISPError("色卡四角必须按 TL、TR、BR、BL 提供 4×2 坐标")
    if columns <= 0 or rows <= 0:
        raise ISPError("色卡行列数必须大于 0")
    if not 0.1 <= inner_scale <= 1.0:
        raise ISPError("色块内部采样比例必须在 0.1～1.0")
    polygons = []
    for row in range(rows):
        for col in range(columns):
            u0, u1 = col / columns, (col + 1) / columns
            v0, v1 = row / rows, (row + 1) / rows
            polygon = np.stack([
                _bilinear_point(points, u0, v0),
                _bilinear_point(points, u1, v0),
                _bilinear_point(points, u1, v1),
                _bilinear_point(points, u0, v1),
            ])
            center = polygon.mean(axis=0)
            polygon = center + (polygon - center) * inner_scale
            polygons.append([tuple(map(float, point)) for point in polygon])
    return polygons


def reorder_reference_indices(rotation: int = 0, flipped: bool = False) -> np.ndarray:
    indices = np.arange(24).reshape(4, 6)
    rotation = int(rotation) % 360
    if rotation == 90:
        indices = np.rot90(indices, 1)
    elif rotation == 180:
        indices = np.rot90(indices, 2)
    elif rotation == 270:
        indices = np.rot90(indices, 3)
    elif rotation != 0:
        raise ISPError("色卡旋转角度必须是 0/90/180/270")
    if flipped:
        indices = np.fliplr(indices)
    return indices.ravel()


def sample_colorchecker(
    linear_rgb: np.ndarray,
    polygons: Sequence[Sequence[Sequence[float]]],
    reference_rgb: np.ndarray,
    names: Sequence[str],
    statistic: str = "Median",
    reference_indices: np.ndarray = None,
) -> List[ColorCheckerPatch]:
    image = np.asarray(linear_rgb, dtype=np.float32)
    if image.ndim != 3 or image.shape[2] < 3:
        raise ISPError("ColorChecker 采样需要 Gamma 前的线性 RGB")
    if len(polygons) != 24:
        raise ISPError(f"ColorChecker 必须有 24 个色块，实际 {len(polygons)}")
    references = np.asarray(reference_rgb, dtype=np.float32)
    if references.shape != (24, 3) or len(names) != 24:
        raise ISPError("ColorChecker 参考数据必须为 24×3")
    order = (
        np.arange(24, dtype=int)
        if reference_indices is None else np.asarray(reference_indices, dtype=int)
    )
    if order.shape != (24,):
        raise ISPError("色卡参考顺序必须包含 24 个索引")

    height, width = image.shape[:2]
    patches = []
    for patch_id, polygon in enumerate(polygons):
        polygon_array = np.asarray(polygon, dtype=np.float32)
        # Sample the central part again even when the grid itself was already
        # inset.  This deliberately avoids printed borders and perspective
        # interpolation leakage between neighbouring patches.
        center = polygon_array.mean(axis=0, keepdims=True)
        sample_polygon = center + (polygon_array - center) * 0.82
        points = np.round(sample_polygon).astype(np.int32)
        if (
            points[:, 0].min() < 0 or points[:, 1].min() < 0
            or points[:, 0].max() >= width or points[:, 1].max() >= height
        ):
            raise ISPError(f"色块 {patch_id + 1} ROI 超出图像")
        mask = np.zeros((height, width), np.uint8)
        cv2.fillConvexPoly(mask, points, 1)
        raw_samples = image[mask.astype(bool), :3]
        finite_mask = np.all(np.isfinite(raw_samples), axis=1)
        finite = raw_samples[finite_mask]
        if finite.shape[0] < 9:
            raise ISPError(f"色块 {patch_id + 1} 有效像素不足")
        clipped_mask = np.any(finite >= 0.985, axis=1)
        dark_mask = np.all(finite <= 0.008, axis=1)
        usable = finite[~clipped_mask & ~dark_mask]
        if usable.shape[0] < 9:
            usable = finite

        median = np.median(usable, axis=0)
        mad = np.median(np.abs(usable - median), axis=0)
        robust_scale = np.maximum(mad * 1.4826, 1e-5)
        inlier_mask = np.max(
            np.abs(usable - median) / robust_scale,
            axis=1,
        ) <= 3.5
        inliers = usable[inlier_mask]
        if inliers.shape[0] < 9:
            inliers = usable

        statistic_key = str(statistic).strip().lower()
        if statistic_key == "median":
            measured = np.median(inliers, axis=0)
        elif statistic_key in {"trimmed mean", "截尾均值"}:
            ordered = np.sort(inliers, axis=0)
            trim = min(int(len(ordered) * 0.1), max(0, len(ordered) // 2 - 1))
            measured = np.mean(
                ordered[trim:len(ordered) - trim] if trim else ordered,
                axis=0,
            )
        else:
            # Robust Mean is the default for unrecognised legacy labels.
            measured = np.mean(inliers, axis=0)
        measured = measured.astype(np.float32)
        clipped_ratio = float(np.mean(clipped_mask))
        dark_ratio = float(np.mean(dark_mask))
        variation = float(
            np.max(mad / np.maximum(np.abs(median), 0.02))
        )
        reasons = []
        if clipped_ratio > 0.12:
            reasons.append("过曝像素过多")
        if dark_ratio > 0.45:
            reasons.append("欠曝像素过多")
        if variation > 0.18:
            reasons.append("色块内部不均匀")
        if inliers.shape[0] < max(9, int(finite.shape[0] * 0.35)):
            reasons.append("异常像素过多")
        reference_index = int(order[patch_id])
        delta, measured_lab, reference_lab = delta_e_values(
            measured[None, :], references[reference_index][None, :], "CIE 2000"
        )
        patches.append(ColorCheckerPatch(
            patch_id + 1,
            str(names[reference_index]),
            [tuple(map(float, point)) for point in polygon],
            measured,
            references[reference_index],
            measured_lab[0].astype(np.float32),
            reference_lab[0].astype(np.float32),
            float(delta[0]),
            {
                "valid": not reasons,
                "reasons": reasons,
                "pixel_count": int(raw_samples.shape[0]),
                "finite_count": int(finite.shape[0]),
                "sample_count": int(inliers.shape[0]),
                "rejected_count": int(usable.shape[0] - inliers.shape[0]),
                "clipped_ratio": clipped_ratio,
                "dark_ratio": dark_ratio,
                "variation": variation,
                "statistic": statistic,
                "sample_inner_scale": 0.82,
                "reference_index": reference_index,
            },
        ))
    return patches
