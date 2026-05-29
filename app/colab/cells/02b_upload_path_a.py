"""Cell 2b — Path A: Upload zip dataset cho LoRA fine-tune.

Cấu trúc zip yêu cầu:
    training_data.zip
    ├── audio/
    │   ├── 001.wav  (3-15s)
    │   └── ...
    └── transcript.csv  (filename|text per dòng, không header)
"""
from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

from google.colab import files

from cells._shared import (
    DATASET_DIR,
    RAW_AUDIO_DIR,
    WORK_DIR,
    _state,
    banner,
    ensure_16khz_mono,
    reset_dir,
    validate_audio_file,
)

print('📦 Path A — Upload training_data.zip')
uploaded = files.upload()
if not uploaded:
    raise SystemExit('❌ Bạn chưa upload file nào.')

zip_name = list(uploaded.keys())[0]
if not zip_name.lower().endswith('.zip'):
    raise SystemExit(f'❌ Phải là .zip, bạn upload: {zip_name}')

reset_dir(RAW_AUDIO_DIR)
extract_tmp = WORK_DIR / 'extract_tmp'
reset_dir(extract_tmp)

print(f'📥 Extract {zip_name}...')
with zipfile.ZipFile(zip_name, 'r') as z:
    # Anti path-traversal
    for zi in z.infolist():
        if zi.filename.startswith('/') or '..' in zi.filename:
            raise SystemExit(f'❌ Zip chứa path không an toàn: {zi.filename}')
    z.extractall(extract_tmp)

transcript_files = list(extract_tmp.rglob('transcript.csv'))
if not transcript_files:
    raise SystemExit('❌ Zip thiếu transcript.csv (xem cấu trúc trong markdown)')
transcript_src = transcript_files[0]
audio_src_dir = transcript_src.parent / 'audio'
if not audio_src_dir.exists():
    audio_src_dir = transcript_src.parent

valid_rows: list[tuple[str, str]] = []
invalid_rows: list[tuple[int, str]] = []
total_duration = 0.0

print('🔍 Validate audio files...')
with open(transcript_src, 'r', encoding='utf-8') as f:
    for line_no, line in enumerate(f, 1):
        line = line.strip()
        if not line or '|' not in line:
            continue
        parts = line.split('|', 1)
        if len(parts) != 2:
            invalid_rows.append((line_no, 'format sai')); continue
        fname, text = parts[0].strip(), parts[1].strip()

        audio_path = audio_src_dir / fname
        if not audio_path.exists():
            invalid_rows.append((line_no, f'không tìm thấy {fname}')); continue
        try:
            info = validate_audio_file(audio_path)
        except ValueError as e:
            invalid_rows.append((line_no, str(e))); continue

        if not (3.0 <= info['duration'] <= 15.0):
            invalid_rows.append((line_no, f"duration {info['duration']:.1f}s ngoài 3-15s"))
            continue
        if not text:
            invalid_rows.append((line_no, 'transcript rỗng')); continue

        try:
            ensure_16khz_mono(audio_path, RAW_AUDIO_DIR / fname)
        except Exception as e:
            invalid_rows.append((line_no, f'resample fail: {e}')); continue

        valid_rows.append((fname, text))
        total_duration += info['duration']

# Ghi metadata
metadata_path = DATASET_DIR / 'metadata.csv'
with open(metadata_path, 'w', encoding='utf-8') as f:
    for fname, text in valid_rows:
        f.write(f'{fname}|{text}\n')

# Cleanup
shutil.rmtree(extract_tmp)
Path(zip_name).unlink(missing_ok=True)

banner('✅ Path A data ready')
print(f'   Valid files:    {len(valid_rows)}')
print(f'   Total duration: {total_duration:.1f}s ({total_duration / 60:.1f} phút)')
print(f'   Skipped:        {len(invalid_rows)}')
for ln, reason in invalid_rows[:5]:
    print(f'     line {ln}: {reason}')

if len(valid_rows) < 50:
    print(f'⚠️  Chỉ {len(valid_rows)} file — khuyến nghị ≥200 cho LoRA tốt')
if total_duration < 15 * 60:
    print(f'⚠️  {total_duration / 60:.1f} phút < 15 phút — chất lượng có thể chưa tối ưu')

_state['mode'] = 'lora'
_state['data_ready'] = True
_state['num_samples'] = len(valid_rows)
_state['total_duration_sec'] = total_duration
