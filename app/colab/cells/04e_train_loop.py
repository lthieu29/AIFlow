"""Cell 4e (Path A) — Train LoRA với checkpoint Drive (resume-safe).

Trainer auto resume từ checkpoint mới nhất trên Drive nếu có. Mất 5-60 phút
tuỳ GPU và preset.
"""
import json
import hashlib
import time
from pathlib import Path

import torch
from torch.utils.data import Dataset
from transformers import Trainer, TrainingArguments, default_data_collator

from cells._shared import (
    BASE_MODEL,
    DRIVE_DIR,
    WORK_DIR,
    _state,
    banner,
    require_state,
)

require_state('mode', 'data_ready', 'config', 'lora_model', 'tokenizer', 'encoded_path')
if _state['mode'] != 'lora':
    raise SystemExit('ℹ️ Path B — bỏ qua.')

cfg = _state['config']
hp = cfg['hyperparams']
voice_id = cfg['voice_id']

# --------------------------------------------------------------------
# Dataset class
# --------------------------------------------------------------------
def _preprocess(sample, tokenizer, max_len=2048):
    speech_gen_start = tokenizer.convert_tokens_to_ids('<|SPEECH_GENERATION_START|>')
    codes_str = ''.join([f'<|speech_{i}|>' for i in sample['codes']])
    chat = (
        f"<|TEXT_PROMPT_START|>{sample['phones']}<|TEXT_PROMPT_END|>"
        f"<|SPEECH_GENERATION_START|>{codes_str}<|SPEECH_GENERATION_END|>"
    )
    ids = tokenizer.encode(chat)
    if len(ids) > max_len:
        raise ValueError('Đoạn vượt giới hạn token. Chia audio/transcript rồi mã hóa lại; không cắt nhãn huấn luyện.')
    if len(ids) < max_len:
        ids = ids + [tokenizer.pad_token_id] * (max_len - len(ids))
    input_ids = torch.tensor(ids, dtype=torch.long)
    labels = torch.full_like(input_ids, -100)
    idx = (input_ids == speech_gen_start).nonzero(as_tuple=True)[0]
    if not len(idx):
        raise ValueError('Tokenizer không nhận được token bắt đầu speech; kiểm tra model/tokenizer trước khi train.')
    labels[idx[0]:] = input_ids[idx[0]:]
    attention_mask = (input_ids != tokenizer.pad_token_id).long()
    labels[attention_mask == 0] = -100
    return {'input_ids': input_ids, 'labels': labels, 'attention_mask': attention_mask}


class VoiceDataset(Dataset):
    def __init__(self, csv_path, tokenizer):
        from vieneu_utils.phonemize_text import phonemize_with_dict
        self.samples = []
        self.tokenizer = tokenizer
        self.phonemize = phonemize_with_dict
        with open(csv_path, encoding='utf-8') as f:
            for line in f:
                parts = line.strip().split('|', 2)
                if len(parts) >= 3:
                    self.samples.append({'text': parts[1], 'codes': json.loads(parts[2])})

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, i):
        s = self.samples[i]
        try:
            phones = self.phonemize(s['text'])
        except Exception:
            phones = s['text']
        return _preprocess({'phones': phones, 'codes': s['codes']}, self.tokenizer)


train_ds = VoiceDataset(_state['encoded_path'], _state['tokenizer'])
print(f'✅ Dataset: {len(train_ds)} samples')

# --------------------------------------------------------------------
# Training args
# --------------------------------------------------------------------
drive_ckpt_dir = DRIVE_DIR / voice_id / 'checkpoints'
drive_ckpt_dir.mkdir(parents=True, exist_ok=True)

def _resume_checkpoint(folder, identity):
    existing = list(folder.glob('checkpoint-*'))
    identity_path = folder / 'resume-identity.json'
    if existing:
        try:
            saved = json.loads(identity_path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise RuntimeError('Checkpoint cũ thiếu provenance. Dùng Voice ID khác hoặc xử lý checkpoint thủ công; không tự resume.') from exc
        if saved != identity:
            raise RuntimeError('Dataset, model, cấu hình hoặc precision khác checkpoint. Dùng Voice ID khác hoặc xử lý thủ công; không tự resume.')
        latest = sorted(existing, key=lambda path: int(path.name.split('-')[1]))[-1]
        return str(latest)
    temporary = identity_path.with_suffix('.tmp')
    temporary.write_text(json.dumps(identity, ensure_ascii=False, sort_keys=True), encoding='utf-8')
    temporary.replace(identity_path)
    return None

use_bf16 = torch.cuda.is_bf16_supported(including_emulation=False)
with Path(_state['encoded_path']).open('rb') as encoded:
    dataset_digest = hashlib.file_digest(encoded, 'sha256').hexdigest()
resume_ckpt = _resume_checkpoint(drive_ckpt_dir, {
    'format': 1, 'dataset_sha256': dataset_digest, 'base_model': BASE_MODEL,
    'language': cfg['language'], 'hyperparams': hp, 'max_length': 2048,
    'precision': 'bf16' if use_bf16 else 'fp32',
})

training_args = TrainingArguments(
    output_dir=str(drive_ckpt_dir),
    max_steps=hp['max_steps'],
    per_device_train_batch_size=hp['batch_size'],
    gradient_accumulation_steps=hp['grad_accum'],
    learning_rate=hp['learning_rate'],
    warmup_ratio=hp['warmup_ratio'],
    bf16=use_bf16,
    logging_steps=50,
    save_steps=500,
    save_total_limit=2,
    save_strategy='steps',
    eval_strategy='no',
    report_to='none',
    dataloader_num_workers=2,
    ddp_find_unused_parameters=False,
)

trainer = Trainer(
    model=_state['lora_model'],
    args=training_args,
    train_dataset=train_ds,
    data_collator=default_data_collator,
)

if resume_ckpt:
    print(f'🔄 Resume từ checkpoint đã khớp provenance: {Path(resume_ckpt).name}')

banner(f'🚀 Start training — {hp["max_steps"]} steps')
print(f'   Effective batch: {hp["batch_size"] * hp["grad_accum"]}')
print(f'   LR:              {hp["learning_rate"]}, warmup={hp["warmup_ratio"]}')
print(f'   Checkpoint dir:  {drive_ckpt_dir}')

t0 = time.time()
trainer.train(resume_from_checkpoint=resume_ckpt)
train_seconds = time.time() - t0

banner(f'✅ Training done in {train_seconds / 60:.1f} phút')

_state['trainer'] = trainer
_state['train_seconds'] = train_seconds
