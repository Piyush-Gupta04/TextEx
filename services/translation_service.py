"""
services/translation_service.py
================================
Translation service for Smart Text Extractor.

Architecture:
    - Completely separated from OCR logic.
    - All translation runs in a QThread worker (_TranslationWorker).
    - Supports automatic source language detection via deep-translator.
    - Preserves line breaks, punctuation, spacing, Unicode, and multilingual
      text formatting by translating line-by-line (preserving structure) and
      then reassembling the result.

Supported target languages:
    English, Hindi, Urdu, Arabic, French, German, Spanish,
    Russian, Chinese (Simplified), Japanese, Korean.

Usage (from app.py):
    svc = TranslationService()
    worker = svc.create_worker(text, target_lang_code)
    worker.result_ready.connect(on_translation_done)
    worker.error_occurred.connect(on_translation_error)
    worker.start()
"""

from __future__ import annotations

import logging
import re

from PyQt6.QtCore import QObject, QThread, pyqtSignal

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Language Map
# ─────────────────────────────────────────────────────────────────────────────

#: Maps human-readable display name -> deep-translator language code
SUPPORTED_LANGUAGES: dict[str, str] = {
    "English":            "en",
    "Hindi":              "hi",
    "Urdu":               "ur",
    "Arabic":             "ar",
    "French":             "fr",
    "German":             "de",
    "Spanish":            "es",
    "Russian":            "ru",
    "Chinese (Simplified)": "zh-CN",
    "Japanese":           "ja",
    "Korean":             "ko",
}

#: Default target language display name
DEFAULT_TARGET_LANG = "English"


def get_language_code(display_name: str) -> str:
    """Return the deep-translator language code for a display name."""
    return SUPPORTED_LANGUAGES.get(display_name, "en")


def get_display_name(lang_code: str) -> str:
    """Return the display name for a language code (reverse lookup)."""
    for name, code in SUPPORTED_LANGUAGES.items():
        if code == lang_code:
            return name
    return lang_code


# ─────────────────────────────────────────────────────────────────────────────
# Translation Worker
# ─────────────────────────────────────────────────────────────────────────────

class _TranslationWorker(QThread):
    """
    Runs a single translation job in a background thread.

    Strategy for preserving formatting:
        - Split input text on newlines.
        - Translate each non-empty line individually.
        - Empty lines (paragraph breaks) are preserved as-is.
        - Reassemble with the original line break structure.

    This avoids translation engines collapsing or misinterpreting multi-line
    text while still sending complete sentences per line for best accuracy.

    Signals:
        result_ready(translated_text, detected_source_lang):
            Fired on success.  detected_source_lang may be '' if unavailable.
        error_occurred(user_friendly_message):
            Fired on failure.  OCR text should be kept unchanged by caller.
    """

    result_ready   = pyqtSignal(str, str)  # translated_text, detected_lang
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        text: str,
        target_lang_code: str,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._text       = text
        self._target     = target_lang_code
        self._detected   = ""

    # ------------------------------------------------------------------

    def run(self) -> None:
        try:
            from deep_translator import GoogleTranslator  # type: ignore
        except ImportError:
            self.error_occurred.emit(
                "Translation library not installed.\n"
                "Run:  pip install deep-translator"
            )
            return

        if not self._text.strip():
            self.result_ready.emit("", "")
            return

        try:
            translated, detected = self._translate(GoogleTranslator)
            self.result_ready.emit(translated, detected)
        except Exception as exc:
            logger.exception("[TranslationWorker] Translation failed: %s", exc)
            self.error_occurred.emit(
                f"Translation failed: {exc}\n\n"
                "Check your internet connection and try again."
            )

    # ------------------------------------------------------------------

    def _translate(self, GoogleTranslator) -> tuple[str, str]:
        """
        Translate self._text to self._target.

        Returns (translated_text, detected_source_lang).
        Preserves blank lines and original line structure.
        """
        lines = self._text.split("\n")
        translated_lines: list[str] = []
        detected: str = ""

        # Batch non-empty lines to reduce API calls while still
        # detecting the source language from the first batch.
        batch_indices: list[int] = []
        batch_texts:   list[str] = []

        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped:
                batch_indices.append(i)
                batch_texts.append(stripped)

        # Initialise the output list with original lines (blanks preserved)
        translated_lines = list(lines)

        if not batch_texts:
            return self._text, detected

        # Translate in chunks of 50 lines (GoogleTranslator limit is 5000 chars)
        chunk_size = 30
        for chunk_start in range(0, len(batch_texts), chunk_size):
            chunk = batch_texts[chunk_start : chunk_start + chunk_size]
            chunk_idx = batch_indices[chunk_start : chunk_start + chunk_size]

            # Join with a unique placeholder so we can split back
            separator = "\n||||\n"
            joined    = separator.join(chunk)

            try:
                translator = GoogleTranslator(source="auto", target=self._target)
                result_joined = translator.translate(joined)
                if not result_joined:
                    # Fallback: keep originals for this chunk
                    continue
            except Exception as exc:
                logger.warning(
                    "[TranslationWorker] Chunk %d failed: %s", chunk_start, exc
                )
                # Keep original text for this chunk; don't abort entirely
                continue

            # Try to detect source language (best-effort, first chunk only)
            if not detected and chunk_start == 0:
                try:
                    detect_result = translator.detect(chunk[0])
                    if detect_result:
                        detected = str(detect_result)
                except Exception:
                    pass

            # Split result back by separator (translator may add spaces around it)
            result_parts = re.split(r"\n?\|\|\|\|\n?", result_joined)

            # Align translated parts with original indices
            for j, orig_idx in enumerate(chunk_idx):
                if j < len(result_parts):
                    translated_lines[orig_idx] = result_parts[j].strip()
                # else: keep original line

        return "\n".join(translated_lines), detected


# ─────────────────────────────────────────────────────────────────────────────
# Service
# ─────────────────────────────────────────────────────────────────────────────

class TranslationService:
    """
    Lightweight factory for translation workers.

    Keeps the service layer thin and stateless — all state lives in the
    QThread worker created per translation job.

    Usage:
        svc = TranslationService()
        worker = svc.create_worker(ocr_text, "hi")
        worker.result_ready.connect(my_slot)
        worker.error_occurred.connect(my_error_slot)
        worker.start()
    """

    @staticmethod
    def create_worker(
        text: str,
        target_lang_code: str,
        parent: QObject | None = None,
    ) -> _TranslationWorker:
        """
        Create a translation worker thread.

        Args:
            text:             The OCR (or any) text to translate.
            target_lang_code: deep-translator language code, e.g. "hi", "ar".
            parent:           Optional Qt parent for memory management.

        Returns:
            A _TranslationWorker instance (not yet started).
            Call .start() to begin translation.
        """
        return _TranslationWorker(text, target_lang_code, parent)

    @staticmethod
    def available_languages() -> dict[str, str]:
        """Return {display_name: lang_code} for all supported target languages."""
        return dict(SUPPORTED_LANGUAGES)
