"""Cell 4h — Release VRAM trước khi load engine test.

Train model + Trainer state giữ ~5-10 GB VRAM. Phải free trước Cell 5
load inference engine, không thì OOM.
"""
import gc

import torch
from IPython import get_ipython

from cells._shared import _state

# Free training artifacts
for key in ('lora_model', 'base_model', 'trainer', 'tokenizer'):
    if key in _state:
        _state.pop(key)

# %run publishes top-level assignments from 04c/04d/04e into the notebook.
shell = get_ipython()
if shell is not None:
    for key in ('model', 'trainer', 'tokenizer'):
        shell.user_ns.pop(key, None)

gc.collect()
if torch.cuda.is_available():
    torch.cuda.empty_cache()
    free, total = torch.cuda.mem_get_info()
    print(f'✅ VRAM freed: {free / 1e9:.1f} / {total / 1e9:.1f} GB available')
else:
    print('✅ Cleanup done')
