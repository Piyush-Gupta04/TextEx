"""
services/ocr_service.py
=======================
OCR service for Smart Text Extractor.

Uses PaddleOCR 3.6.0 + PaddlePaddle 3.3.1 (Python 3.12 venv).

Critical setup (must be done in main.py BEFORE this module is imported):
    os.environ["PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT"] = "0"

    Without this, PaddleX uses oneDNN by default on CPU. PaddlePaddle 3.3.1
    on Windows crashes with NotImplementedError in onednn_instruction.cc.

Model configuration:
    ocr_version="PP-OCRv4"              — stable (PP-OCRv5 server det fails)
    use_doc_orientation_classify=False  — skips PP-LCNet (CPU incompatible)
    use_doc_unwarping=False             — document de-warping not needed
    use_textline_orientation=False      — textline classifier not needed

PaddleOCR 3.x result format:
    result: list[OCRResult]   — one item per input image
    OCRResult is a dict subclass; access fields with .get():
        'rec_texts':  list[str]   — recognised text strings
        'rec_scores': list[float] — confidence per string (0-1)

Supported languages (PaddleOCR lang codes):
    "en"  — English
    "hi"  — Hindi (Devanagari)
    "ch"  — Simplified Chinese (also handles mixed English)

Language switching:
    Call reload(new_language) to swap models at runtime. This blocks
    for several seconds while the new model loads — always call from
    a background thread.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import numpy as np
from paddleocr import PaddleOCR

logger = logging.getLogger(__name__)

# Human-readable labels for supported languages
LANGUAGE_LABELS: dict[str, str] = {
    "en": "English",
    "hi": "Hindi",
    "ch": "Mixed (English + Hindi)",
}


class OCRService:
    """
    Wraps PaddleOCR 3.6.0 for text extraction from images.

    Supports runtime language switching via reload().  The engine is
    initialised once per language and kept in memory until replaced.

    Usage:
        service = OCRService(language="en", min_confidence=0.5)
        text = service.recognize(image_bgr)
        print(service.last_duration)   # seconds
    """

    def __init__(
        self,
        language: str = "en",
        min_confidence: float = 0.5,
    ) -> None:
        """
        Initialise and load the PaddleOCR pipeline.

        Args:
            language:       PaddleOCR language code ("en", "hi", "ch").
            min_confidence: Minimum recognition confidence to include a
                            text line in the output (0.0–1.0).
        """
        self._language = language
        self.min_confidence = min_confidence
        self._engine: Optional[PaddleOCR] = None
        self.last_duration: float = 0.0  # seconds for last recognize() call

        # Suppress noisy internal loggers from PaddleX / PaddlePaddle
        import logging as _log
        for _name in ("ppocr", "paddle", "PaddleOCR", "ppdet",
                       "ppocrlite", "paddlex", "root"):
            _log.getLogger(_name).setLevel(_log.WARNING)

        self._load(language)

    # ──────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────

    def load(self) -> None:
        """
        No-op — kept for compatibility with core/app.py's _OCRLoaderWorker.
        The engine is already initialised in __init__.
        """

    def reload(self, language: str) -> None:
        """
        Replace the current OCR engine with one for a different language.

        Blocks while the new model loads (several seconds on first run
        while models download; faster on cache hits).  Always call from
        a background thread.

        Args:
            language: New PaddleOCR language code ("en", "hi", "ch").
        """
        if language == self._language and self._engine is not None:
            logger.info("[OCRService] Language unchanged (%s) — skipping reload.", language)
            return
        logger.info("[OCRService] Reloading OCR engine for language: %s", language)
        print(f"[OCRService] Reloading for language '{language}'...")
        self._engine = None  # release old engine memory
        self._load(language)

    def recognize(self, image: np.ndarray) -> str:
        """
        Run OCR on a BGR numpy image and return all detected text.

        Sets self.last_duration to the wall-clock seconds taken.

        Args:
            image: numpy array in BGR format (H x W x 3) from CaptureService.

        Returns:
            Detected text lines joined by newlines.
            Empty string if no text is found.

        Raises:
            RuntimeError: If the engine is not ready or inference fails.
        """
        if self._engine is None:
            raise RuntimeError(
                "PaddleOCR engine is not initialised. "
                "Check startup logs for details."
            )

        t0 = time.monotonic()
        try:
            result = self._engine.predict(image)
        except Exception as exc:
            logger.error("[OCRService] Inference failed: %s", exc)
            raise RuntimeError(f"OCR inference failed: {exc}") from exc
        finally:
            self.last_duration = time.monotonic() - t0

        lines = self._extract_lines(result)
        extracted = "\n".join(lines)

        if extracted:
            print(
                f"[OCRService] {len(lines)} line(s), "
                f"{len(extracted.split())} word(s) in "
                f"{self.last_duration:.2f}s."
            )
            logger.info(
                "[OCRService] Extracted %d line(s), %d word(s) in %.2fs.",
                len(lines), len(extracted.split()), self.last_duration,
            )
        else:
            print(f"[OCRService] No text detected ({self.last_duration:.2f}s).")
            logger.info("[OCRService] No text detected.")

        return extracted

    # ──────────────────────────────────────────────────────────────────────
    # Properties
    # ──────────────────────────────────────────────────────────────────────

    @property
    def is_loaded(self) -> bool:
        """True when the OCR engine is ready for inference."""
        return self._engine is not None

    @property
    def language(self) -> str:
        """Current PaddleOCR language code."""
        return self._language

    @property
    def language_label(self) -> str:
        """Human-readable label for the current language."""
        return LANGUAGE_LABELS.get(self._language, self._language)

    # ──────────────────────────────────────────────────────────────────────
    # Internal
    # ──────────────────────────────────────────────────────────────────────

    def _load(self, language: str) -> None:
        """
        Create and initialise a PaddleOCR instance for the given language.

        PP-OCRv4 is only available for 'en' (English) and 'ch' (Chinese /
        mixed).  For all other language codes (e.g. 'hi' for Hindi),
        the ocr_version argument is omitted so PaddleOCR uses its
        default multilingual pipeline.

        Raises:
            RuntimeError: If PaddleOCR fails to initialise.
        """
        label = LANGUAGE_LABELS.get(language, language)
        logger.info("[OCRService] Loading PaddleOCR (%s)...", label)
        print(f"[OCRService] Loading PaddleOCR model ({label})...")

        # PP-OCRv4 models exist only for English and Chinese/mixed
        ppv4_languages = {"en", "ch"}
        kwargs: dict = dict(
            lang=language,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
        if language in ppv4_languages:
            kwargs["ocr_version"] = "PP-OCRv4"

        try:
            self._engine = PaddleOCR(**kwargs)
            self._language = language
            logger.info("[OCRService] PaddleOCR loaded successfully (%s).", label)
            print(f"[OCRService] PaddleOCR loaded successfully ({label}).")
        except Exception as exc:
            self._engine = None
            logger.error("[OCRService] Failed to load PaddleOCR: %s", exc)
            raise RuntimeError(f"Failed to initialise PaddleOCR: {exc}") from exc

    def _extract_lines(self, result) -> list[str]:
        """
        Parse PaddleOCR 3.x predict() output into a flat list of strings.

        OCRResult is a dict subclass — access fields with .get().
        Fields: 'rec_texts' (list[str]), 'rec_scores' (list[float]).

        Args:
            result: Raw value from self._engine.predict().

        Returns:
            Text strings that passed min_confidence, in detection order.
        """
        if not result:
            return []

        lines: list[str] = []
        for item in result:
            texts: list  = item.get("rec_texts",  []) or []
            scores: list = item.get("rec_scores", []) or []

            # Safety: pad scores if shorter than texts
            if len(scores) < len(texts):
                scores = list(scores) + [1.0] * (len(texts) - len(scores))

            for text, score in zip(texts, scores):
                text = (text or "").strip()
                if text and (score is None or float(score) >= self.min_confidence):
                    lines.append(text)

        return lines
