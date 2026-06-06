# textex_packaging/runtime_hook.py
# ─────────────────────────────────────────────────────────────────────────────
# PyInstaller runtime hook for TextEx.
#
# This script is executed by the PyInstaller bootloader BEFORE main.py (or any
# frozen module) is imported.  It sets the critical PaddleX / PaddlePaddle
# environment variables so they take effect regardless of import order inside
# the frozen bundle.
#
# Reference: PyInstaller docs — "Run-time hooks"
# ─────────────────────────────────────────────────────────────────────────────

import os

# Disable oneDNN (MKL-DNN) backend — crashes on PaddlePaddle 3.3.1 + Windows
# due to an unimplemented PIR attribute conversion in onednn_instruction.cc.
os.environ.setdefault("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT", "0")

# Skip the remote connectivity check — prevents a 30-second stall on startup.
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

# Suppress PaddlePaddle noisy INFO banner in the log file.
os.environ.setdefault("GLOG_minloglevel", "3")
os.environ.setdefault("FLAGS_call_stack_level", "0")
