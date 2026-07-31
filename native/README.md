# Optional Native C++ Backend

V0.4.10 keeps the desktop UI, configuration and pipeline in Python, while
allowing selected hot kernels to be supplied by `isp_tool._native`.

The extension contract is versioned by `ISP_BACKEND_ABI = 1`. The extension
provides exact bilinear demosaic and DPC 3x3/5x5. `qualified_kernels` determines
which kernels Auto mode may use. Explicit Native C++ mode can force available
experimental kernels.

## Build prerequisites

- A C++17 compiler
- Python development files
- pybind11

The preferred Windows build does not require CMake:

```powershell
python -m pip install pybind11
python native\setup_native.py build_ext --inplace --force
python tools\native_backend_doctor.py --verify --benchmark
```

`setup_native.py` automatically finds Visual Studio through vswhere and adds
Windows SDK resource tools that may be missing from a normal PowerShell PATH.
You can also double-click `构建C++后端.bat`.

CMake 3.18+ remains an alternative:

```powershell
cmake -S native -B build/native -Dpybind11_DIR="$(python -m pybind11 --cmakedir)"
cmake --build build/native --config Release
cmake --install build/native --prefix .
```

Restart the application after building. `Auto` selects Native C++ when the ABI
and at least one performance-qualified kernel are detected. Unqualified or
unsupported algorithms continue through OpenCV/NumPy. On the V0.4.10 release
machine, exact bilinear demosaic is qualified while DPC remains experimental
because OpenCV DPC is faster.

The native extension is optional and is not part of `requirements.txt`.
