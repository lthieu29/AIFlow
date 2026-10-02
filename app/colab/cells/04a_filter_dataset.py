"""Cell 4a (Path A) — Filter + chuẩn hoá metadata cho training.

Đa phần validate đã làm ở 02b. Cell này tạo metadata_cleaned.csv cho bước encode.
"""
import shutil
from pathlib import Path

from cells._shared import DATASET_DIR, _state, banner, require_state

require_state('mode', 'data_ready', 'config')
if _state['mode'] != 'lora':
    raise SystemExit('ℹ️ Mode = embedding — bỏ qua cell này, chạy Cell 4 (Path B).')

metadata_path = DATASET_DIR / 'metadata.csv'
cleaned_path = DATASET_DIR / 'metadata_cleaned.csv'

if not metadata_path.exists():
    raise SystemExit(f'❌ Không thấy {metadata_path}. Chạy lại Cell 2b.')

shutil.copy(str(metadata_path), str(cleaned_path))
n = sum(1 for _ in open(cleaned_path, encoding='utf-8'))

banner('✅ Filter complete')
print(f'   metadata_cleaned.csv: {n} dòng')
