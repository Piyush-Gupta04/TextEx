"""
services/clipboard_service.py
=============================
Thin clipboard helper for Smart Text Extractor.

Wraps QApplication.clipboard() so that OCRService results can be
copied to the system clipboard from any thread that invokes this
method on the main thread (via a Qt signal/slot).

Usage:
    ClipboardService.copy("extracted text")
"""

from PyQt6.QtWidgets import QApplication


class ClipboardService:
    """Static helper for clipboard operations."""

    @staticmethod
    def copy(text: str) -> bool:
        """
        Copy text to the system clipboard.

        Must be called on the Qt main thread.

        Args:
            text: The string to place on the clipboard.

        Returns:
            True on success, False if QApplication is not available.
        """
        app = QApplication.instance()
        if app is None:
            return False
        app.clipboard().setText(text)
        return True

    @staticmethod
    def get() -> str:
        """Return the current clipboard text (empty string on failure)."""
        app = QApplication.instance()
        if app is None:
            return ""
        return app.clipboard().text()
