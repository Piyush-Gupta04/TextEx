"""
ui/result_overlay.py
====================
Floating result overlay for Smart Text Extractor — Phase 7.

Displays OCR and (optionally) translation results in a small, always-on-top
frameless window that appears near the captured region immediately after
processing completes.  The window is draggable, does NOT steal keyboard
focus, and can auto-hide after a configurable timeout.

Layout:
    ┌───────────────────────────────────────────────────────────┐
    │  ● Smart Text Extractor              [□] [✕]  (drag bar) │
    ├───────────────────────────────────────────────────────────┤
    │  📄 OCR RESULT                                            │
    │  <ocr text, scrollable>                                   │
    ├───────────────────────────────────────────────────────────┤
    │  🌐 TRANSLATION                       (only if present)  │
    │  <translated text, scrollable>                            │
    ├───────────────────────────────────────────────────────────┤
    │  [⎘ Copy OCR] [⎘ Copy Trans.] [⊞ Open Window] [✕ Close] │
    └───────────────────────────────────────────────────────────┘

Design decisions:
    - Frameless window with custom title bar for dragging.
    - Qt.WindowDoesNotStealFocus so it never interrupts typing.
    - Smart positioning: appears near capture region, never off-screen,
      never covers the capture region entirely.
    - Auto-hide via QTimer (0 = disabled).
    - Single instance: Application always calls close() on any existing
      overlay before creating a new one.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import (
    Qt, QPoint, QRect, QTimer, pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
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
        open_main_window_requested: User clicked "Open Full Window".
        copy_ocr_requested:         User clicked "Copy OCR".
        copy_translation_requested: User clicked "Copy Translation".
        closed:                     Overlay was closed (button or auto-hide).
    """

    open_main_window_requested = pyqtSignal()
    copy_ocr_requested         = pyqtSignal()
    copy_translation_requested = pyqtSignal()
    closed                     = pyqtSignal()

    # Preferred width; height is dynamic
    PREFERRED_WIDTH  = 420
    MAX_HEIGHT       = 520
    MIN_HEIGHT       = 120
    # Gap between overlay and capture region edge
    MARGIN           = 12

    def __init__(self, parent=None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        self._drag_pos: QPoint | None = None
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

        # ── Title / drag bar ──────────────────────────────────────────────
        self._title_bar = self._build_title_bar()
        root.addWidget(self._title_bar)

        # ── OCR section ───────────────────────────────────────────────────
        self._ocr_section = self._build_text_section(
            "📄  OCR RESULT", "ocr"
        )
        root.addWidget(self._ocr_section)

        # ── Translation section (initially hidden) ─────────────────────────
        self._trans_section = self._build_text_section(
            "🌐  TRANSLATION", "trans"
        )
        self._trans_section.hide()
        root.addWidget(self._trans_section)

        # ── Action bar ────────────────────────────────────────────────────
        root.addWidget(self._build_action_bar())

    def _build_title_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("OverlayTitleBar")
        bar.setFixedHeight(34)
        h = QHBoxLayout(bar)
        h.setContentsMargins(10, 0, 8, 0)
        h.setSpacing(6)

        icon_lbl = QLabel("●")
        icon_lbl.setObjectName("OverlayDot")
        h.addWidget(icon_lbl)

        title_lbl = QLabel("Smart Text Extractor")
        title_lbl.setObjectName("OverlayTitle")
        h.addWidget(title_lbl, 1)

        # Minimise-to-main-window button
        open_btn = QPushButton("□")
        open_btn.setObjectName("OverlayTitleBtn")
        open_btn.setFixedSize(22, 22)
        open_btn.setToolTip("Open full window")
        open_btn.clicked.connect(self._on_open_main)
        h.addWidget(open_btn)

        close_btn = QPushButton("✕")
        close_btn.setObjectName("OverlayCloseBtn")
        close_btn.setFixedSize(22, 22)
        close_btn.setToolTip("Close overlay")
        close_btn.clicked.connect(self.close_overlay)
        h.addWidget(close_btn)

        return bar

    def _build_text_section(self, header: str, section_id: str) -> QWidget:
        """Build a collapsible text section (header + scrollable text label)."""
        container = QWidget()
        container.setObjectName(f"OverlaySection_{section_id}")
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # Section header row
        header_bar = QWidget()
        header_bar.setObjectName("OverlaySectionHeader")
        header_bar.setFixedHeight(26)
        hh = QHBoxLayout(header_bar)
        hh.setContentsMargins(10, 0, 10, 0)
        hh.setSpacing(0)
        h_lbl = QLabel(header)
        h_lbl.setObjectName("OverlaySectionTitle")
        hh.addWidget(h_lbl)
        hh.addStretch()
        v.addWidget(header_bar)

        # Scrollable text area
        scroll = QScrollArea()
        scroll.setObjectName(f"OverlayScroll_{section_id}")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setMaximumHeight(180)

        text_lbl = QLabel()
        text_lbl.setObjectName(f"OverlayText_{section_id}")
        text_lbl.setWordWrap(True)
        text_lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        text_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        text_lbl.setMargin(10)

        scroll.setWidget(text_lbl)
        v.addWidget(scroll)

        # Store refs
        if section_id == "ocr":
            self._ocr_label = text_lbl
        else:
            self._trans_label = text_lbl

        return container

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
        self._copy_trans_btn.setVisible(False)   # shown only when translation present
        h.addWidget(self._copy_trans_btn)

        h.addStretch()

        open_btn = QPushButton("⊞ Open Window")
        open_btn.setObjectName("OverlayActionBtnSecondary")
        open_btn.clicked.connect(self._on_open_main)
        h.addWidget(open_btn)

        close_btn = QPushButton("✕ Close")
        close_btn.setObjectName("OverlayActionBtnClose")
        close_btn.clicked.connect(self.close_overlay)
        h.addWidget(close_btn)

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

            /* Title bar */
            QWidget#OverlayTitleBar {
                background: #181825;
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
                border-bottom: 1px solid #313244;
            }
            QLabel#OverlayDot  { color: #2979ff; font-size: 10px; }
            QLabel#OverlayTitle {
                color: #89b4fa;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton#OverlayTitleBtn {
                background: transparent;
                color: #6c7086;
                border: none;
                font-size: 12px;
            }
            QPushButton#OverlayTitleBtn:hover { color: #89b4fa; }
            QPushButton#OverlayCloseBtn {
                background: transparent;
                color: #6c7086;
                border: none;
                font-size: 11px;
            }
            QPushButton#OverlayCloseBtn:hover { color: #f38ba8; }

            /* Section headers */
            QWidget#OverlaySectionHeader {
                background: #181825;
                border-bottom: 1px solid #313244;
            }
            QLabel#OverlaySectionTitle {
                color: #89b4fa;
                font-size: 10px;
                font-weight: bold;
                letter-spacing: 1px;
            }

            /* Text areas */
            QScrollArea {
                background: #1e1e2e;
                border: none;
            }
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
            QPushButton#OverlayActionBtn:hover   { background: #45475a; }
            QPushButton#OverlayActionBtn:pressed  { background: #585b70; }
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

            /* Scrollbars */
            QScrollBar:vertical {
                background: #1e1e2e;
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #45475a;
                border-radius: 4px;
                min-height: 20px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)

    # ──────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────

    def set_ocr_text(self, text: str) -> None:
        """Set the OCR result text."""
        self._ocr_label.setText(text.strip())

    def set_translation_text(self, text: str) -> None:
        """Show or hide the translation section and set its text."""
        clean = text.strip()
        if clean and not clean.startswith("[Translation Error]"):
            self._trans_label.setText(clean)
            self._trans_section.show()
            self._copy_trans_btn.setVisible(True)
        else:
            self._trans_section.hide()
            self._copy_trans_btn.setVisible(False)

    def get_ocr_text(self) -> str:
        return self._ocr_label.text()

    def get_translation_text(self) -> str:
        return self._trans_label.text()

    def position_near_region(
        self,
        rx: int, ry: int, rw: int, rh: int,
    ) -> None:
        """
        Position the overlay near the captured region without covering it
        and without going off-screen.

        Strategy (in priority order):
          1. Below the region (+ MARGIN gap)
          2. Above the region (if not enough space below)
          3. Right of the region
          4. Left of the region
          5. Centre of screen (last resort)
        """
        self.adjustSize()
        ow = self.PREFERRED_WIDTH
        oh = self.height()

        screen = QApplication.primaryScreen().availableGeometry()
        sw, sh = screen.width(), screen.height()
        sx, sy = screen.x(), screen.y()

        # Clamp overlay width to screen
        ow = min(ow, sw - 2 * self.MARGIN)

        def _clamp_x(x: int) -> int:
            return max(sx + self.MARGIN, min(x, sx + sw - ow - self.MARGIN))

        def _clamp_y(y: int) -> int:
            return max(sy + self.MARGIN, min(y, sy + sh - oh - self.MARGIN))

        # Try below
        if ry + rh + self.MARGIN + oh <= sy + sh:
            x = _clamp_x(rx + rw // 2 - ow // 2)
            y = ry + rh + self.MARGIN
            self.setGeometry(x, y, ow, oh)
            return

        # Try above
        if ry - self.MARGIN - oh >= sy:
            x = _clamp_x(rx + rw // 2 - ow // 2)
            y = ry - self.MARGIN - oh
            self.setGeometry(x, y, ow, oh)
            return

        # Try right
        if rx + rw + self.MARGIN + ow <= sx + sw:
            x = rx + rw + self.MARGIN
            y = _clamp_y(ry + rh // 2 - oh // 2)
            self.setGeometry(x, y, ow, oh)
            return

        # Try left
        if rx - self.MARGIN - ow >= sx:
            x = rx - self.MARGIN - ow
            y = _clamp_y(ry + rh // 2 - oh // 2)
            self.setGeometry(x, y, ow, oh)
            return

        # Fallback: centre of screen
        x = sx + (sw - ow) // 2
        y = sy + (sh - oh) // 2
        self.setGeometry(x, y, ow, oh)

    def start_autohide(self, seconds: int) -> None:
        """
        Start the auto-hide countdown.  Pass 0 to disable.
        Resets any existing timer.
        """
        self._auto_hide_timer.stop()
        if seconds > 0:
            self._auto_hide_timer.start(seconds * 1000)

    def stop_autohide(self) -> None:
        """Cancel any pending auto-hide."""
        self._auto_hide_timer.stop()

    def close_overlay(self) -> None:
        """Hide and emit closed signal (does not delete the widget)."""
        self._auto_hide_timer.stop()
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

    # ──────────────────────────────────────────────────────────────────────
    # Drag support (frameless window)
    # ──────────────────────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            # Only drag from title bar area (top 34 px)
            if event.position().y() <= 34:
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if (
            event.buttons() == Qt.MouseButton.LeftButton
            and self._drag_pos is not None
        ):
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def enterEvent(self, event) -> None:
        """Pause auto-hide while the mouse is over the overlay."""
        self._auto_hide_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        """Resume auto-hide countdown when the mouse leaves (if still active)."""
        # Don't restart — once the user has interacted we respect the timer
        # state that was set. Only resume if seconds remain on the original.
        super().leaveEvent(event)

    # ──────────────────────────────────────────────────────────────────────
    # Paint — rounded corners on the frameless widget
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
        """Keep fixed preferred width; let height be dynamic."""
        self.setFixedWidth(self.PREFERRED_WIDTH)
        super().resizeEvent(event)
