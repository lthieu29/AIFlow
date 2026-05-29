"""Cell 4c (Path A) — Load VieNeu-TTS-0.3B base model + tokenizer.

Tách riêng để dễ debug nếu HF download fail. Lần đầu mất 1-3 phút download.
"""
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from cells._shared import BASE_MODEL, RUNTIME, _state, banner, require_state

require_state('mode', 'config')
if _state['mode'] != 'lora':
    raise SystemExit('ℹ️ Mode = embedding — bỏ qua cell này.')

if RUNTIME['type'] != 'gpu':
    raise SystemExit('❌ Cần GPU.')

print(f'📥 Load tokenizer: {BASE_MODEL}')
tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token

print(f'📥 Load base model bf16 (~3 GB)...')
model = AutoModelForCausalLM.from_pretrained(
    BASE_MODEL, dtype=torch.bfloat16, device_map='auto',
)

banner('✅ Base model loaded')
print(f'   Vocab size:    {len(tokenizer)}')
print(f'   Device:        {model.device}')
print(f'   Dtype:         {next(model.parameters()).dtype}')

_state['tokenizer'] = tokenizer
_state['base_model'] = model
