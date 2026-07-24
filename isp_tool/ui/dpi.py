from __future__ import annotations

import ctypes
import sys
from typing import Optional


_DPI_AWARENESS_RESULT: Optional[str] = None


def enable_process_dpi_awareness(platform: Optional[str] = None) -> str:
    """Enable the best available Windows DPI mode before creating Tk.

    The function is idempotent and deliberately safe on non-Windows hosts so
    unit tests and Linux desktop sessions can import the UI unchanged.
    """

    global _DPI_AWARENESS_RESULT
    if _DPI_AWARENESS_RESULT is not None:
        return _DPI_AWARENESS_RESULT
    platform = sys.platform if platform is None else platform
    if platform != "win32":
        _DPI_AWARENESS_RESULT = "not-windows"
        return _DPI_AWARENESS_RESULT
    try:
        user32 = ctypes.windll.user32
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 == (HANDLE)-4.
        context = ctypes.c_void_p(-4)
        if user32.SetProcessDpiAwarenessContext(context):
            _DPI_AWARENESS_RESULT = "per-monitor-v2"
            return _DPI_AWARENESS_RESULT
    except (AttributeError, OSError, TypeError):
        pass
    try:
        shcore = ctypes.windll.shcore
        # PROCESS_PER_MONITOR_DPI_AWARE == 2.
        result = int(shcore.SetProcessDpiAwareness(2))
        if result in {0, -2147024891}:  # S_OK or already configured.
            _DPI_AWARENESS_RESULT = "per-monitor"
            return _DPI_AWARENESS_RESULT
    except (AttributeError, OSError, TypeError, ValueError):
        pass
    try:
        if ctypes.windll.user32.SetProcessDPIAware():
            _DPI_AWARENESS_RESULT = "system"
            return _DPI_AWARENESS_RESULT
    except (AttributeError, OSError, TypeError):
        pass
    _DPI_AWARENESS_RESULT = "unavailable"
    return _DPI_AWARENESS_RESULT
