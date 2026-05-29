"""Cell 4 (Path B) — Encode ref audio thành speech codes.

Chỉ chạy nếu mode='embedding'. Output: voices.json trong work/output/.
"""
import gc
import json
from pathlib import Path

import librosa
import torch

from cells._shared import _state, banner, require_state, WORK_DIR

require_state('mode', 'data_ready', 'config')
if _state['mode'] != 'embedding':
    raise SystemExit('ℹ️ Mode = lora — bỏ qua cell này, chạy 04a→04g thay vì cell này.')

cfg = _state['config']
voice_id = cfg['voice_id']
output_dir = WORK_DIR / 'output' / voice_id
output_dir.mkdir(parents=True, exist_ok=True)

banner('🎙️ Path B — Encoding ref audio → preset codes')

print('📥 Load DistillNeuCodec (~30s lần đầu)...')
from neucodec import DistillNeuCodec  # noqa: E402

device = 'cuda' if torch.cuda.is_available() else 'cpu'
codec = DistillNeuCodec.from_pretrained('neuphonic/distill-neucodec').to(device)
codec.eval()

print(f'🎙️ Encode {_state["ref_audio_path"]}...')
wav, _ = librosa.load(str(_state['ref_audio_path']), sr=16000, mono=True)
wav_tensor = torch.from_numpy(wav).float().unsqueeze(0).unsqueeze(0).to(device)

with torch.no_grad():
    ref_codes = codec.encode_code(audio_or_path=wav_tensor).squeeze(0).squeeze(0)

codes_list = ref_codes.cpu().numpy().flatten().astype(int).tolist()

voices_json = {
    'meta': {
        'spec': 'vieneu.voice.presets',
        'spec_version': '1.0',
        'engine': 'VieNeu-TTS',
        'license': 'personal-use',
        'notice': 'Custom voice — user provided audio',
    },
    'default_voice': voice_id,
    'presets': {
        voice_id: {
            'codes': codes_list,
            'text': cfg['ref_text'],
            'description': cfg['description'],
        }
    },
}

voices_json_path = output_dir / 'voices.json'
with open(voices_json_path, 'w', encoding='utf-8') as f:
    json.dump(voices_json, f, ensure_ascii=False, indent=2)

# Free codec
del codec, wav_tensor, ref_codes
gc.collect()
if torch.cuda.is_available():
    torch.cuda.empty_cache()

banner(f'✅ Encoded {len(codes_list)} tokens')
print(f'   voices.json: {voices_json_path}')

_state['voices_json_path'] = voices_json_path
_state['lora_dir'] = None
_state['output_dir'] = output_dir
print('\nNext: Cell 5 — test synthesis')
