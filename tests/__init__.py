"""Test-process isolation for user-specific UI preferences."""

from __future__ import annotations

import atexit
import os
from pathlib import Path
import tempfile


_preference_path = Path(tempfile.gettempdir()) / (
    f"isp_tool_test_preferences_{os.getpid()}.json"
)
os.environ.setdefault(
    "ISP_TOOL_PREFERENCES_PATH", str(_preference_path)
)


@atexit.register
def _remove_test_preferences() -> None:
    try:
        _preference_path.unlink()
    except OSError:
        pass
