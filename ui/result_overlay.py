"""
ui/result_overlay.py
====================
Floating result overlay for Smart Text Extractor — Phase 7 (Bug-fixed).

Displays OCR and (optionally) translation results in a small, always-on-top
frameless window that appears near the captured region immediately after
processing completes.

BUG FIXES (this revision):
    BUG 2 — Added target language dropdown, Translate button, and Auto
             Translate toggle directly inside the overlay.
    BUG 3 — Auto-hide options expanded: Disabled/3/5/10/15/30 seconds.
    BUG 4 — `update_content()` replaces set_ocr_text/set_translation_text
             in one atomic call so a new capture always replaces stale
             content cleanly. Signal connections are made once (on creation)
             and never duplicated.

Layout:
    ┌───────────────────────────────────────────────────────────────────┐
    │  ● Smart Text Extractor                          [□] [✕] (drag)  │
    ├───────────────────────────────────────────────────────────────────┤
    │  📄 OCR RESULT                                                    │
    │  <ocr text, scrollable, selectable>                               │
    ├───────────────────────────────────────────────────────────────────┤
    │  🌐 TRANSLATION          [Lang ▾] [🌐 Translate] [⟲ Auto □]     │
    │  <translated text, scrollable, selectable>                        │
    ├───────────────────────────────────────────────────────────────────┤
    │  [⎘ Copy OCR] [⎘ Copy Trans.]    [⊞ Open Window]  [✕ Close]     │
    └───────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import logging
from typing import Callable

from PyQt6.QtCore import (
    Qt, QPoint, QTimer, pyqtSignal,
)
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QCursor
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Result Overlay
# ─────────────────────────────────────────────────────────────────────────────

class ResultOverlay(QWidget):
    """
    Lightweight floating result window shown after OCR (and optional translation).

    Signals:
        open_main_window_requested  — user clicked "Open Full Window".
        copy_ocr_requested          — user clicked "Copy OCR".
        copy_translation_requested  — user clicked "Copy Translation".
        translate_requested(text, lang_code) — user clicked Translate in overlay.
        auto_translate_toggled(bool) — user toggled Auto Translate in overlay.
        closed                      — overlay was closed (button or auto-hide).
    """

    open_main_window_requested  = pyqtSignal()
    copy_ocr_requested          = pyqtSignal()
    copy_translation_requested  = pyqtSignal()
    translate_requested         = pyqtSignal(str, str)   # (ocr_text, lang_code)
    auto_translate_toggled      = pyqtSignal(bool)
    autohide_changed            = pyqtSignal(int)         # seconds; 0 = disabled
    closed                      = pyqtSignal()

    PREFERRED_WIDTH  = 500
    MARGIN           = 12
    MIN_HEIGHT       = 320       # minimum overlay height (px)
    RESIZE_MARGIN    = 8         # px from edge that triggers resize cursor/drag

    # Session-level size memory: survives hide/show cycles within one launch.
    # Class variable so all instances (there is only one) share state.
    _session_size: tuple[int, int] | None = None

    # Available auto-hide options (label, seconds)  — BUG 3 fix
    AUTOHIDE_OPTIONS: list[tuple[str, int]] = [
        ("Disabled", 0),
        ("3 seconds",  3),
        ("5 seconds",  5),
        ("10 seconds", 10),
        ("15 seconds", 15),
        ("30 seconds", 30),
    ]

    def __init__(self, parent=None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        # BUG 4: do NOT set WA_DeleteOnClose — we reuse the same widget.
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        self._drag_pos:            QPoint | None              = None
        self._current_ocr_text:    str                        = ""
        self._autohide_secs:       int                        = 0
        self._paused_remaining:    int                        = 0
        # Resize state — track which edge is being dragged
        self._resize_edge:         str | None                 = None
        self._resize_start_global: QPoint | None              = None
        self._resize_start_geom:   tuple[int,int,int,int] | None = None

        # Set minimum so the window cannot be shrunk below initial dimensions
        self.setMinimumSize(self.PREFERRED_WIDTH, self.MIN_HEIGHT)
        # Auto-hide timer (0 = disabled)
        self._auto_hide_timer = QTimer(self)
        self._auto_hide_timer.setSingleShot(True)
        self._auto_hide_timer.timeout.connect(self.close_overlay)

        self._build_ui()
        self._apply_stylesheet()

    # ──────────────────────────────────────────────────────────────────────
    # UI Construction
    # ──────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_title_bar())
        self._ocr_section   = self._build_ocr_section()
        root.addWidget(self._ocr_section)
        self._trans_section = self._build_trans_section()
        self._trans_section.hide()
        root.addWidget(self._trans_section)
        root.addWidget(self._build_action_bar())

    # ── Title / drag bar ──────────────────────────────────────────────────

    def _build_title_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("OverlayTitleBar")
        bar.setFixedHeight(34)
        h = QHBoxLayout(bar)
        h.setContentsMargins(10, 0, 8, 0)
        h.setSpacing(6)

        dot = QLabel("\u25cf")
        dot.setObjectName("OverlayDot")
        h.addWidget(dot)

        title = QLabel("Smart Text Extractor")
        title.setObjectName("OverlayTitle")
        h.addWidget(title, 1)

        # ── Auto-hide combo (inline in title bar) ────────────────────
        hide_lbl = QLabel("Hide:")
        hide_lbl.setObjectName("OverlayHideLbl")
        h.addWidget(hide_lbl)

        self._autohide_combo = QComboBox()
        self._autohide_combo.setObjectName("OverlayAutohideCombo")
        self._autohide_combo.setFixedHeight(22)
        self._autohide_combo.setToolTip(
            "Auto-hide delay.  Changes take effect immediately "
            "and are saved to Settings."
        )
        for label, secs in self.AUTOHIDE_OPTIONS:
            self._autohide_combo.addItem(label, secs)
        # Default to 0 (Disabled) until set_autohide_value() is called
        self._autohide_combo.setCurrentIndex(0)
        self._autohide_combo.currentIndexChanged.connect(self._on_autohide_combo_changed)
        h.addWidget(self._autohide_combo)
        # ───────────────────────────────────────────────────

        open_btn = QPushButton("\u25a1")
        open_btn.setObjectName("OverlayTitleBtn")
        open_btn.setFixedSize(22, 22)
        open_btn.setToolTip("Open full window")
        open_btn.clicked.connect(self._on_open_main)
        h.addWidget(open_btn)

        close_btn = QPushButton("\u2715")
        close_btn.setObjectName("OverlayCloseBtn")
        close_btn.setFixedSize(22, 22)
        close_btn.setToolTip("Close overlay")
        close_btn.clicked.connect(self.close_overlay)
        h.addWidget(close_btn)

        return bar

    # ── OCR section ───────────────────────────────────────────────────────

    def _build_ocr_section(self) -> QWidget:
        container = QWidget()
        container.setObjectName("OverlaySection_ocr")
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # Header bar
        hbar = QWidget()
        hbar.setObjectName("OverlaySectionHeader")
        hbar.setFixedHeight(26)
        hh = QHBoxLayout(hbar)
        hh.setContentsMargins(10, 0, 10, 0)
        hh.addWidget(QLabel("📄  OCR RESULT", objectName="OverlaySectionTitle"))
        hh.addStretch()
        v.addWidget(hbar)

        # Scrollable label
        scroll = QScrollArea()
        scroll.setObjectName("OverlayScroll_ocr")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setMinimumHeight(80)    # can expand; no hard cap
        scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        self._ocr_label = QLabel()
        self._ocr_label.setObjectName("OverlayText_ocr")
        self._ocr_label.setWordWrap(True)
        self._ocr_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._ocr_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._ocr_label.setMargin(10)
        scroll.setWidget(self._ocr_label)
        v.addWidget(scroll)

        return container

    # ── Translation section (BUG 2: includes controls) ───────────────────

    def _build_trans_section(self) -> QWidget:
        container = QWidget()
        container.setObjectName("OverlaySection_trans")
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # Header bar with controls (BUG 2)
        hbar = QWidget()
        hbar.setObjectName("OverlaySectionHeader")
        hbar.setFixedHeight(34)
        hh = QHBoxLayout(hbar)
        hh.setContentsMargins(10, 0, 8, 0)
        hh.setSpacing(6)

        hh.addWidget(QLabel("🌐  TRANSLATION", objectName="OverlaySectionTitle"))
        hh.addStretch()

        # Language selector
        self._lang_combo = QComboBox()
        self._lang_combo.setObjectName("OverlayLangCombo")
        self._lang_combo.setFixedHeight(24)
        self._lang_combo.setToolTip("Select target language")
        hh.addWidget(self._lang_combo)

        # Translate button
        self._trans_btn = QPushButton("🌐 Translate")
        self._trans_btn.setObjectName("OverlayTransBtn")
        self._trans_btn.setFixedHeight(24)
        self._trans_btn.setToolTip("Translate OCR text")
        self._trans_btn.clicked.connect(self._on_translate_clicked)
        hh.addWidget(self._trans_btn)

        # Auto Translate toggle
        self._auto_trans_chk = QCheckBox("Auto")
        self._auto_trans_chk.setObjectName("OverlayAutoChk")
        self._auto_trans_chk.setToolTip("Auto Translate after every OCR capture")
        self._auto_trans_chk.stateChanged.connect(self._on_auto_trans_changed)
        hh.addWidget(self._auto_trans_chk)

        v.addWidget(hbar)

        # Scrollable translation label
        scroll = QScrollArea()
        scroll.setObjectName("OverlayScroll_trans")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setMinimumHeight(60)    # can expand; no hard cap
        scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        self._trans_label = QLabel()
        self._trans_label.setObjectName("OverlayText_trans")
        self._trans_label.setWordWrap(True)
        self._trans_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._trans_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._trans_label.setMargin(10)
        scroll.setWidget(self._trans_label)
        v.addWidget(scroll)

        return container

    # ── Action bar ────────────────────────────────────────────────────────

    def _build_action_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("OverlayActionBar")
        bar.setFixedHeight(44)
        h = QHBoxLayout(bar)
        h.setContentsMargins(8, 6, 8, 6)
        h.setSpacing(6)

        self._copy_ocr_btn = QPushButton("⎘ Copy OCR")
        self._copy_ocr_btn.setObjectName("OverlayActionBtn")
        self._copy_ocr_btn.clicked.connect(self._on_copy_ocr)
        h.addWidget(self._copy_ocr_btn)

        self._copy_trans_btn = QPushButton("⎘ Copy Trans.")
        self._copy_trans_btn.setObjectName("OverlayActionBtn")
        self._copy_trans_btn.clicked.connect(self._on_copy_translation)
        self._copy_trans_btn.setVisible(False)
        h.addWidget(self._copy_trans_btn)

        h.addStretch()

        open_btn = QPushButton("\u229e Open Window")
        open_btn.setObjectName("OverlayActionBtnSecondary")
        open_btn.clicked.connect(self._on_open_main)
        h.addWidget(open_btn)

        close_btn = QPushButton("\u2715 Close")
        close_btn.setObjectName("OverlayActionBtnClose")
        close_btn.clicked.connect(self.close_overlay)
        h.addWidget(close_btn)

        # QSizeGrip in corner — enables native corner resize drag
        grip = QSizeGrip(self)
        grip.setObjectName("OverlaySizeGrip")
        grip.setFixedSize(16, 16)
        h.addWidget(grip, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)

        return bar

    # ──────────────────────────────────────────────────────────────────────
    # Stylesheet
    # ──────────────────────────────────────────────────────────────────────

    def _apply_stylesheet(self) -> None:
        self.setStyleSheet("""
            ResultOverlay {
                background: #1e1e2e;
                border: 1px solid #45475a;
                border-radius: 10px;
            }

            QWidget#OverlayTitleBar, QWidget#OverlaySectionHeader {
                background: #181825;
            }
            QWidget#OverlayTitleBar {
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
                border-bottom: 1px solid #313244;
            }
            QWidget#OverlaySectionHeader {
                border-bottom: 1px solid #313244;
            }

            QLabel#OverlayDot   { color: #2979ff; font-size: 10px; }
            QLabel#OverlayTitle { color: #89b4fa; font-size: 11px; font-weight: bold; }
            QLabel#OverlaySectionTitle {
                color: #89b4fa;
                font-size: 10px;
                font-weight: bold;
                letter-spacing: 1px;
            }

            QPushButton#OverlayTitleBtn {
                background: transparent; color: #6c7086; border: none; font-size: 12px;
            }
            QPushButton#OverlayTitleBtn:hover { color: #89b4fa; }
            QPushButton#OverlayCloseBtn {
                background: transparent; color: #6c7086; border: none; font-size: 11px;
            }
            QPushButton#OverlayCloseBtn:hover { color: #f38ba8; }

            /* Auto-hide inline combo in title bar */
            QLabel#OverlayHideLbl {
                color: #6c7086;
                font-size: 10px;
            }
            QComboBox#OverlayAutohideCombo {
                background: #252538;
                color: #a6adc8;
                border: 1px solid #45475a;
                border-radius: 3px;
                padding: 0px 4px;
                font-size: 10px;
                min-width: 68px;
            }
            QComboBox#OverlayAutohideCombo::drop-down {
                border: none;
                width: 14px;
            }
            QComboBox#OverlayAutohideCombo QAbstractItemView {
                background: #1e1e2e;
                color: #cdd6f4;
                border: 1px solid #45475a;
                selection-background-color: #313244;
                font-size: 11px;
            }

            /* Translation header controls */
            QComboBox#OverlayLangCombo {
                background: #313244;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 3px;
                padding: 1px 6px;
                font-size: 11px;
                min-width: 110px;
            }
            QComboBox#OverlayLangCombo QAbstractItemView {
                background: #1e1e2e;
                color: #cdd6f4;
                selection-background-color: #313244;
            }
            QPushButton#OverlayTransBtn {
                background: #1a3a6e;
                color: #89b4fa;
                border: 1px solid #2979ff;
                border-radius: 3px;
                padding: 1px 8px;
                font-size: 11px;
            }
            QPushButton#OverlayTransBtn:hover { background: #2979ff; color: white; }
            QPushButton#OverlayTransBtn:disabled { background: #313244; color: #6c7086; border-color: #45475a; }
            QCheckBox#OverlayAutoChk {
                color: #cdd6f4;
                font-size: 11px;
                spacing: 4px;
            }
            QCheckBox#OverlayAutoChk::indicator {
                width: 13px; height: 13px;
                background: #313244;
                border: 1px solid #45475a;
                border-radius: 2px;
            }
            QCheckBox#OverlayAutoChk::indicator:checked {
                background: #2979ff;
                border-color: #2979ff;
            }

            /* Text areas */
            QScrollArea { background: #1e1e2e; border: none; }
            QLabel#OverlayText_ocr {
                color: #cdd6f4;
                font-family: "Consolas", "Courier New", monospace;
                font-size: 13px;
                background: #1e1e2e;
            }
            QLabel#OverlayText_trans {
                color: #a6e3a1;
                font-family: "Consolas", "Courier New", monospace;
                font-size: 13px;
                background: #12121f;
            }

            /* Action bar */
            QWidget#OverlayActionBar {
                background: #181825;
                border-top: 1px solid #313244;
                border-bottom-left-radius: 10px;
                border-bottom-right-radius: 10px;
            }
            QPushButton#OverlayActionBtn {
                background: #313244;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 5px;
                padding: 3px 10px;
                font-size: 11px;
            }
            QPushButton#OverlayActionBtn:hover  { background: #45475a; }
            QPushButton#OverlayActionBtn:pressed { background: #585b70; }
            QPushButton#OverlayActionBtnSecondary {
                background: #1a3a6e;
                color: #89b4fa;
                border: 1px solid #2979ff;
                border-radius: 5px;
                padding: 3px 10px;
                font-size: 11px;
            }
            QPushButton#OverlayActionBtnSecondary:hover { background: #2979ff; color: white; }
            QPushButton#OverlayActionBtnClose {
                background: transparent;
                color: #6c7086;
                border: 1px solid #45475a;
                border-radius: 5px;
                padding: 3px 10px;
                font-size: 11px;
            }
            QPushButton#OverlayActionBtnClose:hover { color: #f38ba8; border-color: #f38ba8; }

            QScrollBar:vertical { background: #1e1e2e; width: 8px; border-radius: 4px; }
            QScrollBar::handle:vertical {
                background: #45475a; border-radius: 4px; min-height: 20px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

            /* Size grip — subtle dot-matrix on dark background */
            QSizeGrip#OverlaySizeGrip {
                background: transparent;
                image: none;
                width: 16px; height: 16px;
            }
        """)

    # ──────────────────────────────────────────────────────────────────────
    # Public API — content update (BUG 4: single atomic call)
    # ──────────────────────────────────────────────────────────────────────

    def update_content(
        self,
        ocr_text: str,
        translation_text: str = "",
    ) -> None:
        """
        Replace all content atomically.  Called on every new capture.
        Safe to call while the overlay is already visible.

        BUG 4 fix: replaces individual set_ocr_text / set_translation_text
        calls that could leave the overlay in a half-updated state.
        """
        self._current_ocr_text = ocr_text.strip()
        # Clear any inline style set by show_loading_state (italic/grey)
        self._ocr_label.setStyleSheet("")
        self._ocr_label.setText(self._current_ocr_text)
        # Re-enable buttons that were disabled during loading
        self._copy_ocr_btn.setEnabled(bool(self._current_ocr_text))
        self._trans_btn.setEnabled(True)
        self._set_translation(translation_text)

    def show_loading_state(self) -> None:
        """
        Phase 6.5 — Instant Feedback.

        Put the overlay into a loading/placeholder state immediately after
        the screen has been captured but before OCR has completed.

        Visual state:
            OCR RESULT:    "⟳  Recognizing text…"
            TRANSLATION:   hidden
            Copy OCR:      disabled
            Copy Trans.:   hidden
            Translate btn: disabled

        The overlay is shown but auto-hide is NOT started yet
        (app.py calls start_autohide only when real content arrives).
        """
        self._current_ocr_text = ""          # nothing real to copy yet
        self._ocr_label.setText("⟳  Recognizing text…")
        self._ocr_label.setStyleSheet("color: #6c7086; font-style: italic;")

        # Hide translation section while loading
        self._trans_label.setText("")
        self._trans_section.hide()
        self._copy_trans_btn.setVisible(False)
        self._copy_ocr_btn.setEnabled(False)
        self._trans_btn.setEnabled(False)

        # Stop any running auto-hide — don't time-out the loading state
        self._auto_hide_timer.stop()
        self._paused_remaining = 0


    def _set_translation(self, text: str) -> None:
        """Internal — update translation panel visibility + content."""
        clean = text.strip()
        has_translation = bool(clean) and not clean.startswith("[Translation Error]")
        if has_translation:
            self._trans_label.setText(clean)
            self._trans_section.show()
            self._copy_trans_btn.setVisible(True)
        else:
            if clean.startswith("[Translation Error]"):
                # Show the section with the error message but greyed
                self._trans_label.setText(clean)
                self._trans_section.show()
                self._copy_trans_btn.setVisible(False)
            else:
                # No translation — show the section so user can trigger it
                self._trans_label.setText("")
                self._trans_section.show()
                self._copy_trans_btn.setVisible(False)

    # Back-compat accessors used by app.py copy slots
    def get_ocr_text(self) -> str:
        return self._current_ocr_text

    def get_translation_text(self) -> str:
        return self._trans_label.text()

    # ── Translation controls (BUG 2) ──────────────────────────────────────

    def set_languages(self, languages: list[str], current: str = "") -> None:
        """Populate the language combo.  Called once after creation."""
        self._lang_combo.blockSignals(True)
        self._lang_combo.clear()
        for lang in languages:
            self._lang_combo.addItem(lang)
        if current and current in languages:
            self._lang_combo.setCurrentText(current)
        self._lang_combo.blockSignals(False)

    def set_auto_translate(self, enabled: bool) -> None:
        """Sync the Auto Translate checkbox without triggering its signal."""
        self._auto_trans_chk.blockSignals(True)
        self._auto_trans_chk.setChecked(enabled)
        self._auto_trans_chk.blockSignals(False)

    def set_translate_busy(self, busy: bool) -> None:
        """Disable/enable the Translate button while a request is in-flight."""
        self._trans_btn.setEnabled(not busy)
        self._trans_btn.setText("⟳ Translating…" if busy else "🌐 Translate")

    def set_translation_result(self, text: str) -> None:
        """Called when a translation completes (triggered from overlay button)."""
        self._set_translation(text)
        self.set_translate_busy(False)
        self._copy_trans_btn.setVisible(
            bool(text.strip()) and not text.startswith("[Translation Error]")
        )

    # ── Auto-hide ─────────────────────────────────────────────────────────

    def set_autohide_value(self, seconds: int) -> None:
        """
        Sync the autohide combo to ``seconds`` without triggering the slot.
        Called by app.py each time the overlay is shown (to keep combo in sync
        with the persisted setting) and after the Settings dialog is closed.
        """
        self._autohide_combo.blockSignals(True)
        matched = False
        for i in range(self._autohide_combo.count()):
            if self._autohide_combo.itemData(i) == seconds:
                self._autohide_combo.setCurrentIndex(i)
                matched = True
                break
        if not matched:
            # Closest value not in the list — pick index 0 (Disabled)
            self._autohide_combo.setCurrentIndex(0)
        self._autohide_combo.blockSignals(False)
        self._autohide_secs = seconds

    def start_autohide(self, seconds: int) -> None:
        """Start auto-hide countdown.  0 = disabled (never auto-hide).
        Does NOT change the combo selection — call set_autohide_value() for that.
        Resets _paused_remaining so a fresh countdown starts cleanly.
        """
        self._autohide_secs    = seconds
        self._paused_remaining = 0          # clear any stale pause from previous show
        self._auto_hide_timer.stop()
        if seconds > 0:
            self._auto_hide_timer.start(seconds * 1000)

    def stop_autohide(self) -> None:
        self._auto_hide_timer.stop()

    def _on_autohide_combo_changed(self, index: int) -> None:
        """
        User changed the autohide combo directly in the overlay.

        Behaviour:
          - Restart (or stop) the current timer immediately so the change is felt
            right now without waiting for the next capture.
          - Reset _paused_remaining so the new timeout is used as-is on next leave.
          - Emit autohide_changed(seconds) so app.py can persist to Settings.
        """
        secs = self._autohide_combo.itemData(index)
        if secs is None:
            return
        self._autohide_secs    = secs
        self._paused_remaining = 0          # new timeout — discard old paused state
        # Immediately apply to the running timer
        self._auto_hide_timer.stop()
        if secs > 0 and self.isVisible():
            self._auto_hide_timer.start(secs * 1000)
        # Notify app.py to persist + sync settings dialog
        self.autohide_changed.emit(secs)
        logger.debug("[Overlay] Autohide changed to %d s", secs)

    # ── Smart positioning ─────────────────────────────────────────────────

    def position_near_region(
        self, rx: int, ry: int, rw: int, rh: int,
    ) -> None:
        """
        Position the overlay near the captured region without covering it
        and without going off-screen.  Priority: below → above → right → left → centre.

        Phase 6.6: applies the session-saved size if the user resized the overlay
        during this launch, so subsequent captures reuse the last manual size.
        """
        # Apply session size before calculating positions
        if ResultOverlay._session_size is not None:
            sw_save, sh_save = ResultOverlay._session_size
            self.resize(sw_save, sh_save)

        ow = self.width()
        oh = self.height()

        screen = QApplication.primaryScreen().availableGeometry()
        sw, sh = screen.width(), screen.height()
        sx, sy = screen.x(),    screen.y()

        ow = min(ow, sw - 2 * self.MARGIN)

        def _cx(x: int) -> int:
            return max(sx + self.MARGIN, min(x, sx + sw - ow - self.MARGIN))

        def _cy(y: int) -> int:
            return max(sy + self.MARGIN, min(y, sy + sh - oh - self.MARGIN))

        if ry + rh + self.MARGIN + oh <= sy + sh:
            self.setGeometry(_cx(rx + rw // 2 - ow // 2), ry + rh + self.MARGIN, ow, oh)
            return
        if ry - self.MARGIN - oh >= sy:
            self.setGeometry(_cx(rx + rw // 2 - ow // 2), ry - self.MARGIN - oh, ow, oh)
            return
        if rx + rw + self.MARGIN + ow <= sx + sw:
            self.setGeometry(rx + rw + self.MARGIN, _cy(ry + rh // 2 - oh // 2), ow, oh)
            return
        if rx - self.MARGIN - ow >= sx:
            self.setGeometry(rx - self.MARGIN - ow, _cy(ry + rh // 2 - oh // 2), ow, oh)
            return
        # Centre fallback
        self.setGeometry(sx + (sw - ow) // 2, sy + (sh - oh) // 2, ow, oh)

    # ── Close ─────────────────────────────────────────────────────────────

    def close_overlay(self) -> None:
        """Hide and emit closed signal — does NOT destroy the widget (BUG 4)."""
        self._auto_hide_timer.stop()
        self._paused_remaining = 0   # hygiene: clear paused state on close
        self.hide()
        self.closed.emit()

    # ──────────────────────────────────────────────────────────────────────
    # Internal Slots
    # ──────────────────────────────────────────────────────────────────────

    def _on_copy_ocr(self) -> None:
        self.copy_ocr_requested.emit()

    def _on_copy_translation(self) -> None:
        self.copy_translation_requested.emit()

    def _on_open_main(self) -> None:
        self.open_main_window_requested.emit()

    def _on_translate_clicked(self) -> None:
        """BUG 2: emit translate_requested with current OCR text + selected lang."""
        from services.translation_service import get_language_code
        lang_name = self._lang_combo.currentText()
        lang_code = get_language_code(lang_name)
        if self._current_ocr_text and lang_code:
            self.set_translate_busy(True)
            self.translate_requested.emit(self._current_ocr_text, lang_code)

    def _on_auto_trans_changed(self, state: int) -> None:
        """BUG 2: propagate auto-translate toggle to app."""
        self.auto_translate_toggled.emit(bool(state))

    # ──────────────────────────────────────────────────────────────────────
    # Drag support
    # ──────────────────────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            local = event.position().toPoint()
            edge  = self._get_resize_edge(local)
            if edge:
                # Start a resize drag on this edge/corner
                self._resize_edge         = edge
                self._resize_start_global = event.globalPosition().toPoint()
                g = self.geometry()
                self._resize_start_geom   = (g.x(), g.y(), g.width(), g.height())
            elif local.y() <= 34:
                # Title-bar drag (top 34 px)
                self._drag_pos = (
                    event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                )
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        local = event.position().toPoint()
        if event.buttons() == Qt.MouseButton.LeftButton:
            if self._resize_edge and self._resize_start_global and self._resize_start_geom:
                # --- Resize drag ---
                dx = event.globalPosition().toPoint().x() - self._resize_start_global.x()
                dy = event.globalPosition().toPoint().y() - self._resize_start_global.y()
                ox, oy, ow, oh = self._resize_start_geom
                new_w, new_h   = ow, oh
                if self._resize_edge in ('right', 'corner'):
                    new_w = max(self.minimumWidth(),  ow + dx)
                if self._resize_edge in ('bottom', 'corner'):
                    new_h = max(self.minimumHeight(), oh + dy)
                self.resize(new_w, new_h)
            elif self._drag_pos is not None:
                # --- Title-bar move ---
                self.move(event.globalPosition().toPoint() - self._drag_pos)
        else:
            # No button held — update cursor to give resize feedback
            edge = self._get_resize_edge(local)
            if edge == 'corner':
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif edge == 'right':
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            elif edge == 'bottom':
                self.setCursor(Qt.CursorShape.SizeVerCursor)
            else:
                self.unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_pos            = None
        self._resize_edge         = None
        self._resize_start_global = None
        self._resize_start_geom   = None
        super().mouseReleaseEvent(event)

    def _get_resize_edge(self, local: QPoint) -> str | None:
        """Return 'right', 'bottom', 'corner', or None based on cursor position."""
        x, y  = local.x(), local.y()
        w, h  = self.width(), self.height()
        m     = self.RESIZE_MARGIN
        right  = x >= w - m
        bottom = y >= h - m
        if right and bottom:
            return 'corner'
        if right:
            return 'right'
        if bottom:
            return 'bottom'
        return None

    def enterEvent(self, event) -> None:
        """
        Pause auto-hide timer when the mouse enters the overlay.
        Capture remaining time so leaveEvent can resume accurately.
        """
        if self._autohide_secs > 0:
            # QTimer.remainingTime() returns ms left, or -1 if not running.
            remaining = self._auto_hide_timer.remainingTime()
            self._paused_remaining = remaining if remaining > 0 else 0
            self._auto_hide_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        """
        Resume auto-hide timer when the mouse leaves the overlay.

        Rules:
          - Only resume if autohide is enabled (_autohide_secs > 0).
          - Resume with the exact milliseconds that were remaining when the
            mouse entered — so repeated enter/leave cycles don't reset the
            full countdown each time.
          - If _paused_remaining is 0 (timer had already fired or was never
            started) do nothing — the overlay will stay open as expected.
        """
        if self._autohide_secs > 0 and self._paused_remaining > 0:
            self._auto_hide_timer.start(self._paused_remaining)
        super().leaveEvent(event)

    # ──────────────────────────────────────────────────────────────────────
    # Paint — rounded corners
    # ──────────────────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), 10, 10)
        painter.fillPath(path, QColor("#1e1e2e"))
        painter.setPen(QColor("#45475a"))
        painter.drawPath(path)
        painter.end()

    def resizeEvent(self, event) -> None:
        """
        Phase 6.6 — track user-set size for session persistence.
        The hard width lock is gone; only minimum size is enforced
        (via setMinimumSize in __init__).  Saves the new dimensions as the
        session size so subsequent overlays open at the same size.
        """
        super().resizeEvent(event)
        # Save this size as the session default (used in position_near_region)
        ResultOverlay._session_size = (self.width(), self.height())
