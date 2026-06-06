import os
os.environ['PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT'] = '0'
os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = 'True'

from services.auto_ocr_service import AutoOCRService, ENGINE_SPECS, RECOGNITION_ORDER
print('Engine specs:')
for code, ppv4, name in ENGINE_SPECS:
    print(f'  {code:8s}  ppv4={ppv4}  "{name}"')
print()
print('Recognition order:', RECOGNITION_ORDER)

# Test properties on empty service
svc = AutoOCRService(min_confidence=0.5)
print(f'is_loaded={svc.is_loaded}')
print(f'language_label="{svc.language_label}"')
print(f'engines_loaded={svc.engines_loaded}')
print(f'engines_failed={svc.engines_failed}')
print()
print('=== auto_ocr_service.py OK ===')
