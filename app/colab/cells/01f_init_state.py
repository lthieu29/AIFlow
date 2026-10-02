"""Cell 1f — Tạo work dir + summary."""
from cells._shared import (
    BASE_MODEL,
    DATASET_DIR,
    DRIVE_DIR,
    RAW_AUDIO_DIR,
    RUNTIME,
    WORK_DIR,
    banner,
)

WORK_DIR.mkdir(exist_ok=True)
DATASET_DIR.mkdir(parents=True, exist_ok=True)
RAW_AUDIO_DIR.mkdir(parents=True, exist_ok=True)

banner('✅ Setup complete')
print(f'   Runtime:   {RUNTIME["name"]} ({RUNTIME["tier"]})')
print(f'   Base model: {BASE_MODEL}')
print(f'   Work dir:  {WORK_DIR}')
print(f'   Drive:     {DRIVE_DIR}')
print(f'\nNext: chạy Cell 2b (Path A — zip) hoặc Cell 2c (Path B — 1 file).')
