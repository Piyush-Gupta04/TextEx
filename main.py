"""
main.py
=======
Entry point for Smart Text Extractor.

Sets critical environment variables and DPI awareness BEFORE any
Qt or PaddleOCR imports so that both subsystems see the correct config
from the very first import.

Environment flags set here:
    PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT=0
        Disables PaddleX's default oneDNN (MKL-DNN) CPU backend which
        crashes with NotImplementedError on PaddlePaddle 3.3.1 + Windows
        due to an unimplemented PIR attribute conversion in
        onednn_instruction.cc.

    PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
        Skips the remote connectivity check on startup, preventing a
        30-second stall before each session.

DPI awareness:
    SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE) ensures that
    all Windows API calls, Qt, and mss agree on physical pixel coordinates.
"""

import os
import sys
import logging
from logging.handlers import RotatingFileHandler

# ── Ensure the project root is always on sys.path ─────────────────────────
# This allows `python main.py` to work regardless of the shell's CWD.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# ── Set up logging BEFORE any heavy imports ───────────────────────────────
# Phase 10: always write to %APPDATA%\TextEx\logs\textex.log so errors are
# visible even in the packaged (no-console) executable.
from textex_packaging.paths import ensure_dirs, get_log_path  # noqa: E402
ensure_dirs()                                           # create dirs if needed

_log_fmt = "%(asctime)s  %(levelname)-8s  %(name)s: %(message)s"
_log_date = "%H:%M:%S"

logging.basicConfig(
    level=logging.INFO,
    format=_log_fmt,
    datefmt=_log_date,
)

# Rotating file handler: 5 MB × 3 backup files
_fh = RotatingFileHandler(
    get_log_path(), maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
)
_fh.setLevel(logging.INFO)
_fh.setFormatter(logging.Formatter(_log_fmt, datefmt=_log_date))
logging.getLogger().addHandler(_fh)

# Suppress PaddleOCR/PaddlePaddle/PaddleX noise
for _noisy in ("ppocr", "paddle", "PaddleOCR", "ppdet",
               "ppocrlite", "paddlex", "root"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

# ── Set PaddleX environment flags before any PaddleOCR import ─────────────
os.environ.setdefault("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT", "0")
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

# ── Set Windows DPI awareness before creating QApplication ────────────────
def _set_dpi_awareness() -> None:
    """
    Set PROCESS_PER_MONITOR_DPI_AWARE (level 2) so that:
    - Qt receives real physical-pixel coordinates for mouse events.
    - mss captures in physical pixels (its native unit).
    - The selection overlay and the captured region always match.

    Falls back to system-DPI aware (level 1) if the per-monitor API
    is unavailable (pre-Win8.1 systems).
    """
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # PER_MONITOR_AWARE
    except (AttributeError, OSError):
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()    # SYSTEM_AWARE fallback
        except (AttributeError, OSError):
            pass   # Non-Windows or very old Windows — skip silently


_set_dpi_awareness()

# ── Application entry point ───────────────────────────────────────────────
from core.app import Application


def main() -> None:
    """Launch the Smart Text Extractor application."""
    app = Application(sys.argv)
    exit_code = app.run()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
