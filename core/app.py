"""
core/app.py
===========
Application lifecycle manager for Smart Text Extractor.

Full pipeline (Phase 6 + Phase 7):
    Ctrl+Alt+X  (or toolbar / tray — works even when window is hidden)
    -> SelectionOverlay  (hides itself, emits region_selected after 80 ms)
    -> CaptureService.capture()             [main thread — screen is clear]
    -> _OCRWorker (QThread)                 [background — blocking inference]
    -> AutoOCRService.recognize()           [auto multilingual, 10 languages]
    -> MainWindow.set_text()                [main thread]
    -> ClipboardService.copy()              [main thread, if auto_clipboard]
    -> HistoryManager.add()                 [main thread]
    -> [if auto_translate] _TranslationWorker (QThread) [background]
    -> ResultOverlay.show()                 [main thread, if show_overlay on]
    -> ResultOverlay.start_autohide()       [main thread, if configured]

Background workers:
    _AutoOCRLoaderWorker  — loads 7 language engines at startup
    _OCRWorker            — one OCR inference per capture
    _TranslationWorker    — one translation per translate request

Overlay lifecycle:
    SelectionOverlay hides itself before emitting region_selected.
    ResultOverlay is a single persistent widget; its content is replaced
    on every new OCR result.  It is never destroyed, only hidden.

Thread safety:
    All pyqtSignals are queued connections — no manual locking needed.
    Workers are cancelled cleanly before new ones start.
"""

from __future__ import annotations

import logging
import traceback

from PyQt6.QtCore import Qt, QObject, QThread, pyqtSignal
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox

from core.history import HistoryManager
from core.settings import Settings
from services.auto_ocr_service import AutoOCRService
from services.capture_service import CaptureService
from services.clipboard_service import ClipboardService
from services.export_service import ExportService
from services.shortcut_service import ShortcutService
from services.translation_service import (
    TranslationService,
    get_language_code,
    SUPPORTED_LANGUAGES,
    DEFAULT_TARGET_LANG,
)
from ui.main_window import MainWindow
from ui.result_overlay import ResultOverlay
from ui.selection_overlay import SelectionOverlay
from ui.tray import TrayIcon

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Background Workers
# ─────────────────────────────────────────────────────────────────────────────

class _AutoOCRLoaderWorker(QThread):
    """
    Loads all AutoOCRService language engines in a background thread.

    Signals:
        engine_ready(lang_code, loaded, total)
        engine_failed(lang_code, error, loaded, total)
        load_complete(service)
        load_error(message)
    """

    engine_ready  = pyqtSignal(str, int, int)
    engine_failed = pyqtSignal(str, str, int, int)
    load_complete = pyqtSignal(object)
    load_error    = pyqtSignal(str)

    def __init__(self, min_confidence: float = 0.5, parent: QObject = None) -> None:
        super().__init__(parent)
        self._min_confidence = min_confidence

    def run(self) -> None:
        try:
            service = AutoOCRService(min_confidence=self._min_confidence)

            def _on_progress(loaded: int, total: int, code: str, error: str | None):
                if error is None:
                    self.engine_ready.emit(code, loaded, total)
                else:
                    self.engine_failed.emit(code, error, loaded, total)

            service.load_all(on_progress=_on_progress)

            if not service.is_loaded:
                self.load_error.emit(
                    "No OCR language engines could be loaded.  "
                    "Check that PaddleOCR is installed correctly."
                )
            else:
                self.load_complete.emit(service)

        except Exception:
            tb = traceback.format_exc()
            logger.error(
                "[App] _AutoOCRLoaderWorker.run() crashed with unhandled exception:\n%s",
                tb,
            )
            print(f"[App] LOADER THREAD CRASH:\n{tb}", flush=True)
            self.load_error.emit(
                f"OCR loader thread crashed unexpectedly.\n\n"
                f"See log for full traceback:\n{tb[:500]}"
            )


