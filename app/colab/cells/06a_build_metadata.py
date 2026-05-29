"""Cell 6a — Build metadata.json + README cho package zip.

Chuẩn theo schema spec 11 (aiflow.custom_voice).
"""
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from cells._shared import WORK_DIR, _state, banner, require_state

require_state('mode', 'config', 'voices_json_path')

cfg = _state['config']
voice_id = cfg['voice_id']
PACKAGE_DIR = WORK_DIR / 'package' / voice_id

if PACKAGE_DIR.exists():
    shutil.rmtree(PACKAGE_DIR)
PACKAGE_DIR.mkdir(parents=True)

approach = 'lora_finetune' if _state['mode'] == 'lora' else 'persistent_embedding'
now = datetime.now(timezone.utc).isoformat()

metadata = {
    'schema_version': '1.0',
    'spec': 'aiflow.custom_voice',
    'voice_id': voice_id,
    'display_name': cfg['display_name'],
    'description': cfg['description'],
    'language': cfg['language'],
    'gender': cfg['gender'],
    'approach': approach,
    'demo': {
        'text': _state.get('demo_text', ''),
        'file': 'demo.mp3',
    },
    'license': 'personal-use',
    'author': 'user-provided',
    'created_at': now,
    'aiflow_compat': {
        'min_aiflow_version': '0.3.0',
        'vieneu_version': '>=2.7.0',
    },
}

if approach == 'lora_finetune':
    hp = cfg.get('hyperparams', {})
    metadata['approach_details'] = {
        'base_model': 'pnnbao-ump/VieNeu-TTS-0.3B',
        'preset': cfg.get('preset_key'),
        'lora_rank': hp.get('lora_r'),
        'lora_alpha': hp.get('lora_alpha'),
        'training_steps': hp.get('max_steps'),
        'effective_batch_size': hp.get('batch_size', 1) * hp.get('grad_accum', 1),
        'learning_rate': hp.get('learning_rate'),
        'dataset_total_seconds': round(_state.get('total_duration_sec', 0), 1),
        'dataset_num_files': _state.get('num_train_samples', 0),
        'train_time_seconds': round(_state.get('train_seconds', 0), 1),
    }
else:
    metadata['approach_details'] = {
        'ref_audio_seconds': round(_state.get('ref_duration_sec', 0), 1),
        'ref_text': cfg.get('ref_text', ''),
    }

(PACKAGE_DIR / 'metadata.json').write_text(
    json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8',
)

# README
readme = (
    f"# Custom Voice: {cfg['display_name']}\n\n"
    f"- **Voice ID**: `{voice_id}`\n"
    f"- **Approach**: {approach}\n"
    f"- **Language**: {cfg['language']}\n"
    f"- **Gender**: {cfg['gender']}\n"
    f"- **Created**: {now}\n\n"
    f"## Description\n\n{cfg['description']}\n\n"
    f"## Import vào AIFlow\n\n"
    f"1. Mở AIFlow → Voice Gallery → Import Custom Voice\n"
    f"2. Kéo file zip này vào\n"
    f"3. Voice mới xuất hiện trong dropdown TTS\n\n"
    f"Hoặc CLI:\n"
    f"```\n"
    f"curl -X POST http://127.0.0.1:8101/api/tts/voices/custom/import \\\n"
    f"     -F \"file=@custom_voice_{voice_id}.zip\"\n"
    f"```\n\n"
    f"## License\n\n"
    f"- LoRA adapter (nếu có): Apache 2.0 (kế thừa VieNeu-TTS)\n"
    f"- Voice content: personal-use only\n"
    f"- Base model voices.json: CC BY-NC 4.0 (pnnbao-ump)\n"
)
(PACKAGE_DIR / 'README.md').write_text(readme, encoding='utf-8')

banner('✅ metadata.json + README built')
print(f'   Package dir: {PACKAGE_DIR}')

_state['package_dir'] = PACKAGE_DIR
_state['metadata'] = metadata
