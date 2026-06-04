"""
ui/tray.py
==========
System tray icon for Smart Text Extractor — Phase 6.

Provides a persistent icon in the Windows system tray with a full context
menu for all common actions.  The icon is generated programmatically via
QPainter (no external icon file required).

Menu items:
    ● Capture Screen
    ● Show Main Window
    ────────────────
    ● Toggle Auto Translate  (checkable, live)
    ────────────────
    ● History
    ● Settings
    ────────────────
    ● Exit

Behaviour:
    - Double-click / single-click on tray icon → show main window.
    - Closing the main window minimises to tray when that setting is on.
    - Hotkey fires from background even when window is hidden.
    - No duplicate tray icons — TrayIcon is created exactly once in app.py.
    - Settings dialog is shown without needing the main window visible first.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

logger = logging.getLogger(__name__)


class TrayIcon(QSystemTrayIcon):
    """
    Application system tray icon.

    Args:
        app: Reference to the core.app.Application instance so the
             tray can call open/capture/settings/quit actions.
        parent: Optional QObject parent.
    """

    def __init__(self, app, parent=None) -> None:
        super().__init__(self._build_icon(), parent)
        self._app = app
        self._auto_trans_action = None   # kept as ref so we can toggle it
        self._setup_menu()
        self.activated.connect(self._on_activated)
        self.setToolTip("Smart Text Extractor — right-click for menu")

    # ──────────────────────────────────────────────────────────────────────
    # Icon
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _build_icon() -> QIcon:
        """Draw a 32×32 'Tx' icon on a rounded blue background."""
        size = 32
        px = QPixmap(size, size)
        px.fill(Qt.GlobalColor.transparent)

        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Rounded rectangle background
        path = QPainterPath()
        path.addRoundedRect(1, 1, size - 2, size - 2, 7, 7)
        p.fillPath(path, QColor("#2979FF"))

        # White "Tx" text
        font = QFont("Segoe UI", 11, QFont.Weight.Bold)
        p.setFont(font)
        p.setPen(QColor("white"))
        p.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, "Tx")
        p.end()

        return QIcon(px)

    # ──────────────────────────────────────────────────────────────────────
    # Context menu
    # ──────────────────────────────────────────────────────────────────────

    def _setup_menu(self) -> None:
        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background: #1e1e2e;
                color: #cdd6f4;
                border: 1px solid #313244;
                border-radius: 6px;
                padding: 4px 0;
                font-size: 13px;
            }
            QMenu::item {
                padding: 6px 18px 6px 12px;
            }
            QMenu::item:selected {
                background: #313244;
                border-radius: 4px;
            }
            QMenu::item:checked {
                color: #a6e3a1;
            }
            QMenu::separator {
                background: #313244;
                height: 1px;
                margin: 3px 8px;
            }
        """)

        # ── Capture ────────────────────────────────────────────────────────
        capture_act = menu.addAction("⌨   Capture Screen")
        capture_act.triggered.connect(self._capture)

        # ── Show window ────────────────────────────────────────────────────
        open_act = menu.addAction("📋  Show Main Window")
        open_act.triggered.connect(self._open_app)

        menu.addSeparator()

        # ── Toggle Auto Translate (checkable) ──────────────────────────────
        self._auto_trans_action = menu.addAction("🌐  Auto Translate")
        self._auto_trans_action.setCheckable(True)
        # Will be synced from app after settings are loaded
        self._auto_trans_action.triggered.connect(self._toggle_auto_translate)

        menu.addSeparator()

        # ── History ────────────────────────────────────────────────────────
        history_act = menu.addAction("🕓  History")
        history_act.triggered.connect(self._history)

        # ── Settings ───────────────────────────────────────────────────────
        settings_act = menu.addAction("⚙   Settings")
        settings_act.triggered.connect(self._settings)

        menu.addSeparator()

        # ── Exit ───────────────────────────────────────────────────────────
        exit_act = menu.addAction("✕   Exit")
        exit_act.triggered.connect(self._exit)

        self.setContextMenu(menu)

    # ──────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────

    def sync_auto_translate(self, enabled: bool) -> None:
        """Keep the tray checkmark in sync with the actual setting."""
        if self._auto_trans_action is not None:
            self._auto_trans_action.setChecked(enabled)

    def notify(self, title: str, message: str, duration_ms: int = 2500) -> None:
        """Show a desktop notification balloon."""
        self.showMessage(
            title,
            message,
            QSystemTrayIcon.MessageIcon.Information,
            duration_ms,
        )

    # ──────────────────────────────────────────────────────────────────────
    # Activation
    # ──────────────────────────────────────────────────────────────────────

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Double-click or single-click restores the window."""
        if reason in (
            QSystemTrayIcon.ActivationReason.DoubleClick,
            QSystemTrayIcon.ActivationReason.Trigger,
        ):
            self._open_app()

    # ──────────────────────────────────────────────────────────────────────
    # Menu Slots
    # ──────────────────────────────────────────────────────────────────────

    def _open_app(self) -> None:
        win = self._app.main_window
        win.show()
        win.setWindowState(
            win.windowState() & ~Qt.WindowState.WindowMinimized
        )
        win.raise_()
        win.activateWindow()

    def _capture(self) -> None:
        """Trigger OCR capture — works even when the main window is hidden."""
        self._app._show_selection_overlay()

    def _toggle_auto_translate(self, checked: bool) -> None:
        """Toggle auto translate from the tray — persists to settings."""
        self._app.set_auto_translate(checked)

    def _history(self) -> None:
        """Open history — shows the main window first."""
        self._open_app()
        self._app.show_history()

    def _settings(self) -> None:
        """Open settings dialog — shows the main window first."""
        self._open_app()
        self._app.show_settings()

    def _exit(self) -> None:
        QApplication.instance().quit()
