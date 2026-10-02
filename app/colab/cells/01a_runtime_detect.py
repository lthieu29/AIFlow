"""Cell 1a — Detect GPU/TPU/CPU runtime.

Ghi vào RUNTIME dict để Cell 3c auto-suggest preset đúng GPU.
"""
from cells._shared import RUNTIME
import os
import subprocess

try:
    out = subprocess.check_output(
        ['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv,noheader,nounits']
    ).decode().strip()
    name, mem_mb = [x.strip() for x in out.split(',')]
    vram_gb = int(mem_mb) // 1024

    name_l = name.lower()
    if 'h100' in name_l:                       tier = 'h100'
    elif 'a100' in name_l and vram_gb >= 70:   tier = 'a100_80'
    elif 'a100' in name_l:                     tier = 'a100_40'
    elif 'l4' in name_l:                       tier = 'l4'
    elif 't4' in name_l:                       tier = 't4'
    else:                                      tier = 'gpu_other'

    RUNTIME.update({
        'type': 'gpu',
        'name': name,
        'vram_gb': vram_gb,
        'tier': tier,
        'is_pro': tier in ('l4', 'a100_40', 'a100_80', 'h100'),
    })
    print(f'✅ GPU: {name} ({vram_gb} GB VRAM) → tier={tier}')
    if RUNTIME['is_pro']:
        print('   🚀 Colab Pro GPU — sẽ dùng preset accelerated')

except FileNotFoundError:
    if 'COLAB_TPU_ADDR' in os.environ:
        RUNTIME.update({'type': 'tpu', 'tier': 'tpu'})
        print('⚠️ TPU detected — VieNeu-TTS không hỗ trợ TPU.')
        print('   Switch: Runtime → Change runtime type → T4/L4/A100')
    else:
        RUNTIME.update({'type': 'cpu', 'tier': 'cpu'})
        print('⚠️ Không có GPU — chỉ Path B (embedding) chạy được.')
        print('   Cho Path A train: Runtime → Change runtime type → T4 GPU')

print(f'\nRUNTIME = {RUNTIME}')
