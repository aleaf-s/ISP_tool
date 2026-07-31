from __future__ import annotations

import importlib
from dataclasses import dataclass
from functools import lru_cache

from .base import BACKEND_ABI_VERSION, ProcessingBackend
from .native_backend import NativeBackend
from .opencv_backend import OpenCVBackend


BACKEND_PREFERENCES = (
    "Auto",
    "OpenCV / NumPy",
    "Native C++",
)
DEFAULT_BACKEND_PREFERENCE = "Auto"
_NATIVE_UNSET = object()


@dataclass(frozen=True)
class NativeDiscovery:
    module: object = None
    available: bool = False
    reason: str = ""
    version: str = ""


@dataclass(frozen=True)
class BackendSelection:
    preference: str
    backend: ProcessingBackend
    native: NativeDiscovery
    fallback_reason: str = ""

    @property
    def active_name(self) -> str:
        return self.backend.name

    @property
    def cache_key(self) -> str:
        return self.backend.cache_key


@lru_cache(maxsize=1)
def discover_native_backend() -> NativeDiscovery:
    try:
        module = importlib.import_module("isp_tool._native")
    except (ImportError, OSError) as exc:
        return NativeDiscovery(
            reason=f"未检测到可用的 isp_tool._native 扩展：{exc}"
        )
    abi = getattr(module, "ISP_BACKEND_ABI", None)
    if abi != BACKEND_ABI_VERSION:
        return NativeDiscovery(
            reason=(
                f"Native ABI 不匹配：检测到 {abi!r}，"
                f"需要 {BACKEND_ABI_VERSION}"
            )
        )
    kernels = (
        "demosaic_bilinear",
        "dpc_correct",
    )
    if not any(callable(getattr(module, name, None)) for name in kernels):
        return NativeDiscovery(
            reason="Native 扩展没有提供任何受支持的计算内核"
        )
    info = {}
    if callable(getattr(module, "backend_info", None)):
        value = module.backend_info()
        if isinstance(value, dict):
            info = value
    return NativeDiscovery(
        module=module,
        available=True,
        version=str(info.get("version", "unknown")),
    )


def _native_discovery(native_module=_NATIVE_UNSET) -> NativeDiscovery:
    if native_module is _NATIVE_UNSET:
        return discover_native_backend()
    if native_module is None:
        return NativeDiscovery(reason="Native 扩展不可用")
    abi = getattr(native_module, "ISP_BACKEND_ABI", None)
    if abi != BACKEND_ABI_VERSION:
        return NativeDiscovery(
            reason=f"Native ABI 不匹配：{abi!r}"
        )
    if not any(
        callable(getattr(native_module, name, None))
        for name in ("demosaic_bilinear", "dpc_correct")
    ):
        return NativeDiscovery(
            reason="Native 扩展没有提供受支持的计算内核"
        )
    info = {}
    if callable(getattr(native_module, "backend_info", None)):
        value = native_module.backend_info()
        if isinstance(value, dict):
            info = value
    return NativeDiscovery(
        module=native_module,
        available=True,
        version=str(info.get("version", "unknown")),
    )


def normalize_backend_preference(value: str) -> str:
    text = str(value)
    if text not in BACKEND_PREFERENCES:
        return DEFAULT_BACKEND_PREFERENCE
    return text


def select_backend(
    preference: str = DEFAULT_BACKEND_PREFERENCE,
    *,
    native_module=_NATIVE_UNSET,
) -> BackendSelection:
    preference = normalize_backend_preference(preference)
    native = _native_discovery(native_module)
    wants_native = preference in {"Auto", "Native C++"}
    if wants_native and native.available:
        return BackendSelection(
            preference,
            NativeBackend(
                native.module,
                force_all_native=(preference == "Native C++"),
            ),
            native,
        )
    fallback_reason = (
        native.reason if preference == "Native C++" else ""
    )
    return BackendSelection(
        preference,
        OpenCVBackend(),
        native,
        fallback_reason,
    )


@lru_cache(maxsize=1)
def get_default_backend() -> ProcessingBackend:
    return select_backend("OpenCV / NumPy").backend
