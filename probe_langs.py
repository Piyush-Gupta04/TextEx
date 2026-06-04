"""
Probe which PaddleOCR 3.6.0 lang codes are loadable on this machine.
Runs OUTSIDE Qt to isolate crashes. Safe to kill at any time.
"""
import os, sys, traceback
os.environ['PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT'] = '0'
os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = 'True'

from paddleocr import PaddleOCR

CANDIDATES = [
    # (lang, use_ppv4, label)
    ("en",      True,  "English PP-OCRv4"),
    ("ch",      True,  "Chinese PP-OCRv4"),
    ("ch",      False, "Chinese default"),
    ("ar",      False, "Arabic (ar)"),
    ("arabic",  False, "Arabic (arabic)"),
    ("hi",      False, "Hindi"),
    ("ru",      False, "Russian (ru)"),
    ("russian", False, "Russian (russian)"),
    ("japan",   False, "Japanese"),
    ("korean",  False, "Korean"),
]

working = []
failing = []

for lang, ppv4, label in CANDIDATES:
    print(f"\n{'='*60}")
    print(f"Testing: {label}  (lang={lang!r}, ppv4={ppv4})")
    print('='*60)
    try:
        kwargs = dict(
            lang=lang,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
        if ppv4:
            kwargs["ocr_version"] = "PP-OCRv4"
        engine = PaddleOCR(**kwargs)
        print(f"  >>> LOADED OK: {label}")
        working.append(label)
        del engine
    except Exception as exc:
        print(f"  >>> FAILED: {exc}")
        failing.append((label, str(exc)))

print("\n" + "="*60)
print("SUMMARY")
print("="*60)
print(f"Working ({len(working)}): {working}")
print(f"Failing ({len(failing)}):")
for name, err in failing:
    print(f"  {name}: {err[:80]}")
