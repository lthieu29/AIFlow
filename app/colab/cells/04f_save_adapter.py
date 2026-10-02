"""Cell 4f (Path A) — Save LoRA adapter ra work/output/{voice_id}/lora/."""
from pathlib import Path

from cells._shared import WORK_DIR, _state, banner, require_state

require_state('mode', 'config', 'lora_model', 'tokenizer')
if _state['mode'] != 'lora':
    raise SystemExit('ℹ️ Path B — bỏ qua.')

cfg = _state['config']
voice_id = cfg['voice_id']
output_dir = WORK_DIR / 'output' / voice_id
lora_dir = output_dir / 'lora'
lora_dir.mkdir(parents=True, exist_ok=True)

print(f'💾 Save adapter → {lora_dir}')
_state['lora_model'].save_pretrained(str(lora_dir))
_state['tokenizer'].save_pretrained(str(lora_dir))

# Save training log
log_path = output_dir / 'training_log.txt'
hp = cfg['hyperparams']
log_path.write_text(
    f'voice_id:           {voice_id}\n'
    f'base_model:         pnnbao-ump/VieNeu-TTS-0.3B\n'
    f'preset:             {cfg.get("preset_key", "?")}\n'
    f'samples:            {_state.get("num_train_samples", "?")}\n'
    f'total_audio_sec:    {_state.get("total_duration_sec", 0):.1f}\n'
    f'max_steps:          {hp["max_steps"]}\n'
    f'batch_size:         {hp["batch_size"]} × accum {hp["grad_accum"]} = {hp["batch_size"] * hp["grad_accum"]}\n'
    f'learning_rate:      {hp["learning_rate"]}\n'
    f'warmup_ratio:       {hp["warmup_ratio"]}\n'
    f'lora_r:             {hp["lora_r"]}\n'
    f'lora_alpha:         {hp["lora_alpha"]}\n'
    f'lora_dropout:       {hp["lora_dropout"]}\n'
    f'train_time_sec:     {_state.get("train_seconds", 0):.1f}\n',
    encoding='utf-8',
)

banner('✅ Adapter saved')
print(f'   lora_dir:  {lora_dir}')
print(f'   log:       {log_path}')

_state['lora_dir'] = lora_dir
_state['output_dir'] = output_dir
_state['training_log_path'] = log_path
