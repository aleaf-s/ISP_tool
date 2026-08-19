from __future__ import annotations

from typing import Any, Mapping, Optional

from ...i18n import Translator, load_language, save_language


class LanguageController:
    """Own language selection and persistence outside the main window.

    Rendering translated text remains a view responsibility.  Keeping the
    preference and fallback rules here prevents future workspaces from each
    inventing their own language state.
    """

    def __init__(
        self,
        language: Optional[str] = None,
        translator: Optional[Translator] = None,
    ) -> None:
        self.translator = translator or Translator(
            language or load_language()
        )

    @property
    def language(self) -> str:
        return self.translator.language

    def tr(self, key: str, **values: Any) -> str:
        return self.translator.tr(key, **values)

    def set_language(
        self,
        language: str,
        *,
        persist: bool = True,
    ) -> bool:
        changed = self.translator.set_language(language)
        if persist:
            save_language(self.translator.language)
        return changed

    def restore_from_ui_state(
        self,
        ui_state: Mapping[str, Any],
        *,
        persist: bool = True,
    ) -> bool:
        language = ui_state.get("language")
        if not isinstance(language, str) or not language.strip():
            return False
        return self.set_language(language, persist=persist)
