"""
Lightweight translations loader with per-language JSON sources.

This replaces the previous monolithic Python dictionary (≈100k lines) with
UTF-8 json files stored under ``i18n/``.  Loading is lazy and works in both
development and frozen (PyInstaller) builds.
"""

from __future__ import annotations

import json
import sys
from functools import lru_cache
from pathlib import Path
from typing import Dict, Any


class Translations:
    """Runtime translation helper with fallback logic."""

    AVAILABLE_LANGUAGES = {
        "es": "🇲🇽 Español",
        "en": "🇺🇸 English",
        "fr": "🇫🇷 Français",
        "de": "🇩🇪 Deutsch",
        "pt": "🇧🇷 Português",
    }

    def __init__(self, base_path: str | Path | None = None) -> None:
        self.current_language = "es"
        self._cache: Dict[str, Dict[str, str]] = {}
        self._base_path = self._resolve_base_path(base_path)

    @property
    def translations(self) -> Dict[str, Dict[str, str]]:
        """Return every loaded translation map (loads lazily on first use)."""
        for lang_code in self.AVAILABLE_LANGUAGES:
            self._ensure_language_loaded(lang_code)
        return self._cache

    def set_language(self, language_code: str) -> bool:
        """Update current language if it exists."""
        if language_code in self.AVAILABLE_LANGUAGES:
            self.current_language = language_code
            return True
        return False

    def get(self, key: str, *args: Any) -> str:
        """
        Obtain a translation with the following fallback order:
        1. Current language
        2. Spanish
        3. English
        4. The key itself
        """
        for lang in (self.current_language, "es", "en"):
            data = self._ensure_language_loaded(lang)
            if data and key in data:
                text = data[key]
                return text.format(*args) if args else text
        return key

    def get_available_languages(self) -> Dict[str, str]:
        """Expose language codes and human-friendly labels."""
        return self.AVAILABLE_LANGUAGES.copy()

    def get_current_language_name(self) -> str:
        """Return friendly name for current language."""
        return self.AVAILABLE_LANGUAGES.get(self.current_language, "🇲🇽 Español")

    def _ensure_language_loaded(self, language_code: str) -> Dict[str, str]:
        """Load JSON file for language only once."""
        if language_code not in self.AVAILABLE_LANGUAGES:
            return {}
        if language_code not in self._cache:
            self._cache[language_code] = self._load_language_file(language_code)
        return self._cache[language_code]

    def _load_language_file(self, language_code: str) -> Dict[str, str]:
        path = self._base_path / f"{language_code}.json"
        if not path.exists():
            raise FileNotFoundError(f"No translation file found for '{language_code}' at {path}")
        with path.open("r", encoding="utf-8") as handler:
            return json.load(handler)

    @staticmethod
    @lru_cache(maxsize=1)
    def _resolve_base_path(base_path: str | Path | None) -> Path:
        """Determine where JSON files live (dev vs frozen build)."""
        if base_path:
            return Path(base_path)
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            return Path(sys._MEIPASS) / "i18n"  # type: ignore[attr-defined]
        return Path(__file__).resolve().parent / "i18n"
