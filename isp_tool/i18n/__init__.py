from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Callable, Dict, Optional

from .resources import TRANSLATIONS


DEFAULT_LANGUAGE = "zh_CN"
SUPPORTED_LANGUAGES = ("zh_CN", "en_US")
LOGGER = logging.getLogger(__name__)


class Translator:
    """Small runtime translator with deterministic default-language fallback."""

    def __init__(self, language: str = DEFAULT_LANGUAGE, debug: bool = False):
        self.language = self.normalize(language)
        self.debug = bool(debug)
        self._listeners: list[Callable[[str], None]] = []

    @staticmethod
    def normalize(language: object) -> str:
        value = str(language or DEFAULT_LANGUAGE)
        return value if value in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE

    def tr(self, key: str, **values) -> str:
        text = TRANSLATIONS.get(self.language, {}).get(key)
        if text is None:
            text = TRANSLATIONS[DEFAULT_LANGUAGE].get(key)
        if text is None:
            if self.debug:
                LOGGER.warning("Missing translation key: %s", key)
            text = key
        try:
            return str(text).format(**values)
        except (KeyError, ValueError):
            if self.debug:
                LOGGER.warning("Invalid translation arguments for %s", key)
            return str(text)

    def set_language(self, language: str) -> bool:
        normalized = self.normalize(language)
        if normalized == self.language:
            return False
        self.language = normalized
        for listener in tuple(self._listeners):
            listener(normalized)
        return True

    def subscribe(self, listener: Callable[[str], None]) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def unsubscribe(self, listener: Callable[[str], None]) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)


def preferences_path() -> Path:
    override = os.environ.get("ISP_TOOL_PREFERENCES_PATH")
    if override:
        return Path(override)
    base = Path(os.environ.get("APPDATA", Path.home()))
    return base / "ISP RAW Visual Simulator" / "ui_preferences.json"


def load_language(path: Optional[Path] = None) -> str:
    target = Path(path) if path is not None else preferences_path()
    try:
        data: Dict[str, object] = json.loads(target.read_text("utf-8"))
    except (OSError, ValueError, TypeError):
        return DEFAULT_LANGUAGE
    return Translator.normalize(data.get("language"))


def save_language(language: str, path: Optional[Path] = None) -> bool:
    target = Path(path) if path is not None else preferences_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                {"language": Translator.normalize(language)},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError:
        return False
    return True


__all__ = [
    "DEFAULT_LANGUAGE",
    "SUPPORTED_LANGUAGES",
    "Translator",
    "load_language",
    "preferences_path",
    "save_language",
]
