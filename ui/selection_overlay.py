"""
ui/selection_overlay.py
=======================
Full-screen transparent overlay for region selection.

Behaviour:
    - Covers every connected screen with a dark semi-transparent wash.
    - Left-click + drag draws a highlighted selection rectangle.
    - On mouse release the overlay hides itself IMMEDIATELY (before emitting
      the signal) so the screen is fully repainted before CaptureService
      takes its screenshot.  A 60 ms QTimer gives the OS compositor time
      to remove the window from the screen buffer.
    - After the timer fires, region_selected(x, y, width, height) is emitted
      with global physical-pixel coordinates, then deleteLater() is called to
      release the Qt object.
    - Pressing ESC cancels without emitting the signal.

Why hide-before-emit matters:
    region_selected is connected directly (same thread) to
    Application._on_region_selected(), which immediately calls
    CaptureService.capture() via mss.  If the overlay window is still
    painted when mss grabs the screen the dark wash appears in the
    captured image.  hide() + processEvents() + a short singleShot()
    delay guarantees the window manager has removed the overlay before
    the screenshot is taken.
"""

from PyQt6.QtCore import Qt, QRect, QPoint, QTimer, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen
from PyQt6.QtWidgets import QApplication, QWidget


class SelectionOverlay(QWidget):
    """
    Frameless, always-on-top, full-screen selection overlay.

    Signals:
        region_selected(int, int, int, int):
            Emitted after the overlay has been hidden and the OS has had
            time to repaint the desktop.
            Arguments: x, y, width, height in global physical (mss) pixels.
    """

    # Emitted with (x, y, width, height) in physical screen pixels
    region_selected = pyqtSignal(int, int, int, int)

    # ── Visual constants ───────────────────────────────────────────────────
    BACKGROUND_COLOR = QColor(0,   0,   0,  110)   # dark wash
    SELECTION_FILL   = QColor(255, 255, 255, 35)    # subtle interior
    SELECTION_BORDER = QColor(0,   174, 255, 230)   # vivid blue outline
    BORDER_WIDTH     = 2                            # px

    # Milliseconds to wait after hide() before emitting the signal.
    # Gives the OS compositor time to fully remove the overlay from the
    # screen buffer so it does not appear in the screenshot.
    _HIDE_DELAY_MS = 80

    def __init__(self, parent=None):
        super().__init__(parent)

        self._start:     QPoint | None = None
        self._end:       QPoint | None = None
        self._selecting: bool          = False
        self._cancelled: bool          = False   # set by _dismiss(); guards _emit_and_release

        self._configure_window()

    # ──────────────────────────────────────────────────────────────────────
    # Window Setup
    # ──────────────────────────────────────────────────────────────────────

    def _configure_window(self):
        """Apply window flags, transparency, cursor, and geometry."""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setCursor(Qt.CursorShape.CrossCursor)

        # Expand to cover ALL connected screens
        combined = QRect()
        for screen in QApplication.screens():
            combined = combined.united(screen.geometry())
        self.setGeometry(combined)

    # ──────────────────────────────────────────────────────────────────────
    # Paint
    # ──────────────────────────────────────────────────────────────────────

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Full-screen dark wash
        painter.fillRect(self.rect(), self.BACKGROUND_COLOR)

        # Selection rectangle (only while/after dragging)
        if self._start and self._end:
            sel = QRect(self._start, self._end).normalized()
            painter.fillRect(sel, self.SELECTION_FILL)
            pen = QPen(
                self.SELECTION_BORDER,
                self.BORDER_WIDTH,
                Qt.PenStyle.SolidLine,
            )
            painter.setPen(pen)
            painter.drawRect(sel)

        painter.end()

    # ──────────────────────────────────────────────────────────────────────
    # Mouse Events
    # ──────────────────────────────────────────────────────────────────────

    def mousePressEvent(self, event):  # noqa: N802
        """Record the anchor point when the left button is pressed."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._start     = event.pos()
            self._end       = event.pos()
            self._selecting = True
            self.update()

    def mouseMoveEvent(self, event):  # noqa: N802
        """Extend the selection rectangle as the mouse is dragged."""
        if self._selecting:
            self._end = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):  # noqa: N802
        """
        Finish the selection.

        Sequence:
            1. Compute physical-pixel coordinates (DPI-scaled).
            2. Hide the overlay window immediately.
            3. Call QApplication.processEvents() to flush the pending hide
               so the OS repaints the desktop beneath the overlay.
            4. Use QTimer.singleShot(_HIDE_DELAY_MS) to wait for the
               compositor to fully remove the window from the screen buffer.
            5. Emit region_selected from the timer callback.
            6. Call deleteLater() to release the Qt object.

        Qt mouse events use logical (device-independent) pixels.
        mss captures physical pixels.  On a 150% display, multiply by
        devicePixelRatio() to convert.
        """
        if not (event.button() == Qt.MouseButton.LeftButton and self._selecting):
            return

        self._end       = event.pos()
        self._selecting = False

        sel = QRect(self._start, self._end).normalized()

        # Reject accidental tiny clicks (< 5×5 logical px)
        if sel.width() < 5 or sel.height() < 5:
            self._dismiss()
            return

        # Convert widget-local -> global logical coordinates
        global_origin = self.mapToGlobal(sel.topLeft())

        # Scale logical -> physical pixels for mss
        screen      = self.screen()
        dpr: float  = screen.devicePixelRatio() if screen else 1.0

        px = int(global_origin.x() * dpr)
        py = int(global_origin.y() * dpr)
        pw = int(sel.width()  * dpr)
        ph = int(sel.height() * dpr)

        print(
            f"[SelectionOverlay] Region x={px} y={py} "
            f"w={pw} h={ph} DPR={dpr:.2f}"
        )

        # ── Step 2-4: hide now, wait, then emit ───────────────────────────
        self.hide()
        QApplication.processEvents()  # flush hide event to OS
        QTimer.singleShot(
            self._HIDE_DELAY_MS,
            lambda: self._emit_and_release(px, py, pw, ph),
        )

    # ──────────────────────────────────────────────────────────────────────
    # Keyboard Events
    # ──────────────────────────────────────────────────────────────────────

    def keyPressEvent(self, event):  # noqa: N802
        """ESC cancels the overlay without emitting region_selected."""
        if event.key() == Qt.Key.Key_Escape:
            print("[SelectionOverlay] Cancelled by ESC")
            self._dismiss()
        else:
            super().keyPressEvent(event)

    # ──────────────────────────────────────────────────────────────────────
    # Internal
    # ──────────────────────────────────────────────────────────────────────

    def _emit_and_release(self, px: int, py: int, pw: int, ph: int) -> None:
        """
        Called by QTimer after the OS has had time to repaint the desktop.
        Guards against the case where the user pressed ESC between
        mouseReleaseEvent and the timer firing (_cancelled flag).
        Emits region_selected synchronously, then schedules self for deletion.
        """
        if self._cancelled:
            # Overlay was already dismissed via ESC; do not emit.
            return
        self.region_selected.emit(px, py, pw, ph)
        self.deleteLater()

    def _dismiss(self) -> None:
        """Hide and schedule deletion without emitting region_selected."""
        self._cancelled = True
        self.hide()
        self.deleteLater()
