"""
test_launch.py — Launches the app and captures ALL output including stderr.
Run from the project root:  python test_launch.py
"""
import subprocess, sys, os

env = os.environ.copy()
env["PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT"] = "0"
env["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"

result = subprocess.run(
    [sys.executable, "main.py"],
    capture_output=False,   # let output go to terminal in real time
    env=env,
    cwd=os.path.dirname(os.path.abspath(__file__)),
)
print(f"\n[test_launch] Process exited with code: {result.returncode}")
