"""
core/settings.py
================
Singleton application settings manager for Smart Text Extractor.

Wraps Qt's QSettings (INI backend) with typed properties and defaults.
All settings persist across sessions in the system's standard config
location (HKCU on Windows, ~/.config on Linux/macOS).

Usage:
    from core.settings import Settings

    s = Settings.instance()
    s.auto_clipboard = True
    threshold = s.confidence_threshold   # 0.5
"""

from __future__ import annotations
from PyQt6.QtCore import QSettings


class Settings:
    """
    Application-wide settings with typed properties and defaults.
    Instantiate via Settings.instance() to get the shared singleton.
    """

    _instance: "Settings | None" = None

    # ── Defaults ──────────────────────────────────────────────────────────
    _DEFAULTS: dict = {
        "general/start_minimized":    False,
        "general/minimize_to_tray":   True,
        "general/always_on_top":      False,
        "general/auto_clipboard":     True,
        "ocr/language":               "en",
        "ocr/confidence_threshold":   0.5,
        "hotkey/combo":               "ctrl+alt+x",
        "storage/history_limit":      500,
        "storage/keep_screenshots":   True,
        # Translation
        "translation/auto_translate":      False,
        "translation/target_lang":         "English",
        # Overlay (Phase 7)
        "overlay/show_result_overlay":     True,
        "overlay/autohide_secs":           10,   # 0 = never
        # Tray / hotkey (Phase 6)
        "hotkey/works_when_hidden":        True,
    }

    @classmethod
    def instance(cls) -> "Settings":
        """Return (or create) the shared Settings singleton."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self._qs = QSettings("TextEx", "SmartTextExtractor")

    # ── Internal helpers ──────────────────────────────────────────────────

    def _get(self, key: str, typ: type):
        default = self._DEFAULTS.get(key)
        v = self._qs.value(key, default)
        # QSettings may return strings; coerce to the right type
        if typ is bool:
            if isinstance(v, str):
                return v.lower() in ("true", "1", "yes")
            return bool(v)
        if typ is int:
            return int(v)
        if typ is float:
            return float(v)
        return v

    def _set(self, key: str, value) -> None:
        self._qs.setValue(key, value)

    def reset(self) -> None:
        """Restore all settings to their defaults."""
        self._qs.clear()

    def sync(self) -> None:
        """Force-flush settings to disk."""
        self._qs.sync()

    # ── General ───────────────────────────────────────────────────────────

    @property
    def start_minimized(self) -> bool:
        return self._get("general/start_minimized", bool)

    @start_minimized.setter
    def start_minimized(self, v: bool) -> None:
        self._set("general/start_minimized", v)

    @property
    def minimize_to_tray(self) -> bool:
        return self._get("general/minimize_to_tray", bool)

    @minimize_to_tray.setter
    def minimize_to_tray(self, v: bool) -> None:
        self._set("general/minimize_to_tray", v)

    @property
    def always_on_top(self) -> bool:
        return self._get("general/always_on_top", bool)

    @always_on_top.setter
    def always_on_top(self, v: bool) -> None:
        self._set("general/always_on_top", v)

    @property
    def auto_clipboard(self) -> bool:
        return self._get("general/auto_clipboard", bool)

    @auto_clipboard.setter
    def auto_clipboard(self, v: bool) -> None:
        self._set("general/auto_clipboard", v)

    # ── OCR ───────────────────────────────────────────────────────────────

    @property
    def ocr_language(self) -> str:
        return self._get("ocr/language", str)

    @ocr_language.setter
    def ocr_language(self, v: str) -> None:
        self._set("ocr/language", v)

    @property
    def confidence_threshold(self) -> float:
        return self._get("ocr/confidence_threshold", float)

    @confidence_threshold.setter
    def confidence_threshold(self, v: float) -> None:
        self._set("ocr/confidence_threshold", v)

    # ── Hotkey ────────────────────────────────────────────────────────────

    @property
    def hotkey(self) -> str:
        return self._get("hotkey/combo", str)

    @hotkey.setter
    def hotkey(self, v: str) -> None:
        self._set("hotkey/combo", v)

    # ── Storage ───────────────────────────────────────────────────────────

    @property
    def history_limit(self) -> int:
        return self._get("storage/history_limit", int)

    @history_limit.setter
    def history_limit(self, v: int) -> None:
        self._set("storage/history_limit", v)

    @property
    def keep_screenshots(self) -> bool:
        return self._get("storage/keep_screenshots", bool)

    @keep_screenshots.setter
    def keep_screenshots(self, v: bool) -> None:
        self._set("storage/keep_screenshots", v)

    # ── Translation ───────────────────────────────────────────────────────

    @property
    def auto_translate(self) -> bool:
        return self._get("translation/auto_translate", bool)

    @auto_translate.setter
    def auto_translate(self, v: bool) -> None:
        self._set("translation/auto_translate", v)

    @property
    def translation_target_lang(self) -> str:
        """Display name of the target language, e.g. 'Hindi'."""
        return self._get("translation/target_lang", str)

    @translation_target_lang.setter
    def translation_target_lang(self, v: str) -> None:
        self._set("translation/target_lang", v)

    # ── Overlay ─────────────────────────────────────────────────────

    @property
    def show_result_overlay(self) -> bool:
        """Show floating result overlay after OCR."""
        return self._get("overlay/show_result_overlay", bool)

    @show_result_overlay.setter
    def show_result_overlay(self, v: bool) -> None:
        self._set("overlay/show_result_overlay", v)

    @property
    def overlay_autohide_secs(self) -> int:
        """Seconds before overlay auto-hides. 0 = never."""
        return self._get("overlay/autohide_secs", int)

    @overlay_autohide_secs.setter
    def overlay_autohide_secs(self, v: int) -> None:
        self._set("overlay/autohide_secs", v)

    # ── Hotkey when hidden ──────────────────────────────────────

    @property
    def hotkey_works_when_hidden(self) -> bool:
        """OCR hotkey fires even when the main window is hidden."""
        return self._get("hotkey/works_when_hidden", bool)

    @hotkey_works_when_hidden.setter
    def hotkey_works_when_hidden(self, v: bool) -> None:
        self._set("hotkey/works_when_hidden", v)
