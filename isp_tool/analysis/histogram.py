from __future__ import annotations

from typing import Dict, Mapping, Optional

import numpy as np

from ..models import RawMetadata, StageDataState
from ..preview import bayer_cell_rgb, display_rgb


def compute_histogram(
    image: np.ndarray,
    domain: str,
    metadata: RawMetadata,
    bins: int = 256,
) -> Dict[str, np.ndarray]:
    rgb = (
        bayer_cell_rgb(image, metadata)
        if domain == "bayer"
        else display_rgb(image, domain, metadata)
    )
    result = {}
    for index, name in enumerate(("R", "G", "B")):
        result[name] = np.histogram(rgb[:, :, index], bins=bins, range=(0, 1))[0]
    luminance = np.sum(
        rgb * np.array([0.2126, 0.7152, 0.0722], np.float32), axis=2
    )
    result["Y"] = np.histogram(luminance, bins=bins, range=(0, 1))[0]
    return result


def histogram_payload_from_curves(
    curves: Mapping[str, np.ndarray],
    code_max: int,
    *,
    mode: str,
    bins: int = 256,
    exposure_reference: Optional[np.ndarray] = None,
    legal_ranges: Optional[Mapping[str, tuple[int, int]]] = None,
) -> Dict[str, object]:
    """Build a render-ready absolute-code histogram and exposure summary."""

    code_max = max(1, int(code_max))
    bins = max(16, min(int(bins), 4096))
    counts: Dict[str, np.ndarray] = {}
    curve_sizes: Dict[str, int] = {}
    finite_curves: Dict[str, np.ndarray] = {}
    for name, values in curves.items():
        finite = np.asarray(values, dtype=np.float32).reshape(-1)
        finite = finite[np.isfinite(finite)]
        finite_curves[str(name)] = finite
        curve_sizes[str(name)] = int(finite.size)
        counts[str(name)] = np.histogram(
            finite,
            bins=bins,
            range=(0.0, float(code_max)),
        )[0]

    reference = exposure_reference
    if reference is None:
        reference = next(
            iter(finite_curves.values()), np.empty(0, np.float32)
        )
    reference = np.asarray(reference, dtype=np.float32).reshape(-1)
    reference = reference[np.isfinite(reference)]
    if reference.size:
        minimum = float(reference.min())
        maximum = float(reference.max())
        dark_ratio = float(np.mean(reference <= code_max * 0.01))
        highlight_ratio = float(np.mean(reference >= code_max * 0.99))
        underflow_ratio = float(np.mean(reference < 0.0))
        overflow_ratio = float(np.mean(reference > code_max))
    else:
        minimum = maximum = 0.0
        dark_ratio = highlight_ratio = 0.0
        underflow_ratio = overflow_ratio = 0.0

    return {
        "curves": counts,
        "curve_sizes": curve_sizes,
        "bin_edges": np.linspace(
            0.0, float(code_max), bins + 1, dtype=np.float32
        ),
        "code_max": code_max,
        "mode": str(mode),
        "legal_ranges": dict(legal_ranges or {}),
        "stats": {
            "minimum": minimum,
            "maximum": maximum,
            "dark_ratio": dark_ratio,
            "highlight_ratio": highlight_ratio,
            "underflow_ratio": underflow_ratio,
            "overflow_ratio": overflow_ratio,
        },
    }


def compute_histogram_details(
    image: np.ndarray,
    domain: str,
    metadata: RawMetadata,
    *,
    mode: str = "RGB Overlay",
    bins: int = 256,
    bayer_normalized: bool = False,
    data_state: Optional[StageDataState] = None,
) -> Dict[str, object]:
    """Compute domain-aware histograms using the image bit-depth code scale."""

    code_max = (1 << max(1, min(int(metadata.bit_depth), 30))) - 1
    values = np.asarray(image, dtype=np.float32)
    if data_state is not None:
        bayer_normalized = bool(data_state.normalized)
    if domain == "bayer":
        from ..bayer import channel_positions

        scale = float(code_max) if bayer_normalized else 1.0
        curves = {
            name: values[py::2, px::2] * scale
            for name, (py, px) in channel_positions(
                metadata.bayer_pattern
            ).items()
        }
        reference = np.concatenate(
            [channel.reshape(-1) for channel in curves.values()]
        )
        return histogram_payload_from_curves(
            curves,
            code_max,
            mode="Bayer R/Gr/Gb/B",
            bins=bins,
            exposure_reference=reference,
        )

    rgb = (
        values[..., :3]
        if values.ndim == 3 and domain in {"rgb", "yuv_rgb"}
        else display_rgb(values, domain, metadata)
    )
    rgb_scale = (
        data_state.absolute_scale
        if data_state is not None else float(code_max)
    )
    rgb_codes = np.asarray(rgb, dtype=np.float32) * float(rgb_scale)
    luminance = np.sum(
        rgb_codes
        * np.array([0.2126, 0.7152, 0.0722], np.float32),
        axis=2,
    )
    if mode == "Luma":
        curves = {"Y": luminance}
    elif mode in {"R", "G", "B"}:
        index = {"R": 0, "G": 1, "B": 2}[mode]
        curves = {mode: rgb_codes[..., index]}
    else:
        curves = {
            name: rgb_codes[..., index]
            for index, name in enumerate(("R", "G", "B"))
        }
    payload = histogram_payload_from_curves(
        curves,
        code_max,
        mode=mode,
        bins=bins,
        exposure_reference=luminance,
    )
    finite_rgb = np.all(np.isfinite(rgb_codes), axis=2)
    if np.any(finite_rgb):
        valid_rgb = rgb_codes[finite_rgb]
        payload["stats"]["underflow_ratio"] = float(
            np.mean(np.any(valid_rgb < 0.0, axis=1))
        )
        payload["stats"]["overflow_ratio"] = float(
            np.mean(np.any(valid_rgb > code_max, axis=1))
        )
    return payload
