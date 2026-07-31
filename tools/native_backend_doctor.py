"""Diagnose, verify and benchmark the optional Native C++ backend."""

from __future__ import annotations

import argparse
import importlib
import importlib.util
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import time

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from isp_tool.backends import NativeBackend, OpenCVBackend


def find_msvc():
    compiler = shutil.which("cl")
    if compiler:
        return compiler
    candidates = [
        Path(
            r"C:\Program Files (x86)\Microsoft Visual Studio"
            r"\Installer\vswhere.exe"
        ),
        Path(
            r"C:\Program Files\Microsoft Visual Studio"
            r"\Installer\vswhere.exe"
        ),
    ]
    for vswhere in candidates:
        if not vswhere.exists():
            continue
        result = subprocess.run(
            [
                str(vswhere),
                "-latest",
                "-products",
                "*",
                "-requires",
                "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                "-property",
                "installationPath",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        root = Path(result.stdout.strip())
        matches = sorted(
            root.glob(
                "VC/Tools/MSVC/*/bin/Hostx64/x64/cl.exe"
            ),
            reverse=True,
        )
        if matches:
            return str(matches[0])
    return None


def load_native_module():
    importlib.invalidate_caches()
    try:
        return importlib.import_module("isp_tool._native"), ""
    except (ImportError, OSError) as exc:
        return None, str(exc)


def verify_native(module):
    reference = OpenCVBackend()
    native = NativeBackend(module, force_all_native=True)
    rng = np.random.default_rng(410)

    for pattern in ("RGGB", "GRBG", "GBRG", "BGGR"):
        source = rng.random((65, 97), dtype=np.float32) * 1.4
        expected = reference.demosaic(
            source, pattern, "Bilinear"
        ).image
        actual = native.demosaic(
            source, pattern, "Bilinear"
        ).image
        np.testing.assert_allclose(
            actual, expected, rtol=1e-6, atol=2e-7
        )

    source = rng.random((67, 99), dtype=np.float32)
    static_map = np.zeros(source.shape, np.uint8)
    static_map[0, 0] = 1
    static_map[12, 22] = 1
    static_map[31, 47] = 2
    for kernel in (3, 5):
        for dynamic, static in (
            (True, False),
            (False, True),
            (True, True),
        ):
            options = {
                "kernel": kernel,
                "threshold": 0.12,
                "detect_hot": True,
                "detect_dark": True,
                "static_map": static_map if static else None,
                "dynamic_enabled": dynamic,
                "static_enabled": static,
            }
            expected = reference.correct_defective_pixels(
                source, **options
            )
            actual = native.correct_defective_pixels(
                source, **options
            )
            np.testing.assert_array_equal(
                actual.corrected, expected.corrected
            )
            np.testing.assert_array_equal(
                actual.defect_mask, expected.defect_mask
            )
            assert actual.hot_count == expected.hot_count
            assert actual.dark_count == expected.dark_count
            assert actual.corrected_count == expected.corrected_count


def median_time(function, iterations):
    function()
    values = []
    for _ in range(iterations):
        started = time.perf_counter()
        function()
        values.append((time.perf_counter() - started) * 1000.0)
    return statistics.median(values)


def benchmark_native(module, iterations):
    reference = OpenCVBackend()
    native = NativeBackend(module, force_all_native=True)
    rng = np.random.default_rng(411)
    source = rng.random((1000, 1500), dtype=np.float32)
    dpc_options = {
        "kernel": 3,
        "threshold": 0.08,
        "detect_hot": True,
        "detect_dark": True,
        "static_map": None,
        "dynamic_enabled": True,
        "static_enabled": False,
    }
    rows = []
    for name, reference_call, native_call in (
        (
            "Bilinear Demosaic",
            lambda: reference.demosaic(
                source, "RGGB", "Bilinear"
            ),
            lambda: native.demosaic(
                source, "RGGB", "Bilinear"
            ),
        ),
        (
            "DPC 3x3",
            lambda: reference.correct_defective_pixels(
                source, **dpc_options
            ),
            lambda: native.correct_defective_pixels(
                source, **dpc_options
            ),
        ),
    ):
        reference_ms = median_time(reference_call, iterations)
        native_ms = median_time(native_call, iterations)
        speedup = reference_ms / max(native_ms, 1e-9)
        rows.append((name, reference_ms, native_ms, speedup))
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--verify",
        action="store_true",
        help="run Native/OpenCV output parity checks",
    )
    parser.add_argument(
        "--benchmark",
        action="store_true",
        help="benchmark 1500x1000 DPC and Demosaic",
    )
    parser.add_argument("--iterations", type=int, default=5)
    args = parser.parse_args()
    if args.iterations < 1:
        parser.error("--iterations must be >= 1")

    print("ISP NATIVE BACKEND DOCTOR")
    print(f"python              {sys.executable}")
    print(
        "pybind11            "
        + (
            "available"
            if importlib.util.find_spec("pybind11")
            else "not found"
        )
    )
    print(f"cmake               {shutil.which('cmake') or 'not required'}")
    print(f"msvc                {find_msvc() or 'not found'}")

    module, error = load_native_module()
    if module is None:
        print(f"native extension    unavailable · {error}")
        return 1 if args.verify or args.benchmark else 0
    info = module.backend_info()
    print(f"native extension    available · {module.__file__}")
    print(f"version             {info.get('version', 'unknown')}")
    print(f"ABI                 {info.get('abi', 'unknown')}")
    print(f"kernels             {', '.join(info.get('kernels', ())) or 'none'}")
    print(
        "Auto qualified      "
        f"{', '.join(info.get('qualified_kernels', ())) or 'none'}"
    )

    if args.verify:
        try:
            verify_native(module)
        except Exception as exc:
            print(f"parity              FAILED · {exc}")
            return 2
        print("parity              PASS")
    if args.benchmark:
        print("")
        print("1500x1000 MEDIAN PERFORMANCE")
        for name, reference_ms, native_ms, speedup in benchmark_native(
            module, args.iterations
        ):
            print(
                f"{name:<22} OpenCV {reference_ms:8.2f} ms · "
                f"Native {native_ms:8.2f} ms · {speedup:5.2f}x"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
