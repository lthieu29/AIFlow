"""Cell 4b (Path A) — Encode toàn bộ dataset audio thành speech codes.

Dùng NeuCodec (PyTorch) — yêu cầu GPU. Output metadata_encoded.csv format
filename|text|json_codes per dòng.
"""
import gc
import json
from pathlib import Path

import librosa
import torch
from tqdm.auto import tqdm

from cells._shared import (
    DATASET_DIR,
    RAW_AUDIO_DIR,
    RUNTIME,
    _state,
    banner,
    require_state,
)

require_state('mode', 'data_ready')
if _state['mode'] != 'lora':
    raise SystemExit('ℹ️ Mode = embedding — bỏ qua cell này.')

if RUNTIME['type'] != 'gpu':
    raise SystemExit(
        '❌ Encode dataset cần GPU. '
        'Switch: Runtime → Change runtime type → T4 GPU trở lên.'
    )

cleaned_path = DATASET_DIR / 'metadata_cleaned.csv'
encoded_path = DATASET_DIR / 'metadata_encoded.csv'
if not cleaned_path.exists():
    raise SystemExit('❌ Chưa chạy Cell 4a.')

print('📥 Load NeuCodec (~30-60s lần đầu)...')
from neucodec import NeuCodec  # noqa: E402

codec = NeuCodec.from_pretrained('neuphonic/neucodec').to('cuda')
codec.eval()

with open(cleaned_path, encoding='utf-8') as f:
    lines = [l.strip() for l in f if l.strip()]

encoded_lines: list[str] = []
skipped = 0

for line in tqdm(lines, desc='Encoding'):
    parts = line.split('|', 1)
    if len(parts) != 2:
        skipped += 1; continue
    fname, text = parts
    audio_path = RAW_AUDIO_DIR / fname
    if not audio_path.exists():
        skipped += 1; continue
    try:
        wav, _ = librosa.load(str(audio_path), sr=16000, mono=True)
        wav_t = torch.from_numpy(wav).float().unsqueeze(0).unsqueeze(0).to('cuda')
        with torch.no_grad():
            codes = (
                codec.encode_code(wav_t)
                .squeeze(0).squeeze(0)
                .cpu().numpy().flatten().astype(int).tolist()
            )
        if codes and all(0 <= c < 65536 for c in codes):
            encoded_lines.append(f'{fname}|{text}|{json.dumps(codes)}\n')
        else:
            skipped += 1
    except Exception as e:
        print(f'  ⚠️ {fname}: {e}')
        skipped += 1

with open(encoded_path, 'w', encoding='utf-8') as f:
    f.writelines(encoded_lines)

del codec
gc.collect()
torch.cuda.empty_cache()

banner('✅ Encode dataset complete')
print(f'   Encoded: {len(encoded_lines)}')
print(f'   Skipped: {skipped}')
print(f'   Output:  {encoded_path}')

if len(encoded_lines) < 30:
    raise SystemExit(
        f'❌ Chỉ {len(encoded_lines)} sample — không đủ train. '
        'Cần ≥30. Quay lại Cell 2b upload data nhiều hơn.'
    )

_state['encoded_path'] = encoded_path
_state['num_train_samples'] = len(encoded_lines)
