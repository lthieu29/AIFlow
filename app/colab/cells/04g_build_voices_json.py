"""Cell 4g (Path A) — Build voices.json từ 1 sample đại diện trong dataset.

VieNeu cần voices.json có codes prefix để inference (ngay cả với LoRA model).
Chọn sample đầu tiên trong encoded dataset làm anchor.
"""
import json

from cells._shared import _state, banner, require_state

require_state('mode', 'config', 'encoded_path', 'lora_dir')
if _state['mode'] != 'lora':
    raise SystemExit('ℹ️ Path B — bỏ qua.')

cfg = _state['config']
voice_id = cfg['voice_id']

print('🎙️ Build voices.json từ sample đại diện...')
with open(_state['encoded_path'], encoding='utf-8') as f:
    first_line = f.readline().strip()
fname, text, codes_json = first_line.split('|', 2)
sample_codes = json.loads(codes_json)

voices_json = {
    'meta': {
        'spec': 'vieneu.voice.presets',
        'spec_version': '1.0',
        'engine': 'VieNeu-TTS',
        'license': 'personal-use',
    },
    'default_voice': voice_id,
    'presets': {
        voice_id: {
            'codes': sample_codes,
            'text': text,
            'description': cfg['description'],
        }
    },
}

# Ghi vào lora_dir để engine.load_lora_adapter tự load
voices_json_path = _state['lora_dir'] / 'voices.json'
with open(voices_json_path, 'w', encoding='utf-8') as f:
    json.dump(voices_json, f, ensure_ascii=False, indent=2)

banner('✅ voices.json built')
print(f'   {voices_json_path}')
print(f'   sample_text: {text[:80]}...')
print(f'   tokens:      {len(sample_codes)}')

_state['voices_json_path'] = voices_json_path
