"""Shared state + helpers cho mọi cell file.

Mỗi cell file `%run` lại module này (Colab tự cache module nên import nhanh).
Tất cả cell đọc/ghi qua dict `_state` global để pass data giữa cells.

KHÔNG đặt logic train/encode ở đây — chỉ helper + state container.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import soundfile as sf

# --------------------------------------------------------------------
# Global state — share giữa các cell
# --------------------------------------------------------------------
RUNTIME: dict[str, Any] = {
    'type': 'unknown',          # 'gpu' | 'tpu' | 'cpu' | 'unknown'
    'name': 'unknown',
    'vram_gb': 0,
    'tier': 'cpu',              # 't4' | 'l4' | 'a100_40' | 'a100_80' | 'h100' | ...
    'is_pro': False,
}

_state: dict[str, Any] = {
    'mode': None,               # 'lora' | 'embedding'
    'data_ready': False,
    'config': None,
    'preset': None,
    'engine': None,             # cached VieNeu engine
}

# Path constants
WORK_DIR = Path('/content/work')
DATASET_DIR = WORK_DIR / 'dataset'
RAW_AUDIO_DIR = DATASET_DIR / 'raw_audio'
REPO_DIR = Path('/content/VieNeu-TTS')

# Drive paths — set bởi cell 01b sau khi mount
DRIVE_DIR: Path | None = None

# Model defaults
BASE_MODEL = 'pnnbao-ump/VieNeu-TTS-0.3B'

# Demo template cho cell 5
DEMO_TEXT_TEMPLATE = (
    'Xin chào, tôi là {name}. Đây là ví dụ giọng đọc của tôi '
    'được tạo bằng AIFlow.'
)


# --------------------------------------------------------------------
# Audio helpers (dùng trong cell 02a, 02b, 02c)
# --------------------------------------------------------------------
def validate_audio_file(path: Path) -> dict[str, Any]:
    """Trả info file. Raise ValueError nếu invalid."""
    try:
        info = sf.info(str(path))
    except Exception as e:
        raise ValueError(f'Không đọc được audio: {e}') from e
    return {
        'duration': info.duration,
        'sample_rate': info.samplerate,
        'channels': info.channels,
        'format': info.format,
    }


def ensure_16khz_mono(in_path: Path, out_path: Path) -> bool:
    """Resample về 16kHz mono cho NeuCodec encoding.
    Return True nếu đã convert, False nếu chỉ copy.
    """
    info = validate_audio_file(in_path)
    needs = info['sample_rate'] != 16000 or info['channels'] != 1
    if needs:
        import librosa
        wav, _ = librosa.load(str(in_path), sr=16000, mono=True)
        sf.write(str(out_path), wav, 16000, subtype='PCM_16')
    elif in_path != out_path:
        shutil.copy(str(in_path), str(out_path))
    return needs


def reset_dir(path: Path) -> None:
    """Xoá rồi tạo lại thư mục."""
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------
# Voice id validate (dùng trong 03e)
# --------------------------------------------------------------------
def validate_voice_id(vid: str) -> tuple[bool, str]:
    import re
    if not vid:
        return False, 'Voice ID rỗng'
    if not re.match(r'^[a-z][a-z0-9-]{1,40}$', vid):
        return False, 'Voice ID phải kebab-case, vd: phuong-anh-female'
    return True, ''


# --------------------------------------------------------------------
# Hyperparam presets (dùng trong 03c)
# --------------------------------------------------------------------
PRESETS: dict[str, dict[str, Any]] = {
    'quick_test': {
        'label': 'Quick Test (1000 steps)',
        'batch_size': 2, 'grad_accum': 1, 'max_steps': 1000,
        'learning_rate': 2e-4, 'warmup_ratio': 0.05,
        'lora_r': 16, 'lora_alpha': 32, 'lora_dropout': 0.05,
        'min_vram_gb': 8,
        'desc': 'Smoke test pipeline (~5 phút). Output không production-ready.',
    },
    'conservative': {
        'label': 'Conservative (T4 free, 3000 steps)',
        'batch_size': 2, 'grad_accum': 1, 'max_steps': 3000,
        'learning_rate': 2e-4, 'warmup_ratio': 0.05,
        'lora_r': 16, 'lora_alpha': 32, 'lora_dropout': 0.05,
        'min_vram_gb': 12,
        'desc': 'T4 free tier (15 GB VRAM). ~25-30 phút.',
    },
    'balanced': {
        'label': 'Balanced (L4 Pro, 4000 steps)',
        'batch_size': 4, 'grad_accum': 1, 'max_steps': 4000,
        'learning_rate': 2e-4, 'warmup_ratio': 0.05,
        'lora_r': 16, 'lora_alpha': 32, 'lora_dropout': 0.05,
        'min_vram_gb': 20,
        'desc': 'L4 22 GB Pro. ~12-15 phút. Effective batch=4.',
    },
    'fast': {
        'label': 'Fast (A100 40GB, 5000 steps)',
        'batch_size': 8, 'grad_accum': 1, 'max_steps': 5000,
        'learning_rate': 3e-4, 'warmup_ratio': 0.03,
        'lora_r': 16, 'lora_alpha': 32, 'lora_dropout': 0.05,
        'min_vram_gb': 35,
        'desc': 'A100 40GB Pro. ~5-8 phút. Effective batch=8 + LR cao hơn.',
    },
    'very_fast': {
        'label': 'Very Fast (A100 80GB / H100, 6000 steps)',
        'batch_size': 16, 'grad_accum': 1, 'max_steps': 6000,
        'learning_rate': 3e-4, 'warmup_ratio': 0.03,
        'lora_r': 32, 'lora_alpha': 64, 'lora_dropout': 0.05,
        'min_vram_gb': 70,
        'desc': 'A100 80GB / H100 Pro+. ~3-5 phút. Effective batch=16, rank=32.',
    },
    'advanced': {
        'label': '⚙️ Advanced (override thủ công)',
        'batch_size': 4, 'grad_accum': 1, 'max_steps': 4000,
        'learning_rate': 2e-4, 'warmup_ratio': 0.05,
        'lora_r': 16, 'lora_alpha': 32, 'lora_dropout': 0.05,
        'min_vram_gb': 0,
        'desc': 'Tự chỉnh từng hyperparam ở Cell 3d.',
    },
}

# Map GPU tier → preset đề xuất (dùng trong 03c để auto-suggest)
TIER_TO_PRESET: dict[str, str] = {
    'cpu':       'quick_test',   # Path A không train được trên CPU thực tế
    't4':        'conservative',
    'l4':        'balanced',
    'a100_40':   'fast',
    'a100_80':   'very_fast',
    'h100':      'very_fast',
    'gpu_other': 'conservative',
}


# --------------------------------------------------------------------
# Print helpers
# --------------------------------------------------------------------
def banner(title: str, char: str = '=', width: int = 60) -> None:
    print()
    print(char * width)
    print(title)
    print(char * width)


def require_state(*keys: str) -> None:
    """Raise SystemExit nếu state thiếu key — giúp cell sau bảo vệ chính nó."""
    missing = [k for k in keys if not _state.get(k)]
    if missing:
        raise SystemExit(
            f'❌ Cell trước chưa chạy hoặc state bị reset: thiếu {missing}. '
            f'Quay lại chạy lần lượt từ Cell 1a.'
        )
