"""
services/shortcut_service.py
============================
Global hotkey detection service for Smart Text Extractor.

Inherits from QObject so it can emit a proper Qt signal.
The `keyboard` library fires its callback on its own internal thread;
Qt automatically promotes the signal emission to a queued connection
when the receiver lives in a different thread — making this
cross-thread pattern safe without any manual locking.

Supports live hotkey switching via change_hotkey() with no restart
required — the old hook is unregistered and a new one is registered
in one atomic call.
"""

import logging

import keyboard
from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)


class ShortcutService(QObject):
    """
    Manages global keyboard shortcuts for Smart Text Extractor.

    Signals:
        hotkey_triggered: Emitted (thread-safely) whenever the registered
                          hotkey is detected system-wide.

    Usage:
        service = ShortcutService(hotkey="ctrl+alt+x")
        service.hotkey_triggered.connect(some_slot)
        service.start()
        ...
        service.change_hotkey("ctrl+shift+s")   # live swap
        ...
        service.stop()
    """

    # Emitted from keyboard's hook thread; Qt queues it to the main thread
    hotkey_triggered = pyqtSignal()

    DEFAULT_HOTKEY = "ctrl+alt+x"

    def __init__(self, hotkey: str = DEFAULT_HOTKEY, parent: QObject = None):
        """
        Initialise the ShortcutService.

        Args:
            hotkey: Key combination string in keyboard library syntax,
                    e.g. 'ctrl+alt+x', 'ctrl+shift+s'.
            parent: Optional QObject parent.
        """
        super().__init__(parent)
        self._hotkey  = hotkey
        self._hook    = None   # handle returned by keyboard.add_hotkey()
        self._running = False

    # ──────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────

    def start(self) -> None:
        """
        Register the global hotkey with the OS.
        Safe to call multiple times — subsequent calls are no-ops.
        """
        if self._running:
            return
        try:
            self._hook = keyboard.add_hotkey(self._hotkey, self._on_hotkey_pressed)
            self._running = True
            print(f"[ShortcutService] Registered hotkey: '{self._hotkey}'")
            logger.info("[ShortcutService] Registered hotkey: '%s'", self._hotkey)
        except Exception as exc:
            self._hook = None
            logger.error("[ShortcutService] Failed to register '%s': %s", self._hotkey, exc)
            print(f"[ShortcutService] Error registering hotkey: {exc}")

    def stop(self) -> None:
        """
        Unregister the hotkey and release the OS hook.
        Called automatically via Application._cleanup() on exit.
        """
        if not self._running:
            return
        self._remove_hook()
        self._running = False
        print(f"[ShortcutService] Unregistered hotkey: '{self._hotkey}'")
        logger.info("[ShortcutService] Unregistered hotkey: '%s'", self._hotkey)

    def change_hotkey(self, new_hotkey: str) -> None:
        """
        Replace the active hotkey without stopping and restarting the service.

        Safe to call while running.  If the service is not running, just
        updates the stored combo so the next start() uses the new value.

        Args:
            new_hotkey: New key combination string (keyboard library syntax).
        """
        new_hotkey = new_hotkey.strip().lower()
        if not new_hotkey:
            logger.warning("[ShortcutService] Ignoring empty hotkey.")
            return

        if new_hotkey == self._hotkey:
            return

        # Unregister old hook if running
        if self._running:
            self._remove_hook()
            self._running = False

        self._hotkey = new_hotkey

        # Re-register with new combo
        try:
            self._hook = keyboard.add_hotkey(self._hotkey, self._on_hotkey_pressed)
            self._running = True
            print(f"[ShortcutService] Hotkey changed to: '{self._hotkey}'")
            logger.info("[ShortcutService] Hotkey changed to: '%s'", self._hotkey)
        except Exception as exc:
            self._hook = None
            logger.error("[ShortcutService] Failed to register '%s': %s", self._hotkey, exc)
            print(f"[ShortcutService] Error registering new hotkey: {exc}")

    # ──────────────────────────────────────────────────────────────────────
    # Properties
    # ──────────────────────────────────────────────────────────────────────

    @property
    def hotkey(self) -> str:
        """The currently registered hotkey string."""
        return self._hotkey

    @property
    def is_running(self) -> bool:
        """True if the hotkey listener is active."""
        return self._running

    # ──────────────────────────────────────────────────────────────────────
    # Internal Helpers
    # ──────────────────────────────────────────────────────────────────────

    def _remove_hook(self) -> None:
        """
        Safely remove the keyboard hook using the stored handle.
        Falls back to string-based removal if the handle is unavailable.
        """
        if self._hook is not None:
            try:
                keyboard.remove_hotkey(self._hook)
            except Exception:
                pass
            self._hook = None
        else:
            try:
                keyboard.remove_hotkey(self._hotkey)
            except Exception:
                pass

    # ──────────────────────────────────────────────────────────────────────
    # Internal Callback  (runs on keyboard's hook thread)
    # ──────────────────────────────────────────────────────────────────────

    def _on_hotkey_pressed(self) -> None:
        """
        Called by the keyboard library on its own thread.
        Emitting a pyqtSignal here is safe — Qt will automatically use
        a QueuedConnection to deliver it on the main thread.
        """
        self.hotkey_triggered.emit()
