"""
validate_multilingual_ocr.py
============================
Automated multilingual OCR validation for Smart Text Extractor.

Creates a synthetic test image containing mixed-script text and
verifies that AutoOCRService correctly identifies characters from
every supported script group.

Test string:
    Good अच्छा مرحبا 좋다 Gut 良い

Expected scripts detected:
    ✓ Latin     "Good" / "Gut"
    ✓ Devanagari "अच्छा"
    ✓ Arabic    "مرحبا"
    ✓ Korean    "좋다"
    ✓ CJK       "良い"

Run from the project root:
    venv\\Scripts\\python.exe validate_multilingual_ocr.py

The script exits with code 0 when all checks pass, code 1 otherwise.
A summary image is saved to captures/ocr_validation_input.png so you can
inspect what the OCR engines actually see.
"""

import os
import sys
import unicodedata

os.environ["PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT"]     = "0"
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"]  = "True"

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# ─── Add project root to path ────────────────────────────────────────────────
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from services.auto_ocr_service import AutoOCRService

# ─── Test configuration ───────────────────────────────────────────────────────
TEST_TEXT = "Good अच्छा مرحبا 좋다 Gut 良い"

# Script checks: (script_name, sample_chars_from_that_script)
SCRIPT_CHECKS = [
    ("Latin (Good/Gut)",  "Good"),
    ("Devanagari (Hindi)", "अच"),
    ("Arabic",             "مر"),
    ("Korean",             "좋"),
    ("CJK (Japanese/Chinese)", "良"),
]

# Font candidates with broad Unicode coverage, tried in order.
# On Windows, Segoe UI has excellent coverage for most scripts.
FONT_CANDIDATES = [
    "seguiemj.ttf",           # Segoe UI Emoji (Windows)
    "segoeui.ttf",            # Segoe UI (Windows)
    "arial.ttf",              # Arial (Windows / cross-platform)
    "Arial Unicode MS.ttf",   # Arial Unicode MS
    "NotoSans-Regular.ttf",   # Noto Sans (if installed)
    "DejaVuSans.ttf",         # DejaVu Sans (often available)
]

OUTPUT_PATH = os.path.join(_ROOT, "captures", "ocr_validation_input.png")
IMG_WIDTH   = 900
IMG_HEIGHT  = 120
FONT_SIZE   = 42


# ─── Image creation ───────────────────────────────────────────────────────────

