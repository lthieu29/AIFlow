"""Cell 4d (Path A) — Apply LoRA adapter lên base model."""
from peft import LoraConfig, TaskType, get_peft_model

from cells._shared import _state, banner, require_state

require_state('mode', 'config', 'base_model')
if _state['mode'] != 'lora':
    raise SystemExit('ℹ️ Path B — bỏ qua.')

cfg = _state['config']
hp = cfg['hyperparams']

lora_config = LoraConfig(
    r=hp['lora_r'],
    lora_alpha=hp['lora_alpha'],
    target_modules=[
        'q_proj', 'k_proj', 'v_proj', 'o_proj',
        'gate_proj', 'up_proj', 'down_proj',
    ],
    lora_dropout=hp['lora_dropout'],
    bias='none',
    task_type=TaskType.CAUSAL_LM,
)

model = get_peft_model(_state['base_model'], lora_config)

banner('✅ LoRA adapter attached')
print(f'   rank (r):     {hp["lora_r"]}')
print(f'   alpha:        {hp["lora_alpha"]}')
print(f'   dropout:      {hp["lora_dropout"]}')
print(f'   target_modules: q/k/v/o + gate/up/down (full attn + MLP)\n')
model.print_trainable_parameters()

_state['lora_model'] = model
