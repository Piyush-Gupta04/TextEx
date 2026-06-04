"""
services/auto_ocr_service.py
============================
Automatic multilingual OCR engine for Smart Text Extractor.

Supports 10+ languages with NO user language selection:

    Script group          PaddleOCR code  Languages covered
    ─────────────────── ─────────────── ──────────────────────────────
    Latin (PP-OCRv4)    en              English, French, Spanish, German
    Chinese (PP-OCRv4)  ch              Chinese (simplified/traditional)
    Arabic/Urdu         ar              Arabic, Urdu
    Devanagari          hi              Hindi
    Cyrillic            ru              Russian (and related Cyrillic)
    Japanese            japan           Japanese (Hiragana/Katakana/Kanji)
    Korean              korean          Korean (Hangul)

Recognition strategy — per-region best-engine merge
────────────────────────────────────────────────────
Previous approach (BROKEN for mixed-script input):
    • Tried engines in order; picked whichever produced the highest
      aggregate score (mean_confidence × word_count).
    • FATAL flaw: The English engine misreads non-Latin characters as
      garbage tokens with moderate confidence, accumulating a higher
      aggregate score than specialist engines that only read their own
      script → English always won, non-Latin was garbled.

Current approach (CORRECT):
    1. ALL loaded engines are run on the full image.
    2. Each engine returns a list of text regions with bounding polygons,
       recognised text, and per-region confidence scores.
    3. Bounding polygons from different engines that cover the same
       physical area on the image (IoU ≥ IOU_THRESHOLD = 0.30) are
       grouped as "the same region".
    4. Within each group, the engine that produced the highest confidence
       score wins — giving each script its specialist engine:
           Latin letters  → 'en'   engine  (0.98+)
           Hindi script   → 'hi'   engine  (0.90+)
           Arabic script  → 'ar'   engine  (0.90+)
           Korean script  → 'korean' engine
           Japanese script→ 'japan'  engine
           CJK characters → 'ch'   engine
    5. Regions are then sorted in reading order (top-to-bottom,
       left-to-right) respecting line-band grouping.
    6. Fallback: if no engine returns bounding-box information, the
       service selects the single engine whose regions have the highest
       sum of confidence scores (better than word-count × mean_conf).

Compatibility: PaddleOCR 3.6.0 / PaddlePaddle 3.3.1 / Python 3.12 / Windows.
Set PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT=0 in main.py before any import.
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Optional

import numpy as np
from paddleocr import PaddleOCR

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Engine configuration
# ─────────────────────────────────────────────────────────────────────────────

# (lang_code, use_pp_ocrv4, display_name)
# use_pp_ocrv4=True  → pass ocr_version="PP-OCRv4" (mobile, ~50 MB)
# use_pp_ocrv4=False → omit ocr_version (PaddleOCR picks best available model)
ENGINE_SPECS: list[tuple[str, bool, str]] = [
    ("en",     True,  "Latin / English"),
    ("ch",     True,  "Chinese"),
    ("ar",     False, "Arabic / Urdu"),
    ("hi",     False, "Hindi / Devanagari"),
    ("ru",     False, "Russian / Cyrillic"),
    ("japan",  False, "Japanese"),
    ("korean", False, "Korean"),
]

# All engines run on every image — order only matters for logging
RECOGNITION_ORDER: list[str] = ["en", "ch", "ar", "hi", "ru", "japan", "korean"]

# Bounding-box IoU threshold: two detected regions with IoU ≥ this value are
# considered the same physical area on the image.
IOU_THRESHOLD = 0.30

# Possible keys for polygon data in PaddleOCR 3.x result dicts.
# The API key changed across minor versions — try all of them.
_BOX_KEYS = ("det_polys", "dt_polys", "det_boxes", "boxes")


# ─────────────────────────────────────────────────────────────────────────────
# Region dict schema (internal)
# ─────────────────────────────────────────────────────────────────────────────
# {
#   "text":   str,                       # recognised text string
#   "score":  float,                     # per-region recognition confidence
#   "rect":   (x1, y1, x2, y2) | None,  # axis-aligned bounding rect
#   "engine": str,                       # which engine produced this
# }


# ─────────────────────────────────────────────────────────────────────────────
# AutoOCRService
# ─────────────────────────────────────────────────────────────────────────────

class AutoOCRService:
    """
    Automatic multilingual OCR service supporting 10+ languages.

    Usage:
        svc = AutoOCRService(min_confidence=0.5)
        svc.load_all()              # blocking — call from background thread
        text = svc.recognize(img)   # numpy BGR array
        print(svc.last_duration)    # seconds
        print(svc.engines_loaded)   # int (0–7)
    """

    def __init__(self, min_confidence: float = 0.5) -> None:
        self.min_confidence  = min_confidence
        self.last_duration:  float = 0.0
        self._engines:       dict[str, PaddleOCR] = {}
        self._failed:        dict[str, str]        = {}

    # ──────────────────────────────────────────────────────────────────────
    # Loading  (call from background QThread — blocks until complete)
    # ──────────────────────────────────────────────────────────────────────

    def load_all(
        self,
        on_progress: Optional[Callable[[int, int, str, Optional[str]], None]] = None,
    ) -> None:
        """
        Load all language engines SEQUENTIALLY.

        Sequential (not parallel) loading is intentional: loading multiple
        PaddleOCR instances concurrently causes peak RAM usage that can
        exceed 2 GB on systems with PP-OCRv5 server models, leading to
        out-of-memory crashes.  Sequential loading keeps peak usage to
        one model at a time.

        Args:
            on_progress: Optional callback(loaded, total, lang_code, error_or_None)
                         called after each engine attempt (success or failure).
                         Invoked from the calling thread — do NOT touch Qt
                         widgets from this callback; use Qt signals instead.
        """
        total = len(ENGINE_SPECS)

        for idx, (code, ppv4, name) in enumerate(ENGINE_SPECS, start=1):
            engine, error = self._load_one(code, ppv4, name)

            if engine is not None:
                self._engines[code] = engine
                print(f"[AutoOCR] ✔ {name} ({code}) loaded  [{idx}/{total}]")
                logger.info("[AutoOCR] Engine '%s' loaded [%d/%d].", code, idx, total)
            else:
                self._failed[code] = error or "unknown error"
                print(f"[AutoOCR] ✘ {name} ({code}) failed  [{idx}/{total}]: {error}")
                logger.warning("[AutoOCR] Engine '%s' failed: %s", code, error)

            if on_progress:
                # Pass the *actual* success count, not the attempt index.
                on_progress(len(self._engines), total, code, error)

        print(
            f"[AutoOCR] Done — {len(self._engines)}/{total} engines ready."
        )
        logger.info(
            "[AutoOCR] Loading complete: %d/%d engines ready.",
            len(self._engines), total,
        )

    # ──────────────────────────────────────────────────────────────────────
    # Recognition — per-region best-engine merge
    # ──────────────────────────────────────────────────────────────────────

    def recognize(self, image: np.ndarray) -> str:
        """
        Run multilingual OCR on a BGR numpy image.

        ALL loaded engines are run on the image.  For each detected text
        region the engine that produced the highest recognition confidence
        is selected, giving every script its specialist engine rather than
        forcing everything through the Latin/English model.

        Args:
            image: BGR numpy array (H × W × 3) from CaptureService.

        Returns:
            Extracted text lines joined by newlines, or "" if no text found.

        Raises:
            RuntimeError: If no engines were successfully loaded.
        """
        if not self._engines:
            raise RuntimeError(
                "No OCR engines are loaded. "
                "Call load_all() from a background thread first."
            )

        t0 = time.monotonic()

        # Step 1 — run EVERY loaded engine and collect per-region results
        engine_regions: dict[str, list[dict]] = {}
        for code in RECOGNITION_ORDER:
            if code not in self._engines:
                continue
            regions = self._run_engine_with_boxes(code, image)
            if regions:
                engine_regions[code] = regions
                logger.debug(
                    "[AutoOCR] Engine '%s': %d region(s) detected.",
                    code, len(regions),
                )

        self.last_duration = time.monotonic() - t0

        if not engine_regions:
            print(f"[AutoOCR] No text detected ({self.last_duration:.2f}s).")
            logger.info("[AutoOCR] No text detected.")
            return ""

        # Step 2 — merge: for each physical region keep highest-confidence engine
        merged = self._merge_by_region(engine_regions)

        # Step 3 — sort into reading order (top-to-bottom, left-to-right)
        merged = self._sort_reading_order(merged)

        # Step 4 — assemble final text, preserving original Unicode characters
        text = "\n".join(r["text"] for r in merged)

        if text.strip():
            words        = len(text.split())
            engines_used = sorted({r["engine"] for r in merged})
            print(
                f"[AutoOCR] {len(merged)} region(s), {words} word(s) "
                f"via {engines_used} in {self.last_duration:.2f}s."
            )
            logger.info(
                "[AutoOCR] %d region(s), %d word(s) via %s in %.2fs.",
                len(merged), words, engines_used, self.last_duration,
            )
        else:
            print(f"[AutoOCR] No text detected ({self.last_duration:.2f}s).")
            logger.info("[AutoOCR] No text detected.")

        return text

    # ──────────────────────────────────────────────────────────────────────
    # Properties
    # ──────────────────────────────────────────────────────────────────────

    @property
    def is_loaded(self) -> bool:
        """True when at least one engine is ready for inference."""
        return bool(self._engines)

    @property
    def engines_loaded(self) -> int:
        return len(self._engines)

    @property
    def engines_failed(self) -> int:
        return len(self._failed)

    @property
    def language_label(self) -> str:
        n = len(self._engines)
        return f"Auto Detect ({n} engine{'s' if n != 1 else ''})"

    # ──────────────────────────────────────────────────────────────────────
    # Internal — engine loading
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _load_one(
        code: str, ppv4: bool, name: str
    ) -> tuple[Optional[PaddleOCR], Optional[str]]:
        """
        Attempt to create a PaddleOCR engine for the given language code.

        Returns (engine, None) on success or (None, error_message) on failure.
        """
        try:
            kwargs: dict = dict(
                lang=code,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
            if ppv4:
                kwargs["ocr_version"] = "PP-OCRv4"
            engine = PaddleOCR(**kwargs)
            return engine, None
        except Exception as exc:
            return None, str(exc)

    # ──────────────────────────────────────────────────────────────────────
    # Internal — per-region inference
    # ──────────────────────────────────────────────────────────────────────

    def _run_engine_with_boxes(
        self, code: str, image: np.ndarray
    ) -> list[dict]:
        """
        Run one engine on the image.

        Returns a list of region dicts:
            {"text": str, "score": float, "rect": (x1,y1,x2,y2)|None, "engine": str}

        Only regions whose confidence score ≥ self.min_confidence are included.
        Regions with empty text are excluded.
        """
        engine = self._engines.get(code)
        if engine is None:
            return []
        try:
            result = engine.predict(image)
        except Exception as exc:
            logger.debug("[AutoOCR] Engine '%s' inference error: %s", code, exc)
            return []

        regions: list[dict] = []
        for item in (result or []):
            texts  = list(item.get("rec_texts",  []) or [])
            scores = list(item.get("rec_scores", []) or [])

            # Try all known key names for bounding polygons
            raw_boxes: list = []
            for key in _BOX_KEYS:
                val = item.get(key)
                if val:
                    raw_boxes = list(val)
                    break

            # Pad shorter lists to match len(texts)
            while len(scores) < len(texts):
                scores.append(1.0)
            while len(raw_boxes) < len(texts):
                raw_boxes.append(None)

            for text, score, box in zip(texts, scores, raw_boxes):
                text  = (text or "").strip()
                score = float(score)
                if not text:
                    continue
                if score < self.min_confidence:
                    continue
                rect = self._box_to_rect(box)
                regions.append({
                    "text":   text,
                    "score":  score,
                    "rect":   rect,
                    "engine": code,
                })

        return regions

    # ──────────────────────────────────────────────────────────────────────
    # Internal — per-region merge
    # ──────────────────────────────────────────────────────────────────────

    def _merge_by_region(
        self, engine_regions: dict[str, list[dict]]
    ) -> list[dict]:
        """
        For each detected text region, keep the result from whichever engine
        produced the highest recognition confidence score.

        Matching uses axis-aligned bounding-box IoU ≥ IOU_THRESHOLD (0.30).

        Fallback (no bounding-box info): selects the single engine whose
        regions have the highest sum of confidence scores — which is more
        accurate than mean_confidence × word_count because it does not
        reward the English engine for producing many low-confidence garbage
        tokens on non-Latin scripts.
        """
        # Flatten all regions into one list, keeping engine tag
        all_regions: list[dict] = []
        for code, regions in engine_regions.items():
            for r in regions:
                all_regions.append({**r, "engine": code})

        if not all_regions:
            return []

        # Check whether any bounding-box data is available
        has_boxes = any(r.get("rect") is not None for r in all_regions)

        if not has_boxes:
            # Fallback: pick the single best engine by confidence sum
            logger.debug(
                "[AutoOCR] No bounding-box info — using confidence-sum fallback."
            )
            best_code = max(
                engine_regions,
                key=lambda c: sum(r["score"] for r in engine_regions[c]),
            )
            return list(engine_regions[best_code])

        # ── Per-region IoU merge ──────────────────────────────────────────
        merged:       list[dict] = []
        used_indices: set[int]   = set()

        for i, r1 in enumerate(all_regions):
            if i in used_indices:
                continue

            if r1.get("rect") is None:
                # No position info — include as-is (cannot be matched)
                merged.append(r1)
                used_indices.add(i)
                continue

            # Collect all regions from OTHER engines that overlap this box
            group: list[dict] = [r1]
            used_indices.add(i)

            for j, r2 in enumerate(all_regions):
                if j in used_indices:
                    continue
                if r2["engine"] == r1["engine"]:
                    continue
                if r2.get("rect") is None:
                    continue
                if self._rect_iou(r1["rect"], r2["rect"]) >= IOU_THRESHOLD:
                    group.append(r2)
                    used_indices.add(j)

            # Winner = highest per-region confidence in the group
            best = max(group, key=lambda r: r["score"])
            merged.append(best)

        return merged

    # ──────────────────────────────────────────────────────────────────────
    # Internal — reading order
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _sort_reading_order(regions: list[dict]) -> list[dict]:
        """
        Sort text regions in standard reading order: top-to-bottom,
        left-to-right, with line-band grouping so that words on the same
        line stay together even when their detected y-coordinates differ
        slightly.
        """
        if not regions:
            return regions

        # Compute centroid for every region that has a bounding rect
        annotated: list[dict] = []
        for r in regions:
            rc = dict(r)
            rect = r.get("rect")
            if rect:
                x1, y1, x2, y2 = rect
                rc["_cx"] = (x1 + x2) / 2.0
                rc["_cy"] = (y1 + y2) / 2.0
                rc["_h"]  = max(y2 - y1, 1.0)
            else:
                rc["_cx"] = 0.0
                rc["_cy"] = 0.0
                rc["_h"]  = 20.0
            annotated.append(rc)

        if not any(r.get("rect") for r in annotated):
            # No positional info at all — return as-is
            return regions

        # Line-band height: 60% of average region height, at least 10 px
        avg_h = sum(r["_h"] for r in annotated) / len(annotated)
        band  = max(avg_h * 0.6, 10.0)

        # Sort by y-centroid first
        annotated.sort(key=lambda r: r["_cy"])

        # Group into lines
        lines: list[list[dict]] = []
        for r in annotated:
            placed = False
            for line in lines:
                ref_cy = sum(lr["_cy"] for lr in line) / len(line)
                if abs(r["_cy"] - ref_cy) <= band:
                    line.append(r)
                    placed = True
                    break
            if not placed:
                lines.append([r])

        # Within each line sort left-to-right, then flatten
        result: list[dict] = []
        for line in lines:
            line.sort(key=lambda r: r["_cx"])
            result.extend(line)

        # Strip private sorting keys before returning
        clean: list[dict] = []
        for r in result:
            c = {k: v for k, v in r.items() if not k.startswith("_")}
            clean.append(c)
        return clean

    # ──────────────────────────────────────────────────────────────────────
    # Internal — geometry helpers
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _box_to_rect(box) -> tuple[float, float, float, float] | None:
        """
        Convert a PaddleOCR polygon/box to an axis-aligned bounding rect
        (x1, y1, x2, y2).

        Handles:
            - list of [x, y] points: [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
            - flat array:  [x1, y1, x2, y2, ...]
            - None / invalid → returns None
        """
        if box is None:
            return None
        try:
            pts = np.asarray(box, dtype=float)
            if pts.ndim == 1:
                pts = pts.reshape(-1, 2)   # flat [x1,y1,x2,y2,...] → points
            if pts.shape[0] < 2 or pts.shape[1] < 2:
                return None
            x1 = float(pts[:, 0].min())
            y1 = float(pts[:, 1].min())
            x2 = float(pts[:, 0].max())
            y2 = float(pts[:, 1].max())
            if x2 <= x1 or y2 <= y1:
                return None
            return (x1, y1, x2, y2)
        except Exception:
            return None

    @staticmethod
    def _rect_iou(
        a: tuple[float, float, float, float],
        b: tuple[float, float, float, float],
    ) -> float:
        """
        Intersection-over-Union of two axis-aligned rectangles.

        Each rect is (x1, y1, x2, y2).  Returns 0.0 when no overlap.
        """
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        ix1 = max(ax1, bx1)
        iy1 = max(ay1, by1)
        ix2 = min(ax2, bx2)
        iy2 = min(ay2, by2)
        if ix2 <= ix1 or iy2 <= iy1:
            return 0.0
        inter  = (ix2 - ix1) * (iy2 - iy1)
        area_a = max((ax2 - ax1) * (ay2 - ay1), 1e-9)
        area_b = max((bx2 - bx1) * (by2 - by1), 1e-9)
        union  = area_a + area_b - inter
        return inter / union if union > 1e-9 else 0.0

    # ──────────────────────────────────────────────────────────────────────
    # Legacy helper (kept for unit-test compat — not used by recognize())
    # ──────────────────────────────────────────────────────────────────────

    def _run_engine(
        self, code: str, image: np.ndarray
    ) -> list[tuple[str, float]]:
        """
        Legacy: run one engine, return (text, score) pairs.
        Not used by recognize() — retained for backward compatibility.
        """
        regions = self._run_engine_with_boxes(code, image)
        return [(r["text"], r["score"]) for r in regions]