def _find_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Try font candidates from system font directories; fall back to default."""
    import platform
    search_dirs = ["."]
    if platform.system() == "Windows":
        search_dirs += [
            os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts"),
        ]
    else:
        search_dirs += ["/usr/share/fonts", "/usr/local/share/fonts",
                        os.path.expanduser("~/.fonts")]

    for fname in FONT_CANDIDATES:
        for d in search_dirs:
            full = os.path.join(d, fname)
            if os.path.isfile(full):
                try:
                    return ImageFont.truetype(full, size)
                except Exception:
                    pass

    print("  [warn] No Unicode-capable font found; using default bitmap font.")
    print("         Install 'Segoe UI' (Windows) or 'Noto Sans' for best results.")
    return ImageFont.load_default()


def create_test_image(text: str) -> np.ndarray:
    """Render the test string onto a white image and return as BGR numpy array."""
    img  = Image.new("RGB", (IMG_WIDTH, IMG_HEIGHT), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    font = _find_font(FONT_SIZE)

    # Center the text
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw   = bbox[2] - bbox[0]
        th   = bbox[3] - bbox[1]
        x    = max((IMG_WIDTH  - tw) // 2, 5)
        y    = max((IMG_HEIGHT - th) // 2, 5)
    except AttributeError:
        # Older Pillow without textbbox
        tw, th = draw.textsize(text, font=font)
        x = max((IMG_WIDTH  - tw) // 2, 5)
        y = max((IMG_HEIGHT - th) // 2, 5)

    draw.text((x, y), text, fill=(10, 10, 10), font=font)

    # Save the input image for human inspection
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    img.save(OUTPUT_PATH)
    print(f"  Test image saved: {OUTPUT_PATH}")

    # Convert RGB → BGR (what PaddleOCR expects)
    arr = np.array(img)
    bgr = arr[:, :, ::-1].copy()
    return bgr


# ─── Script detection helpers ─────────────────────────────────────────────────

def _script_of_char(ch: str) -> str:
    """Return the Unicode script name for a single character."""
    try:
        name = unicodedata.name(ch, "")
        if not name:
            return "Unknown"
        parts = name.split()
        return parts[0]
    except Exception:
        return "Unknown"


def text_contains_chars(ocr_output: str, sample: str) -> bool:
    """
    Check whether OCR output contains any of the sample characters.
    Case-insensitive for Latin; exact for non-Latin.
    """
    ocr_lower = ocr_output.lower()
    for ch in sample:
        if ch.lower() in ocr_lower:
            return True
    return False


# ─── Main validation ──────────────────────────────────────────────────────────

def main() -> int:
    print("=" * 60)
    print("Smart Text Extractor — Multilingual OCR Validation")
    print("=" * 60)
    print(f"\nTest string: {TEST_TEXT!r}\n")

    # Step 1: load OCR service
    print("[1/4] Loading AutoOCR engines (this may take a while)...")
    svc = AutoOCRService(min_confidence=0.35)   # lower threshold for test image
    svc.load_all()

    if not svc.is_loaded:
        print("\n❌ FATAL: No OCR engines loaded. Aborting.")
        return 1

    print(f"      {svc.engines_loaded} engine(s) loaded, "
          f"{svc.engines_failed} failed.\n")

    # Step 2: create test image
    print("[2/4] Creating synthetic test image...")
    image = create_test_image(TEST_TEXT)
    print(f"      Image shape: {image.shape}  (H×W×C, BGR)\n")

    # Step 3: run OCR
    print("[3/4] Running multilingual OCR...")
    try:
        result = svc.recognize(image)
    except Exception as exc:
        print(f"\n❌ OCR raised exception: {exc}")
        return 1

    print(f"\n      Raw OCR output:\n      {result!r}\n")
    print(f"      Duration: {svc.last_duration:.2f}s\n")

    # Step 4: check per-script detection
    print("[4/4] Checking per-script output...")
    print("-" * 60)

    passed = 0
    failed = 0
    results = []

    for script_name, sample in SCRIPT_CHECKS:
        found = text_contains_chars(result, sample)
        status = "✓ PASS" if found else "✗ FAIL"
        results.append((script_name, sample, found, status))
        if found:
            passed += 1
        else:
            failed += 1
        print(f"  {status}  {script_name:30s}  (looking for: {sample!r})")

    print("-" * 60)
    print(f"\n  Result: {passed}/{len(SCRIPT_CHECKS)} script checks passed\n")

    # Summary
    print("=" * 60)
    if failed == 0:
        print("✅  ALL CHECKS PASSED — multilingual OCR is working correctly.")
        print(f"    Input:    {TEST_TEXT!r}")
        print(f"    Output:   {result.strip()!r}")
        exit_code = 0
    else:
        print(f"❌  {failed} CHECK(S) FAILED — some scripts were not correctly extracted.")
        print()
        print("Troubleshooting:")
        print("  1. Ensure the PaddleOCR engine for the failing script was loaded")
        print("     (check the loading output above for ✘ marks).")
        print("  2. The test image uses a system font — if the font does not")
        print("     support a script's characters, they may render as boxes.")
        print("     Install 'Noto Sans' or 'Segoe UI' for full Unicode coverage.")
        print("  3. Try lowering min_confidence (currently 0.35) if engines load")
        print("     but confidence is below the threshold.")
        print()
        print(f"  Raw output was: {result!r}")
        exit_code = 1
    print("=" * 60)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
