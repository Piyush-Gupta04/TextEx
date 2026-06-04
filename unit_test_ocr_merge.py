# -*- coding: utf-8 -*-

import os, sys, numpy as np
import io
os.environ['PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT'] = '0'
os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = 'True'

# Force UTF-8 output so Devanagari/Arabic/CJK print correctly on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from services.auto_ocr_service import AutoOCRService, IOU_THRESHOLD, _BOX_KEYS

print('=== Testing _box_to_rect ===')
box1 = [[10, 20], [110, 20], [110, 50], [10, 50]]
rect1 = AutoOCRService._box_to_rect(box1)
assert rect1 == (10.0, 20.0, 110.0, 50.0), f'Got {rect1}'
print(f'  Polygon box  -> {rect1}  OK')

box2 = [10, 20, 110, 20, 110, 50, 10, 50]
rect2 = AutoOCRService._box_to_rect(box2)
assert rect2 == (10.0, 20.0, 110.0, 50.0), f'Got {rect2}'
print(f'  Flat array   -> {rect2}  OK')

assert AutoOCRService._box_to_rect(None) is None
print('  None         -> None  OK')

print()
print('=== Testing _rect_iou ===')
a = (0.0, 0.0, 100.0, 50.0)
b = (0.0, 0.0, 100.0, 50.0)
iou_same = AutoOCRService._rect_iou(a, b)
assert abs(iou_same - 1.0) < 1e-6, f'Expected 1.0 got {iou_same}'
print(f'  Same rects     IoU={iou_same:.4f}  OK')

c = (200.0, 0.0, 300.0, 50.0)
iou_no = AutoOCRService._rect_iou(a, c)
assert iou_no == 0.0, f'Expected 0.0 got {iou_no}'
print(f'  No overlap     IoU={iou_no:.4f}  OK')

d = (50.0, 0.0, 150.0, 50.0)
iou_half = AutoOCRService._rect_iou(a, d)
expected = 2500.0 / 7500.0
assert abs(iou_half - expected) < 1e-4, f'Expected {expected:.4f} got {iou_half}'
print(f'  50%% overlap   IoU={iou_half:.4f} (expected {expected:.4f})  OK')

print()
print('=== Testing _merge_by_region with synthetic mixed-script data ===')

svc = AutoOCRService(min_confidence=0.5)

engine_regions = {
    'en': [
        {'text': 'Good', 'score': 0.99, 'rect': (0,   10, 80,  40), 'engine': 'en'},
        {'text': '3|9T', 'score': 0.35, 'rect': (90,  10, 200, 40), 'engine': 'en'},
        {'text': 'Lz1',  'score': 0.30, 'rect': (210, 10, 310, 40), 'engine': 'en'},
    ],
    'hi': [
        {'text': 'अच्छा', 'score': 0.92, 'rect': (92,  8, 198, 42), 'engine': 'hi'},
    ],
    'ar': [
        {'text': 'مرحبا', 'score': 0.94, 'rect': (212, 9, 308, 41), 'engine': 'ar'},
    ],
}

merged = svc._merge_by_region(engine_regions)
merged_sorted = svc._sort_reading_order(merged)

texts   = [r['text'] for r in merged_sorted]
engines = [r['engine'] for r in merged_sorted]

print(f'  Merged texts:    {texts}')
print(f'  Winning engines: {engines}')

assert 'Good'    in texts, f'Missing Good in {texts}'
assert 'अच्छा'  in texts, f'Missing Hindi in {texts}'
assert 'مرحبا'  in texts, f'Missing Arabic in {texts}'
assert '3|9T'   not in texts, f'English garbage should be replaced!'
assert 'Lz1'    not in texts, f'English garbage should be replaced!'

good_r   = next(r for r in merged_sorted if r['text'] == 'Good')
hindi_r  = next(r for r in merged_sorted if r['text'] == 'अच्छा')
arabic_r = next(r for r in merged_sorted if r['text'] == 'مرحبا')

assert good_r['engine']   == 'en', f"Expected en, got {good_r['engine']}"
assert hindi_r['engine']  == 'hi', f"Expected hi, got {hindi_r['engine']}"
assert arabic_r['engine'] == 'ar', f"Expected ar, got {arabic_r['engine']}"

print('  PASS Good   -> en engine (0.99) beats nobody')
print('  PASS Hindi  -> hi engine (0.92) beats en (0.35) garbage')
print('  PASS Arabic -> ar engine (0.94) beats en (0.30) garbage')
print('  PASS Garbage tokens 3|9T and Lz1 correctly eliminated')

print()
print('=== Testing Unicode preservation ===')
test_str = 'Good \u0905\u091a\u094d\u091b\u093e \u0645\u0631\u062d\u0628\u0627 \uc88b\ub2e4 Gut \u826f\u3044'
encoded = test_str.encode('utf-8')
decoded = encoded.decode('utf-8')
assert decoded == test_str
print(f'  UTF-8 round-trip OK')
print(f'  String: {decoded!r}')

print()
print('ALL UNIT TESTS PASSED')
