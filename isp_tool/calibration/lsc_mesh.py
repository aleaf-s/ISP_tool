from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Dict, Optional, Tuple

import cv2
import numpy as np

from ..models import ISPError, LSCMesh


def normalize_mesh_center(mesh: LSCMesh) -> LSCMesh:
    mesh.validate()
    channels = {}
    cy = (mesh.rows - 1) * 0.5
    cx = (mesh.cols - 1) * 0.5
    y0, x0 = int(np.floor(cy)), int(np.floor(cx))
    y1, x1 = min(y0 + 1, mesh.rows - 1), min(x0 + 1, mesh.cols - 1)
    fy, fx = cy - y0, cx - x0
    for name, array in mesh.channels().items():
        center = (
            array[y0, x0] * (1 - fy) * (1 - fx)
            + array[y1, x0] * fy * (1 - fx)
            + array[y0, x1] * (1 - fy) * fx
            + array[y1, x1] * fy * fx
        )
        channels[name] = array / max(float(center), 1e-8)
    return LSCMesh(
        mesh.rows,
        mesh.cols,
        channels["R"],
        channels["Gr"],
        channels["Gb"],
        channels["B"],
        True,
        mesh.source,
        dict(mesh.metadata),
    )


def interpolate_mesh_channels(
    mesh: LSCMesh,
    frame_shape: Tuple[int, int],
    origin: Tuple[int, int] = (0, 0),
    output_shape: Optional[Tuple[int, int]] = None,
    gain_limit: float = 8.0,
    strength: float = 1.0,
    normalize_center: bool = False,
    preserve_mean: bool = False,
) -> Dict[str, np.ndarray]:
    mesh.validate()
    frame_h, frame_w = map(int, frame_shape[:2])
    origin_x, origin_y = map(int, origin)
    out_h, out_w = output_shape or (frame_h, frame_w)
    if frame_h <= 0 or frame_w <= 0 or out_h <= 0 or out_w <= 0:
        raise ISPError("LSC 插值尺寸必须大于 0")
    if origin_x < 0 or origin_y < 0 or origin_x + out_w > frame_w or origin_y + out_h > frame_h:
        raise ISPError("LSC ROI 坐标超出完整图像")
    working = normalize_mesh_center(mesh) if normalize_center else mesh
    output = {}
    for name, nodes in working.channels().items():
        full = cv2.resize(
            nodes.astype(np.float32),
            (frame_w, frame_h),
            interpolation=cv2.INTER_LINEAR,
        )
        gain = full[origin_y:origin_y + out_h, origin_x:origin_x + out_w].copy()
        gain = 1.0 + (gain - 1.0) * float(np.clip(strength, 0, 1))
        output[name] = np.clip(gain, 0.0, float(gain_limit)).astype(np.float32)
    if preserve_mean:
        combined_mean = float(np.mean([array.mean() for array in output.values()]))
        if combined_mean > 1e-8:
            output = {
                name: np.clip(array / combined_mean, 0, gain_limit).astype(np.float32)
                for name, array in output.items()
            }
    return output


def save_lsc_mesh(path: str, mesh: LSCMesh) -> None:
    mesh.validate()
    target = Path(path)
    suffix = target.suffix.lower()
    if suffix == ".json":
        target.write_text(
            json.dumps(mesh.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return
    if suffix == ".npz":
        np.savez_compressed(
            str(target),
            R=mesh.r,
            Gr=mesh.gr,
            Gb=mesh.gb,
            B=mesh.b,
            rows=mesh.rows,
            cols=mesh.cols,
        )
        return
    if suffix == ".npy":
        stacked = np.stack([mesh.r, mesh.gr, mesh.gb, mesh.b], axis=0)
        np.save(str(target), stacked)
        return
    if suffix == ".csv":
        with target.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.writer(stream)
            writer.writerow(["channel", "row", "col", "gain"])
            for name, array in mesh.channels().items():
                for row in range(mesh.rows):
                    for col in range(mesh.cols):
                        writer.writerow([name, row, col, f"{array[row, col]:.9g}"])
        return
    raise ISPError(f"不支持的 LSC Mesh 文件格式：{suffix}")


def load_lsc_mesh(path: str) -> LSCMesh:
    source = Path(path)
    suffix = source.suffix.lower()
    try:
        if suffix == ".json":
            return LSCMesh.from_dict(json.loads(source.read_text(encoding="utf-8")))
        if suffix == ".npz":
            with np.load(str(source)) as data:
                channels = {name: np.asarray(data[name], np.float32) for name in ("R", "Gr", "Gb", "B")}
            rows, cols = channels["R"].shape
            mesh = LSCMesh(rows, cols, channels["R"], channels["Gr"], channels["Gb"], channels["B"], source=str(source))
            mesh.validate()
            return mesh
        if suffix == ".npy":
            stacked = np.asarray(np.load(str(source)), dtype=np.float32)
            if stacked.ndim != 3 or stacked.shape[0] != 4:
                raise ISPError("NPY Mesh 必须为 [4, rows, cols]")
            mesh = LSCMesh(
                stacked.shape[1], stacked.shape[2],
                stacked[0], stacked[1], stacked[2], stacked[3],
                source=str(source),
            )
            mesh.validate()
            return mesh
        if suffix == ".csv":
            records = {name: {} for name in ("R", "Gr", "Gb", "B")}
            with source.open("r", encoding="utf-8-sig", newline="") as stream:
                for row in csv.DictReader(stream):
                    name = row["channel"]
                    if name not in records:
                        raise ISPError(f"CSV 包含未知通道：{name}")
                    records[name][(int(row["row"]), int(row["col"]))] = float(row["gain"])
            if any(not values for values in records.values()):
                raise ISPError("CSV Mesh 缺少一个或多个通道")
            rows = max(key[0] for values in records.values() for key in values) + 1
            cols = max(key[1] for values in records.values() for key in values) + 1
            arrays = {}
            for name, values in records.items():
                if len(values) != rows * cols:
                    raise ISPError(f"CSV Mesh {name} 节点数量不完整")
                array = np.empty((rows, cols), np.float32)
                for (row, col), gain in values.items():
                    array[row, col] = gain
                arrays[name] = array
            mesh = LSCMesh(
                rows, cols, arrays["R"], arrays["Gr"], arrays["Gb"], arrays["B"],
                source=str(source),
            )
            mesh.validate()
            return mesh
    except ISPError:
        raise
    except Exception as exc:
        raise ISPError(f"LSC Mesh 读取失败：{exc}") from exc
    raise ISPError(f"不支持的 LSC Mesh 文件格式：{suffix}")