class _OCRWorker(QThread):
    """
    Runs a single AutoOCR inference in a background thread.
    Emits result_ready(text, duration_seconds) or error_occurred(message).
    """

    result_ready   = pyqtSignal(str, float)
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        ocr_service: AutoOCRService,
        image,
        parent: QObject = None,
    ) -> None:
        super().__init__(parent)
        self._svc   = ocr_service
        self._image = image

    def run(self) -> None:
        try:
            text     = self._svc.recognize(self._image)
            duration = self._svc.last_duration
            self.result_ready.emit(text, duration)
        except Exception as exc:
            self.error_occurred.emit(str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# Application
# ─────────────────────────────────────────────────────────────────────────────

class Application:
    """
    Manages the full lifecycle of Smart Text Extractor.

    Phase 6 additions:
        - Tray menu with History, Toggle Auto Translate, Settings, Exit.
        - Hotkey fires even when main window is hidden.
        - set_auto_translate() public method for tray ↔ settings sync.

    Phase 7 additions:
        - ResultOverlay shown after OCR (and translation if enabled).
        - Smart positioning near the captured region.
        - Auto-hide timer based on settings.
        - Overlay copy/open-window actions wired to clipboard and main window.
    """

    def __init__(self, argv: list[str]) -> None:
        # ── Qt application ────────────────────────────────────────────────
        self.qt_app = QApplication(argv)
        self.qt_app.setApplicationName("Smart Text Extractor")
        self.qt_app.setApplicationVersion("2.0.0")
        self.qt_app.setOrganizationName("TextEx")
        self.qt_app.setQuitOnLastWindowClosed(False)

        # ── Settings & History ────────────────────────────────────────────
        self._settings = Settings.instance()
        self._history  = HistoryManager(limit=self._settings.history_limit)

        # ── Main window ───────────────────────────────────────────────────
        self.main_window = MainWindow()

        # ── Services ──────────────────────────────────────────────────────
        self.shortcut_service    = ShortcutService(hotkey=self._settings.hotkey)
        self.capture_service     = CaptureService()
        self.ocr_service: AutoOCRService | None = None
        self.translation_service = TranslationService()

        # ── Tray ──────────────────────────────────────────────────────────
        self._tray = TrayIcon(self)

        # ── Workers ───────────────────────────────────────────────────────
        self._load_worker:        _AutoOCRLoaderWorker | None = None
        self._ocr_worker:         _OCRWorker           | None = None
        self._translation_worker                        = None

        # ── Overlays ──────────────────────────────────────────────────────
        self._overlay: SelectionOverlay | None = None
        # ResultOverlay is persistent — created once, reused
        self._result_overlay: ResultOverlay | None = None

        # Track last capture region for smart overlay positioning
        self._last_capture_region: tuple[int, int, int, int] = (0, 0, 400, 300)
        # Cache OCR text for overlay copy button
        self._last_ocr_text: str = ""

        self._connect_signals()
        self._setup_translation_ui()

    # ──────────────────────────────────────────────────────────────────────
    # Entry Point
    # ──────────────────────────────────────────────────────────────────────

    def run(self) -> int:
        if self._settings.always_on_top:
            self.main_window.set_always_on_top(True)

        self._install_close_handler()
        self._tray.show()

        if self._settings.start_minimized:
            self._tray.notify(
                "Smart Text Extractor",
                "Running in the system tray. Click to open.",
            )
        else:
            self.main_window.show()

        self.main_window.set_language_label("Auto — loading…")
        self.shortcut_service.start()

        self.main_window.set_status("Loading multilingual OCR engines…")
        self._load_worker = _AutoOCRLoaderWorker(
            min_confidence=self._settings.confidence_threshold,
        )
        self._load_worker.engine_ready.connect(self._on_engine_ready)
        self._load_worker.engine_failed.connect(self._on_engine_failed)
        self._load_worker.load_complete.connect(self._on_ocr_model_loaded)
        self._load_worker.load_error.connect(self._on_ocr_model_error)
        self._load_worker.finished.connect(self._on_load_worker_done)
        self._load_worker.start()

        # Sync tray checkmark with persisted setting
        self._tray.sync_auto_translate(self._settings.auto_translate)

        return self.qt_app.exec()

    # ──────────────────────────────────────────────────────────────────────
    # Signal Wiring
    # ──────────────────────────────────────────────────────────────────────

    def _connect_signals(self) -> None:
        # OCR
        self.shortcut_service.hotkey_triggered.connect(self._show_selection_overlay)
        self.main_window.capture_requested.connect(self._show_selection_overlay)
        self.main_window.copy_requested.connect(self._on_copy_requested)
        self.main_window.history_requested.connect(self.show_history)
        self.main_window.settings_requested.connect(self.show_settings)
        self.main_window.gallery_requested.connect(self.show_gallery)
        self.main_window.save_txt_requested.connect(self._on_save_txt)
        self.main_window.export_requested.connect(self._on_export)
        self.qt_app.aboutToQuit.connect(self._cleanup)

        # Translation
        self.main_window.translate_requested.connect(self._on_translate_requested)
        self.main_window.copy_translation_requested.connect(self._on_copy_translation)
        self.main_window.save_translation_requested.connect(self._on_save_translation)

    def _setup_translation_ui(self) -> None:
        langs   = list(SUPPORTED_LANGUAGES.keys())
        current = self._settings.translation_target_lang or DEFAULT_TARGET_LANG
        self.main_window.set_translation_languages(langs, current)
        self.main_window.set_auto_translate(self._settings.auto_translate)

        chk = self.main_window.get_auto_translate_checkbox()
        chk.stateChanged.connect(self._on_auto_translate_toggled)

        combo = self.main_window.get_language_combo()
        combo.currentTextChanged.connect(self._on_target_lang_changed)

    def _install_close_handler(self) -> None:
        app_ref = self

        def _close_event(event):
            if app_ref._settings.minimize_to_tray:
                event.ignore()
                app_ref.main_window.hide()
                app_ref._tray.notify(
                    "Smart Text Extractor",
                    "Minimized to tray. Double-click to restore.",
                    duration_ms=2000,
                )
            else:
                event.accept()
                app_ref.qt_app.quit()

        self.main_window.closeEvent = _close_event

    # ──────────────────────────────────────────────────────────────────────
    # OCR Engine Loading
    # ──────────────────────────────────────────────────────────────────────

    def _on_load_worker_done(self) -> None:
        self._load_worker = None

    def _on_engine_ready(self, code: str, loaded: int, total: int) -> None:
        self.main_window.set_status(f"Loading OCR engines… ({loaded}/{total} ready)")

    def _on_engine_failed(self, code: str, error: str, loaded: int, total: int) -> None:
        logger.warning("[App] Engine '%s' failed: %s", code, error)
        self.main_window.set_status(
            f"Loading OCR engines… ({loaded}/{total} ready, '{code}' unavailable)"
        )

    def _on_ocr_model_loaded(self, service: AutoOCRService) -> None:
        try:
            self.ocr_service = service
            self.ocr_service.min_confidence = self._settings.confidence_threshold
            label = service.language_label
            self.main_window.set_language_label(label)
            n_ok  = service.engines_loaded
            n_bad = service.engines_failed
            status = (
                f"Ready  •  {label}"
                f"  •  Press {self._settings.hotkey.upper()} to capture"
            )
            if n_bad:
                status += f"  ({n_bad} engine(s) unavailable)"
            self.main_window.set_status(status)
            logger.info("[App] AutoOCR ready: %d engines loaded, %d failed.", n_ok, n_bad)
        except Exception as exc:
            logger.exception("[App] Error in _on_ocr_model_loaded: %s", exc)
            self.main_window.set_status(f"OCR ready (UI update error: {exc})")

    def _on_ocr_model_error(self, message: str) -> None:
        self.main_window.set_status(f"OCR load error: {message}")
        logger.error("[App] All OCR engines failed: %s", message)
        QMessageBox.critical(
            self.main_window, "OCR Engine Error",
            f"No OCR language engines could be loaded:\n\n{message}\n\n"
            "Ensure PaddleOCR is installed in your virtual environment.",
        )

    # ──────────────────────────────────────────────────────────────────────
    # Selection Overlay
    # ──────────────────────────────────────────────────────────────────────

    def _show_selection_overlay(self) -> None:
        """
        Display the fullscreen selection overlay.
        Works whether the main window is visible or hidden.
        """
        if self.ocr_service is None or not self.ocr_service.is_loaded:
            self.main_window.set_status("OCR engines are still loading — please wait…")
            return

        if self._overlay is not None:
            try:
                self._overlay.hide()
                self._overlay.deleteLater()
            except RuntimeError:
                pass
            self._overlay = None

        # Hide any existing result overlay so it doesn't obstruct selection
        if self._result_overlay is not None:
            self._result_overlay.hide()

        self._overlay = SelectionOverlay()
        self._overlay.region_selected.connect(self._on_region_selected)
        self._overlay.show()
        self._overlay.activateWindow()

    # ──────────────────────────────────────────────────────────────────────
    # Capture → OCR Pipeline
    # ──────────────────────────────────────────────────────────────────────

    def _on_region_selected(self, x: int, y: int, width: int, height: int) -> None:
        self._overlay = None
        # Remember region for smart overlay positioning
        self._last_capture_region = (x, y, width, height)

        self.main_window.set_status("Capturing screen region…")

        try:
            image, _saved = self.capture_service.capture(
                x, y, width, height,
                save_named=self._settings.keep_screenshots,
            )
        except (ValueError, RuntimeError) as exc:
            msg = str(exc)
            self.main_window.set_status(f"Capture error: {msg}")
            logger.error("[App] Capture failed: %s", msg)
            QMessageBox.warning(
                self.main_window, "Capture Failed",
                f"Could not capture the selected region:\n{msg}",
            )
            return

        self.main_window.set_status("Running multilingual OCR…")

        if self._ocr_worker is not None:
            if self._ocr_worker.isRunning():
                self._ocr_worker.requestInterruption()
                self._ocr_worker.quit()
                if not self._ocr_worker.wait(3000):
                    logger.warning("[App] OCR worker did not finish in time; terminating.")
                    self._ocr_worker.terminate()
                    self._ocr_worker.wait(1000)
            try:
                self._ocr_worker.result_ready.disconnect()
                self._ocr_worker.error_occurred.disconnect()
            except RuntimeError:
                pass
            self._ocr_worker = None

        self._ocr_worker = _OCRWorker(self.ocr_service, image)
        self._ocr_worker.result_ready.connect(self._on_ocr_result)
        self._ocr_worker.error_occurred.connect(self._on_ocr_error)
        self._ocr_worker.start()

        # Phase 6.5 — show overlay immediately with loading placeholder
        if self._settings.show_result_overlay:
            self._show_loading_overlay()

    def _on_ocr_result(self, text: str, duration: float) -> None:
        if not text.strip():
            self.main_window.set_status("No text detected in the selected region")
            return

        self._last_ocr_text = text
        self.main_window.set_text(text)
        self.main_window.set_translation_text("")
        self.main_window.set_translation_status("")
        self.main_window.set_detected_lang("")

        lines = len(text.splitlines())
        words = len(text.split())
        chars = len(text)
        self.main_window.set_stats(chars, words, lines, duration)
        self.main_window.set_status(
            f"Extracted {words} word(s) across {lines} line(s) in {duration:.2f}s",
            timeout_ms=6000,
        )

        if self._settings.auto_clipboard:
            ClipboardService.copy(text)
            self._tray.notify(
                "Text Extracted",
                f"{words} word(s) copied to clipboard.",
                duration_ms=2500,
            )

        self._history.add(text, language="auto", duration=duration)
        logger.info("[App] OCR done: %d words, %.2fs.", words, duration)

        # Auto-translate or update overlay with real OCR text
        if self._settings.auto_translate:
            lang_name = self._settings.translation_target_lang or DEFAULT_TARGET_LANG
            lang_code = get_language_code(lang_name)
            # Phase 6.5: if overlay already visible from loading state, update it
            # with OCR text now; translation result will update it again when done
            if self._settings.show_result_overlay and self._result_overlay is not None:
                self._update_loading_overlay(ocr_text=text, translation_text="")
            self._start_translation(text, lang_code, show_overlay_after=True)
        else:
            # No translation — show overlay with OCR result
            if self._settings.show_result_overlay:
                self._show_result_overlay(ocr_text=text, translation_text="")

    def _on_ocr_error(self, message: str) -> None:
        self.main_window.set_status(f"OCR error: {message}")
        logger.error("[App] OCR error: %s", message)
        # Phase 6.5: update loading overlay to show error instead of leaving
        # it frozen on "Recognizing text…"
        if self._settings.show_result_overlay and self._result_overlay is not None:
            self._update_loading_overlay(
                ocr_text=f"[OCR Error]\n\n{message}",
                translation_text="",
            )
        QMessageBox.warning(
            self.main_window, "OCR Failed",
            f"Text extraction failed:\n\n{message}\n\n"
            "Try selecting a clearer region with higher contrast.",
        )

    # ──────────────────────────────────────────────────────────────────────
    # Translation Pipeline
    # ──────────────────────────────────────────────────────────────────────

    def _on_translate_requested(self, text: str, lang_code: str) -> None:
        """Manual translate button."""
        self._start_translation(text, lang_code, show_overlay_after=False)

    def _start_translation(
        self,
        text: str,
        lang_code: str,
        show_overlay_after: bool = False,
    ) -> None:
        """Cancel any running translation, then start a fresh worker."""
        if self._translation_worker is not None:
            try:
                if self._translation_worker.isRunning():
                    self._translation_worker.requestInterruption()
                    self._translation_worker.quit()
                    self._translation_worker.wait(2000)
                self._translation_worker.result_ready.disconnect()
                self._translation_worker.error_occurred.disconnect()
            except RuntimeError:
                pass
            self._translation_worker = None

        self.main_window.set_translation_status("⟳  Translating…")
        self.main_window.set_translate_button_enabled(False)
        self.main_window.set_translation_text("")

        worker = self.translation_service.create_worker(text, lang_code)
        # Capture show_overlay_after in closure
        _show_after = show_overlay_after
        _ocr_text   = text

        def _on_result(translated: str, detected: str) -> None:
            self._on_translation_result(translated, detected)
            if _show_after and self._settings.show_result_overlay:
                self._show_result_overlay(
                    ocr_text=_ocr_text, translation_text=translated
                )

        def _on_error(message: str) -> None:
            self._on_translation_error(message)
            if _show_after and self._settings.show_result_overlay:
                self._show_result_overlay(
                    ocr_text=_ocr_text, translation_text=""
                )

        worker.result_ready.connect(_on_result)
        worker.error_occurred.connect(_on_error)
        worker.finished.connect(self._on_translation_worker_done)
        self._translation_worker = worker
        self._translation_worker.start()
        logger.info("[App] Translation started → lang_code=%s", lang_code)

    def _on_translation_result(self, translated: str, detected: str) -> None:
        self.main_window.set_translation_text(translated)
        self.main_window.set_translation_status("✓  Done")
        self.main_window.set_detected_lang(detected)
        self.main_window.set_status("Translation complete", timeout_ms=4000)
        logger.info("[App] Translation done. detected=%r, chars=%d", detected, len(translated))

    def _on_translation_error(self, message: str) -> None:
        self.main_window.set_translation_status("⚠  Error")
        self.main_window.set_status("Translation failed — see translation panel", timeout_ms=5000)
        self.main_window.set_translation_text(
            f"[Translation Error]\n\n{message}\n\nOCR text above is unchanged."
        )
        logger.error("[App] Translation error: %s", message)

    def _on_translation_worker_done(self) -> None:
        self.main_window.set_translate_button_enabled(True)
        self._translation_worker = None

    # ──────────────────────────────────────────────────────────────────────
    # Result Overlay (Phase 7)
    # ──────────────────────────────────────────────────────────────────────

    def _get_result_overlay(self) -> ResultOverlay:
        """
        Return the single persistent ResultOverlay, creating it on first call.
        All signals are connected exactly once here — no duplicates (BUG 4).
        """
        if self._result_overlay is None:
            ov = ResultOverlay()
            ov.open_main_window_requested.connect(self._on_overlay_open_main)
            ov.copy_ocr_requested.connect(self._on_overlay_copy_ocr)
            ov.copy_translation_requested.connect(self._on_overlay_copy_translation)
            # BUG 2: wire translation controls inside overlay
            ov.translate_requested.connect(self._on_overlay_translate)
            ov.auto_translate_toggled.connect(self._on_overlay_auto_trans_toggled)
            # UX improvement: autohide combo inside overlay
            ov.autohide_changed.connect(self._on_overlay_autohide_changed)
            # Populate language list and sync auto-translate state
            lang_name = self._settings.translation_target_lang or DEFAULT_TARGET_LANG
            ov.set_languages(list(SUPPORTED_LANGUAGES.keys()), lang_name)
            ov.set_auto_translate(self._settings.auto_translate)
            ov.set_autohide_value(self._settings.overlay_autohide_secs)
            self._result_overlay = ov
        return self._result_overlay

    def _show_result_overlay(self, ocr_text: str, translation_text: str) -> None:
        """
        Populate and display the result overlay near the last capture region.
        Uses update_content() for atomic state replacement (BUG 4).

        Called when the full result (OCR + optional translation) is ready.
        Also called by _start_translation closures when auto-translate finishes.
        """
        overlay = self._get_result_overlay()
        # Sync language and auto-translate on every show
        lang_name = self._settings.translation_target_lang or DEFAULT_TARGET_LANG
        overlay.set_languages(list(SUPPORTED_LANGUAGES.keys()), lang_name)
        overlay.set_auto_translate(self._settings.auto_translate)
        overlay.set_translate_busy(False)
        # Sync autohide combo with persisted setting (without triggering the slot)
        overlay.set_autohide_value(self._settings.overlay_autohide_secs)

        # Atomic content update — no partial state
        overlay.update_content(ocr_text, translation_text)

        rx, ry, rw, rh = self._last_capture_region
        overlay.position_near_region(rx, ry, rw, rh)
        overlay.show()
        overlay.start_autohide(self._settings.overlay_autohide_secs)

        logger.debug(
            "[App] ResultOverlay shown near (%d,%d,%d,%d), autohide=%ds",
            rx, ry, rw, rh, self._settings.overlay_autohide_secs,
        )

    # ── Phase 6.5 — Instant Feedback helpers ─────────────────────────────

    def _show_loading_overlay(self) -> None:
        """
        Phase 6.5 — show the overlay immediately after capture, before OCR.

        The overlay appears near the captured region displaying a
        "Recognizing text…" placeholder.  The auto-hide countdown is NOT
        started here — it begins only once real OCR content arrives via
        _update_loading_overlay(), so the overlay never times out mid-recognition.
        """
        overlay = self._get_result_overlay()
        lang_name = self._settings.translation_target_lang or DEFAULT_TARGET_LANG
        overlay.set_languages(list(SUPPORTED_LANGUAGES.keys()), lang_name)
        overlay.set_auto_translate(self._settings.auto_translate)
        overlay.set_autohide_value(self._settings.overlay_autohide_secs)

        # Enter loading state — clears OCR text, shows spinner label
        overlay.show_loading_state()

        rx, ry, rw, rh = self._last_capture_region
        overlay.position_near_region(rx, ry, rw, rh)
        overlay.show()
        # Auto-hide countdown begins only when real OCR content arrives
        # (_update_loading_overlay calls the timer — never called here).
        logger.debug("[App] Loading overlay shown near (%d,%d,%d,%d)", rx, ry, rw, rh)

    def _update_loading_overlay(self, ocr_text: str, translation_text: str) -> None:
        """
        Phase 6.5 — update the loading overlay with real OCR content.

        Called from _on_ocr_result() once OCR finishes.  If the overlay is
        already visible (from _show_loading_overlay) its content is replaced
        atomically.  If for any reason it is not visible, falls back to the
        standard _show_result_overlay() path.

        Auto-hide is started here for the first time with real content.
        """
        overlay = self._get_result_overlay()
        if not overlay.isVisible():
            # Fallback: overlay was closed by user during recognition
            self._show_result_overlay(ocr_text, translation_text)
            return

        # Keep overlay in place — no repositioning, no flicker
        overlay.set_translate_busy(False)
        overlay.update_content(ocr_text, translation_text)
        # Now start the countdown — real content is visible
        overlay.start_autohide(self._settings.overlay_autohide_secs)
        logger.debug("[App] Loading overlay updated with OCR result (%d chars)", len(ocr_text))

    # ── Overlay action slots ─────────────────────────────────────────────

    def _on_overlay_open_main(self) -> None:
        """Bring main window to front — BUG 1 fix: proper PyQt6 enum usage."""
        win = self.main_window
        win.show()
        state = win.windowState()
        state &= ~Qt.WindowState.WindowMinimized
        win.setWindowState(state)
        win.raise_()
        win.activateWindow()

    def _on_overlay_copy_ocr(self) -> None:
        text = self._last_ocr_text
        if text:
            ClipboardService.copy(text)
            self.main_window.set_status("OCR text copied from overlay", timeout_ms=3000)

    def _on_overlay_copy_translation(self) -> None:
        if self._result_overlay is not None:
            text = self._result_overlay.get_translation_text()
            if text and not text.startswith("[Translation Error]"):
                ClipboardService.copy(text)
                self.main_window.set_status(
                    "Translation copied from overlay", timeout_ms=3000
                )

    def _on_overlay_translate(self, ocr_text: str, lang_code: str) -> None:
        """
        BUG 2: Translate button inside the overlay was clicked.
        Runs translation worker and feeds result back to the overlay.
        """
        # Cancel any running translation first
        if self._translation_worker is not None:
            try:
                if self._translation_worker.isRunning():
                    self._translation_worker.requestInterruption()
                    self._translation_worker.quit()
                    self._translation_worker.wait(2000)
                self._translation_worker.result_ready.disconnect()
                self._translation_worker.error_occurred.disconnect()
            except RuntimeError:
                pass
            self._translation_worker = None

        worker = self.translation_service.create_worker(ocr_text, lang_code)
        overlay = self._result_overlay   # local ref for closure safety

        def _on_result(translated: str, detected: str) -> None:
            if overlay is not None and not overlay.isHidden():
                overlay.set_translation_result(translated)
            # Also update main window
            self.main_window.set_translation_text(translated)
            self.main_window.set_detected_lang(detected)
            self.main_window.set_translation_status("✓  Done")
            self.main_window.set_translate_button_enabled(True)
            self._translation_worker = None

        def _on_error(message: str) -> None:
            if overlay is not None and not overlay.isHidden():
                overlay.set_translation_result(f"[Translation Error]\n{message}")
            self.main_window.set_translation_status("⚠  Error")
            self.main_window.set_translate_button_enabled(True)
            self._translation_worker = None

        worker.result_ready.connect(_on_result)
        worker.error_occurred.connect(_on_error)
        self._translation_worker = worker
        worker.start()
        logger.info("[App] Overlay translation started → lang_code=%s", lang_code)

    def _on_overlay_auto_trans_toggled(self, enabled: bool) -> None:
        """BUG 2: Auto Translate toggled from inside the overlay — keep everything in sync."""
        self.set_auto_translate(enabled)

    def _on_overlay_autohide_changed(self, seconds: int) -> None:
        """
        User changed the autohide combo directly inside the overlay.

        Actions:
          1. Persist the new value to Settings immediately.
          2. Call set_autohide_value() on the overlay (blockSignals) so the
             combo reflects the canonical stored value — guards against any
             rounding or mismatch.

        Note: start_autohide() is NOT called here because the overlay's own
        _on_autohide_combo_changed() already restarted the timer inline.
        """
        self._settings.overlay_autohide_secs = seconds
        self._settings.sync()
        # Confirm combo state without re-emitting the signal
        if self._result_overlay is not None:
            self._result_overlay.set_autohide_value(seconds)
        logger.info("[App] Overlay autohide persisted: %d s", seconds)


    # ──────────────────────────────────────────────────────────────────────
    # Toolbar / Menu Slots — OCR
    # ──────────────────────────────────────────────────────────────────────

    def _on_copy_requested(self) -> None:
        text = self.main_window.get_text()
        if text:
            ClipboardService.copy(text)
            self.main_window.set_status("OCR text copied to clipboard", timeout_ms=3000)
        else:
            self.main_window.set_status("Nothing to copy")

    def _on_save_txt(self) -> None:
        text = self.main_window.get_text()
        if not text:
            QMessageBox.information(self.main_window, "Save", "No OCR text to save.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self.main_window, "Save OCR Text As", "extracted.txt",
            "Text Files (*.txt);;All Files (*)",
        )
        if not path:
            return
        try:
            ExportService.to_txt(text, path)
            self.main_window.set_status(f"Saved OCR text: {path}", timeout_ms=5000)
        except RuntimeError as exc:
            QMessageBox.critical(self.main_window, "Save Failed", str(exc))

    def _on_export(self, fmt: str) -> None:
        records = self._history.get_all()
        if not records:
            QMessageBox.information(
                self.main_window, "Export",
                "No history entries to export.\nCapture some text first.",
            )
            return
        ext = fmt.upper()
        path, _ = QFileDialog.getSaveFileName(
            self.main_window, f"Export as {ext}", f"history.{fmt}",
            f"{ext} Files (*.{fmt});;All Files (*)",
        )
        if not path:
            return
        try:
            if fmt == "json":
                ExportService.to_json(records, path)
            else:
                ExportService.to_csv(records, path)
            self.main_window.set_status(
                f"Exported {len(records)} records to {path}", timeout_ms=5000
            )
        except RuntimeError as exc:
            QMessageBox.critical(self.main_window, "Export Failed", str(exc))

    # ──────────────────────────────────────────────────────────────────────
    # Toolbar / Menu Slots — Translation
    # ──────────────────────────────────────────────────────────────────────

    def _on_copy_translation(self) -> None:
        text = self.main_window.get_translation_text()
        if text and not text.startswith("[Translation Error]"):
            ClipboardService.copy(text)
            self.main_window.set_status("Translation copied to clipboard", timeout_ms=3000)
        else:
            self.main_window.set_status("No translation to copy")

    def _on_save_translation(self) -> None:
        text = self.main_window.get_translation_text()
        if not text or text.startswith("[Translation Error]"):
            QMessageBox.information(
                self.main_window, "Save", "No translation text to save."
            )
            return
        path, _ = QFileDialog.getSaveFileName(
            self.main_window, "Save Translation As", "translation.txt",
            "Text Files (*.txt);;All Files (*)",
        )
        if not path:
            return
        try:
            ExportService.to_txt(text, path)
            self.main_window.set_status(f"Saved translation: {path}", timeout_ms=5000)
        except RuntimeError as exc:
            QMessageBox.critical(self.main_window, "Save Failed", str(exc))

    # ──────────────────────────────────────────────────────────────────────
    # Public API — Tray ↔ Settings sync
    # ──────────────────────────────────────────────────────────────────────

    def set_auto_translate(self, enabled: bool) -> None:
        """
        Called by the tray toggle.  Persists the setting and syncs all UI.
        """
        self._settings.auto_translate = enabled
        self._settings.sync()
        self.main_window.set_auto_translate(enabled)
        self._tray.sync_auto_translate(enabled)
        logger.debug("[App] Auto Translate set to %s (from tray)", enabled)

    # ──────────────────────────────────────────────────────────────────────
    # Settings Change Handlers
    # ──────────────────────────────────────────────────────────────────────

    def _on_auto_translate_toggled(self, state: int) -> None:
        """Main window checkbox changed."""
        enabled = bool(state)
        self._settings.auto_translate = enabled
        self._settings.sync()
        self._tray.sync_auto_translate(enabled)
        logger.debug("[App] Auto Translate set to %s (from main window)", enabled)

    def _on_target_lang_changed(self, lang_name: str) -> None:
        self._settings.translation_target_lang = lang_name
        self._settings.sync()
        logger.debug("[App] Translation target language set to '%s'", lang_name)

    # ──────────────────────────────────────────────────────────────────────
    # Dialog Launchers
    # ──────────────────────────────────────────────────────────────────────

    def show_history(self) -> None:
        from ui.dialogs.history_dialog import HistoryDialog
        dlg = HistoryDialog(self._history, parent=self.main_window)
        dlg.exec()
        if dlg.selected_text:
            self.main_window.set_text(dlg.selected_text)
            self.main_window.set_status("History entry loaded into editor")

    def show_settings(self) -> None:
        from ui.dialogs.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self._settings, parent=self.main_window)
        dlg.hotkey_changed.connect(self._on_hotkey_changed)
        dlg.always_on_top_changed.connect(self.main_window.set_always_on_top)
        dlg.auto_translate_changed.connect(self._on_auto_translate_settings_changed)
        dlg.exec()
        self._history.limit = self._settings.history_limit
        if self.ocr_service:
            self.ocr_service.min_confidence = self._settings.confidence_threshold
        # Sync UI after settings dialog closes
        self.main_window.set_auto_translate(self._settings.auto_translate)
        self._tray.sync_auto_translate(self._settings.auto_translate)
        lang_name = self._settings.translation_target_lang or DEFAULT_TARGET_LANG
        self.main_window.set_translation_languages(
            list(SUPPORTED_LANGUAGES.keys()), lang_name
        )

    def show_gallery(self) -> None:
        from ui.dialogs.screenshot_gallery import ScreenshotGallery
        dlg = ScreenshotGallery(self.capture_service, parent=self.main_window)
        dlg.exec()

    # ──────────────────────────────────────────────────────────────────────
    # Settings Handlers
    # ──────────────────────────────────────────────────────────────────────

    def _on_hotkey_changed(self, new_hotkey: str) -> None:
        self.shortcut_service.change_hotkey(new_hotkey)
        self.main_window.set_status(
            f"Hotkey updated: {new_hotkey.upper()}", timeout_ms=4000
        )

    def _on_auto_translate_settings_changed(self, enabled: bool) -> None:
        self.main_window.set_auto_translate(enabled)
        self._tray.sync_auto_translate(enabled)

    # ──────────────────────────────────────────────────────────────────────
    # Teardown
    # ──────────────────────────────────────────────────────────────────────

    def _cleanup(self) -> None:
        logger.info("[App] Shutting down.")

        # Close result overlay
        if self._result_overlay is not None:
            try:
                self._result_overlay.close()
            except RuntimeError:
                pass
            self._result_overlay = None

        # Close selection overlay
        if self._overlay is not None:
            try:
                self._overlay.hide()
                self._overlay.deleteLater()
            except RuntimeError:
                pass
            self._overlay = None

        # Stop all workers
        workers = [self._load_worker, self._ocr_worker, self._translation_worker]
        for worker in workers:
            if worker is None:
                continue
            if worker.isRunning():
                worker.requestInterruption()
                worker.quit()
                if not worker.wait(3000):
                    logger.warning(
                        "[App] Worker %r did not stop in 3 s; forcing terminate.", worker
                    )
                    worker.terminate()
                    worker.wait(1000)

        self.shortcut_service.stop()
        self._history.close()
        logger.info("[App] Shutdown complete.")
