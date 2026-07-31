"""Repeatable cold-pipeline and cached-parameter benchmark for V0.4.11."""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
import statistics
import sys
import time

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from isp_tool.models import RawMetadata
from isp_tool.pipeline import ISPPipeline


def run_once(pipeline, image, metadata, snapshot, cache):
    started = time.perf_counter()
    pipeline.process_cached(
        image,
        "bayer",
        metadata,
        snapshot,
        cache,
        input_revision=1,
    )
    measured = (time.perf_counter() - started) * 1000.0
    return measured, dict(cache["last_metrics"])


def median(values):
    return statistics.median(float(value) for value in values)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--width", type=int, default=1500)
    parser.add_argument("--height", type=int, default=1000)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument(
        "--demosaic",
        choices=(
            "Nearest Neighbor",
            "Bilinear",
            "Adaptive Interpolation",
            "Constant Color Difference",
        ),
        default="Bilinear",
        help="demosaic algorithm to benchmark",
    )
    parser.add_argument(
        "--backend",
        choices=("auto", "opencv", "native"),
        default="auto",
        help="requested processing backend; native falls back when unavailable",
    )
    args = parser.parse_args()
    if args.width < 32 or args.height < 32 or args.iterations < 1:
        parser.error("width/height must be >= 32 and iterations >= 1")

    rng = np.random.default_rng(46)
    image = (
        rng.random((args.height, args.width), dtype=np.float32) * 3500.0
        + 64.0
    ).astype(np.float32)
    metadata = RawMetadata(
        width=args.width,
        height=args.height,
        bit_depth=12,
        bayer_pattern="RGGB",
        black_level=[64, 64, 64, 64],
        white_level=4095,
    )
    backend_preferences = {
        "auto": "Auto",
        "opencv": "OpenCV / NumPy",
        "native": "Native C++",
    }
    pipeline = ISPPipeline(
        backend_preference=backend_preferences[args.backend]
    )
    pipeline.module_by_id("demosaic").parameters[
        "algorithm"
    ] = args.demosaic
    snapshot = pipeline.snapshot()

    # Warm OpenCV dispatch and allocator paths before collecting samples.
    run_once(pipeline, image, metadata, snapshot, {})

    cold_wall = []
    cold_modules = defaultdict(list)
    for _ in range(args.iterations):
        measured, metrics = run_once(
            pipeline, image, metadata, snapshot, {}
        )
        cold_wall.append(measured)
        for name, elapsed in metrics["module_timings"].items():
            cold_modules[name].append(elapsed)

    cache = {}
    run_once(pipeline, image, metadata, snapshot, cache)
    cached_wall = []
    ccm_index = next(
        index
        for index, module in enumerate(pipeline.modules)
        if module.module_id == "color_correction_matrix"
    )
    for iteration in range(args.iterations):
        adjusted = pipeline.snapshot()
        adjusted[ccm_index]["parameters"]["strength"] = (
            0.98 if iteration % 2 == 0 else 1.0
        )
        measured, _ = run_once(
            pipeline, image, metadata, adjusted, cache
        )
        cached_wall.append(measured)

    print(
        f"ISP benchmark · {args.width}x{args.height} · "
        f"{args.iterations} iterations · "
        f"{'fast' if args.fast_demosaic else 'exact'} demosaic · "
        f"{pipeline.backend.name}"
    )
    if pipeline.backend_selection.fallback_reason:
        print(
            "backend fallback          "
            f"{pipeline.backend_selection.fallback_reason}"
        )
    print(f"cold pipeline median     {median(cold_wall):8.2f} ms")
    print(f"cached CCM edit median   {median(cached_wall):8.2f} ms")
    print("")
    print("cold module medians")
    for name, values in sorted(
        cold_modules.items(),
        key=lambda item: median(item[1]),
        reverse=True,
    ):
        print(f"  {name:<32} {median(values):8.2f} ms")


if __name__ == "__main__":
    main()
