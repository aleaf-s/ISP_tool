"""Setuptools build entry point for the optional native backend."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

from setuptools import setup

from pybind11.setup_helpers import Pybind11Extension, build_ext


PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)


def bootstrap_windows_build_path():
    """Make a normal PowerShell as build-capable as a VS developer shell."""

    if os.name != "nt":
        return []
    directories = []
    if not shutil.which("cl"):
        vswhere = Path(
            r"C:\Program Files (x86)\Microsoft Visual Studio"
            r"\Installer\vswhere.exe"
        )
        if vswhere.exists():
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
            compilers = sorted(
                root.glob(
                    "VC/Tools/MSVC/*/bin/Hostx64/x64/cl.exe"
                ),
                reverse=True,
            )
            if compilers:
                directories.append(str(compilers[0].parent))
    windows_kit = Path(
        r"C:\Program Files (x86)\Windows Kits\10\bin"
    )
    resource_compilers = sorted(
        windows_kit.glob("*/x64/rc.exe"), reverse=True
    )
    if resource_compilers:
        directories.append(str(resource_compilers[0].parent))
    if directories:
        os.environ["PATH"] = os.pathsep.join(
            directories + [os.environ.get("PATH", "")]
        )
    return directories


windows_tool_directories = bootstrap_windows_build_path()
compile_args = (
    ["/O2", "/EHsc", "/utf-8"] if os.name == "nt" else ["-O3"]
)


class NativeBuildExt(build_ext):
    """Preserve Windows SDK tools omitted by some setuptools VS probes."""

    def build_extensions(self):
        compiler = self.compiler
        if os.name == "nt":
            if not getattr(compiler, "initialized", True):
                compiler.initialize()
            if hasattr(compiler, "_paths"):
                current = compiler._paths.split(os.pathsep)
                compiler._paths = os.pathsep.join(
                    windows_tool_directories + current
                )
        super().build_extensions()

extension = Pybind11Extension(
    "isp_tool._native",
    [str(PROJECT_ROOT / "native" / "isp_native.cpp")],
    define_macros=[("ISP_NATIVE_VERSION", '"0.4.10"')],
    cxx_std=17,
    extra_compile_args=compile_args,
)

setup(
    name="isp-raw-simulator-native",
    version="0.4.10",
    description="Optional C++ kernels for ISP RAW Visual Simulator",
    packages=["isp_tool"],
    ext_modules=[extension],
    cmdclass={"build_ext": NativeBuildExt},
)
