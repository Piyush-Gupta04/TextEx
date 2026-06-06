r"""
textex_packaging/paths.py
==================
Centralized user-data path resolution for Smart Text Extractor.

All user-writable files (SQLite DB, screenshots, logs) are stored under
%APPDATA%\TextEx\ on Windows so that:

  1. The app works correctly when installed to Program Files (read-only for
     non-admin users).
  2. User data survives application upgrades (the installer never touches
     %APPDATA%).
  3. Both the development venv and the packaged executable use the same
     data location.

Directory layout:
    %APPDATA%\TextEx\
        history.db          -- OCR history (SQLite)
        captures\           -- timestamped screenshot PNGs
        logs\               -- rotating textex.log

Settings are stored via QSettings("TextEx", "SmartTextExtractor") which
uses the Windows registry (HKCU) and requires no path resolution here.
"""

from __future__ import annotations

import os


def get_app_data_dir() -> str:
    """
    Return the root user-data directory for TextEx.

    Windows : %APPDATA%\\TextEx\\   (e.g. C:\\Users\\alice\\AppData\\Roaming\\TextEx)
    Other   : ~/.local/share/TextEx/  (fallback for non-Windows dev environments)
    """
    base = os.environ.get("APPDATA") or os.path.join(
        os.path.expanduser("~"), ".local", "share"
    )
    return os.path.join(base, "TextEx")


def get_db_path() -> str:
    """Absolute path to the SQLite history database."""
    return os.path.join(get_app_data_dir(), "history.db")


def get_captures_dir() -> str:
    """Absolute path to the screenshot captures directory."""
    return os.path.join(get_app_data_dir(), "captures")


def get_logs_dir() -> str:
    """Absolute path to the application log directory."""
    return os.path.join(get_app_data_dir(), "logs")


def get_log_path() -> str:
    """Absolute path to the rotating log file."""
    return os.path.join(get_logs_dir(), "textex.log")


def ensure_dirs() -> None:
    """Create all required data directories if they do not already exist."""
    for d in (get_app_data_dir(), get_captures_dir(), get_logs_dir()):
        os.makedirs(d, exist_ok=True)
