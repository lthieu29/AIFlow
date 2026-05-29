# 11 — Custom Voice Training Spec

> **Status**: Draft for review
> **Depends on**: 10-tts-spec (TTSProvider, VieNeuTTSProvider, voice catalog)
> **Used by**: Voice Gallery UI (Phase 5+), pipeline orchestrator
> **Phase mapping**: Phase 5.x — sau khi Phase 3 TTS production-ready và Phase 5 UI có Voice Gallery
> **Notebook artifact**: `colab/train_custom_voice.ipynb`

## Mục đích

Spec 10 đã expose zero-shot voice clone qua `ref_audio` + `ref_text`. Tuy nhiên:

- Zero-shot 3–5s ref → giọng "gần giống" nhưng có drift, prosody không nhất quán giữa các scene
- Mỗi lần synthesize phải re-encode ref → chậm + không deterministic
- Không có cách "lưu" giọng để tái dùng xuyên project; user phải copy/paste ref_audio + ref_text mỗi lần

Spec này định nghĩa 2 path để biến giọng custom thành asset bền vững:

| Path | Khi nào | Output | Effort |
|------|---------|--------|--------|
| **A — LoRA fine-tune** | Có ≥30 phút data sạch, muốn chất lượng tối đa | LoRA adapter ~30–80 MB + voices.json | 1–2 giờ Colab T4 |
| **B — Persistent embedding** | Chỉ có 3–15s ref, dùng nhanh | voices.json ~10 KB | <1 phút local hoặc Colab CPU |

Cả 2 path xuất ra **1 file `.zip` đồng nhất** import được vào AIFlow qua 1 endpoint duy nhất.

## Approach

### Path A — LoRA fine-tune (chính)

VieNeu hỗ trợ LoRA fine-tune qua PEFT (đã verify trong source `finetune/train.py`):
- **Target modules**: `q_proj`, `k_proj`, `v_proj`, `o_proj`, `gate_proj`, `up_proj`, `down_proj` (full attention + MLP)
- **Rank**: 16 (default), alpha 32, dropout 0.05
- **Base model**: `pnnbao-ump/VieNeu-TTS-0.3B` (300M params, LoRA-friendly, bf16 ~9GB VRAM trên T4)
- **Data preprocessing**: 2 stage — `filter_data.py` (loại file <3s/>15s, text rác) → `encode_data.py` (NeuCodec encode → token codes)
- **Inference re-use**: `vieneu.VieNeuTTS.load_lora_adapter(path)` apply lên runtime model

→ AIFlow tích hợp bằng cách lưu adapter folder + load qua `tts._engine.load_lora_adapter()` trước khi synth.

### Path B — Persistent embedding (bonus)

Repo có `create_voices_json.py` — chỉ cần ref_audio 3–10s + ref_text:
1. Load `DistillNeuCodec` → encode_code(audio) → list[int] tokens
2. Pack vào `voices.json` schema (compatible với spec hiện có của VieNeu)
3. Inference time: VieNeuTTS đọc preset → dùng codes như character voice anchor

→ AIFlow tích hợp: ghi voices.json vào runtime preset cache, voice_id = user-defined.

### Vì sao Hybrid

- User Phase 1 (mới dùng AIFlow): chỉ có 1 file mp3 30s podcast của họ → Path B đủ, không cần Colab
- User Phase 2 (production): có 1 giờ recording quiet studio → Path A cho chất lượng pro
- 1 endpoint API + 1 UI form, package format thống nhất → ít cognitive load

## Data requirements

### Path A — LoRA fine-tune

| Tiêu chí | Minimum | Recommended | Maximum useful |
|----------|---------|-------------|----------------|
| Tổng thời lượng | 15 phút | 30–60 phút | 2–4 giờ (sau đó diminishing returns) |
| Số file | 50 | 200–500 | 1500 |
| Độ dài mỗi file | 3–15s | 5–10s sweet spot | — |
| Sample rate input | bất kỳ (auto resample 16kHz) | 22050+ Hz để giữ chi tiết | 48kHz (sau resample về 16kHz) |
| Format | WAV/MP3/M4A | WAV PCM 16-bit mono | — |
| Background noise | < -40 dBFS | Studio quiet < -55 dBFS | — |
| Reverb | Tránh | Phòng thu acoustic treatment | — |
| Diversity | Mọi câu khác nhau | Mix câu hỏi/cảm thán/khẳng định | — |
| Ngôn ngữ | 1 ngôn ngữ | Vi hoặc En | Vi-En code-switch (nâng cao) |

**Metadata bắt buộc**: file `transcript.csv` dạng `filename|text` (không header), text khớp **100%** với audio (kể cả dấu câu).

### Path B — Persistent embedding

| Tiêu chí | Yêu cầu |
|----------|---------|
| Tổng thời lượng | 3–10 giây (chính xác 1 file) |
| Format | WAV mono 16kHz+ (auto resample) |
| Nội dung | 1 câu hoàn chỉnh, đủ phonemes đa dạng |
| Transcript | Bắt buộc, khớp 100% audio |
| Quality | Càng sạch càng tốt; với 3–10s không đủ data để model "smooth out" noise |

### Tip thu âm tốt (cả 2 path)

```
✅ DO
- Phòng yên tĩnh, đóng cửa, có rèm/thảm hấp thụ vọng âm
- Mic condenser USB tầm trung (Blue Yeti, Audio-Technica AT2020) cách miệng 15-20cm
- Pop filter để giảm âm "p", "b" nổ
- Đọc tự nhiên, không gồng giọng
- Mỗi đoạn dừng 0.5s đầu/cuối để dễ split

❌ DON'T
- Không dùng laptop mic / phone mic
- Không edit pitch/EQ trước khi train (model học artifact)
- Không trộn nhiều người nói trong cùng dataset
- Không dùng audio đã compress mạnh (mp3 64kbps)
- Không record giữa quạt/AC/cửa sổ mở
```

## Colab workflow overview

```
┌─────────────────────────────────────────────────────────────┐
│ Bước 1 — Setup                                              │
│ Cài VieNeu-TTS + dependencies, mount Google Drive           │
│ ~5 phút, 1 lần đầu                                          │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│ Bước 2 — Upload data                                        │
│ Path A: Upload .zip chứa audio/ + transcript.csv            │
│ Path B: Upload 1 file audio + paste transcript              │
│ Auto-validate: format, duration, sample rate, transcript    │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│ Bước 3 — Config                                             │
│ - Voice name (kebab-case → voice_id)                        │
│ - Language: vi | en | vi-en                                 │
│ - Gender: male | female | neutral                           │
│ - Mode: LoRA fine-tune | Persistent embedding               │
│ - (LoRA only) Quality: Fast/Standard/High                   │
│ Estimate hiển thị: thời gian, VRAM, output size             │
└──────────────────────┬──────────────────────────────────────┘
                       │
        ┌──────────────┴──────────────┐
        │                             │
┌───────▼────────┐          ┌─────────▼────────┐
│ Path A         │          │ Path B           │
│ Preprocess     │          │ Encode 1 file    │
│ Filter audio   │          │ ref_codes        │
│ NeuCodec encode│          │ ~10s             │
│ ~5 phút        │          └─────────┬────────┘
└───────┬────────┘                    │
        │                             │
┌───────▼────────────────┐            │
│ Bước 4A — Train LoRA   │            │
│ Steps based on quality │            │
│ Checkpoint mỗi 500 step│            │
│ → Drive (resume-safe)  │            │
│ ~15-60 phút T4         │            │
└───────┬────────────────┘            │
        │                             │
        └──────────────┬──────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│ Bước 5 — Test                                               │
│ Nhập câu test, gen audio, play inline                       │
│ Nếu fail: hint hyperparam adjust                            │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│ Bước 6 — Export & Download                                  │
│ Pack thành .zip với cấu trúc chuẩn                          │
│ Download về máy + lưu Drive backup                          │
│ Print hướng dẫn import vào AIFlow                           │
└─────────────────────────────────────────────────────────────┘
```

## Output format

### Package `.zip` chuẩn AIFlow

Cả 2 path xuất ra **cùng schema** để API import xử lý unified:

```
custom_voice_{voice_id}.zip
├── metadata.json                  ← VoiceInfo + AIFlow integration hints
├── voices.json                    ← VieNeu native preset format (codes + ref_text)
├── demo.mp3                       ← 1 câu sample 24kHz mono, ~3-5s
├── README.md                      ← Auto-generated, license + usage
│
├── (Path A only) lora/
│   ├── adapter_model.safetensors  ← ~30-80 MB
│   ├── adapter_config.json        ← PEFT config (r, alpha, target_modules)
│   ├── tokenizer.json             ← Required cho load
│   ├── tokenizer_config.json
│   └── special_tokens_map.json
│
└── (Path A only) training_log.txt ← Loss curve, hyperparams, dataset stats
```

### `metadata.json` schema

```json
{
  "schema_version": "1.0",
  "spec": "aiflow.custom_voice",
  
  "voice_id": "phuong-anh-female",
  "display_name": "Phương Anh",
  "description": "Nữ miền Bắc, ấm, narration phù hợp eclamation/explainer",
  
  "language": "vi",
  "gender": "female",
  
  "approach": "lora_finetune",
  "approach_details": {
    "base_model": "pnnbao-ump/VieNeu-TTS-0.3B",
    "lora_rank": 16,
    "lora_alpha": 32,
    "training_steps": 3000,
    "training_minutes": 28,
    "dataset_total_seconds": 1842,
    "dataset_num_files": 187
  },
  
  "demo": {
    "text": "Xin chào, tôi là Phương Anh, giọng narration cho dự án AIFlow.",
    "file": "demo.mp3"
  },
  
  "license": "personal-use",
  "author": "user-provided",
  "created_at": "2026-05-27T10:30:00+07:00",
  
  "aiflow_compat": {
    "min_aiflow_version": "0.3.0",
    "vieneu_version": ">=2.7.0"
  }
}
```

`approach` field = `"lora_finetune"` | `"persistent_embedding"`. Khi import:
- `lora_finetune` → AIFlow extract `lora/` folder vào `storage/voice_gallery/{voice_id}/lora/`, load qua `engine.load_lora_adapter()`
- `persistent_embedding` → AIFlow chỉ ghi `voices.json` vào runtime preset cache, không cần adapter folder

### Why `.zip`?

- 1 file duy nhất → drag-drop UX dễ
- Có thể bundle nhiều artifact (model + voices + demo + readme + training log)
- Standard format, mọi OS extract được
- Verify integrity bằng checksum trong metadata

### Size budget

| Approach | Size ước tính | Notes |
|----------|---------------|-------|
| Path B (embedding) | ~15 KB | voices.json + 50 KB demo mp3 |
| Path A (LoRA r=16) | ~50 MB | adapter ~30 MB + tokenizer ~15 MB + demo + training_log |
| Path A (LoRA r=32) | ~80 MB | Cao hơn rank cao hơn |

## Integration với AIFlow

### Endpoint mới — bổ sung spec 10

```python
# server/api/routes/tts.py — thêm vào sau /api/tts/voices

@router.post("/api/tts/voices/custom/import")
async def import_custom_voice(
    file: UploadFile,
    request: Request,
):
    """Import custom voice package (.zip).
    
    Body: multipart/form-data với field 'file' = zip
    Response: VoiceInfo của voice mới + status
    """
    # 1. Validate zip + extract vào storage/voice_gallery/{voice_id}/
    # 2. Read metadata.json, validate schema
    # 3. Conflict check: voice_id đã tồn tại?
    #    - 409 nếu có; query param ?overwrite=true để force
    # 4. Theo approach:
    #    - lora_finetune: copy lora/ vào storage/voice_gallery/{voice_id}/lora/
    #                     register trong VoiceRegistry với handler load_lora trước synth
    #    - persistent_embedding: ghi voices.json vào storage/voice_gallery/{voice_id}/voices.json
    #                            register preset code trong VoiceRegistry
    # 5. Save VoiceInfo vào DB Config table key="tts.custom_voices.{voice_id}"
    # 6. Trả về VoiceInfo
    ...


@router.get("/api/tts/voices/custom")
async def list_custom_voices() -> list[VoiceInfo]:
    """List voices user đã import. UI Voice Gallery dùng."""
    ...


@router.delete("/api/tts/voices/custom/{voice_id}")
async def delete_custom_voice(voice_id: str):
    """Xoá voice custom + cleanup storage/voice_gallery/{voice_id}/."""
    ...


@router.get("/api/tts/voices/custom/{voice_id}/demo")
async def get_voice_demo(voice_id: str):
    """Stream demo.mp3 của voice cho UI play preview."""
    ...
```

### `VoiceInfo` model (bổ sung spec 10)

> **REVIEW-02 #12** — Spec 10 §A.1 đã định nghĩa `VoiceInfo(BaseModel)` đầy đủ.
> Spec 11 KHÔNG redefine — chỉ tham chiếu. FastAPI `response_model` cần Pydantic
> `BaseModel` (không nhận `@dataclass`).

```python
# Re-import từ spec 10 — KHÔNG redefine
from server.audio.tts.voice_catalog import VoiceInfo  # Pydantic BaseModel
```

Schema rút gọn (xem spec 10 §A.1 để lấy full):

| Field | Type | Source value khi import |
|-------|------|------------------------|
| `voice_id` | str | metadata.json `voice_id` |
| `label` | str | metadata.json `display_name` |
| `description` | str? | metadata.json `description` |
| `gender` | `male`\|`female`\|`neutral` | metadata.json `gender` |
| `language` | `vi`\|`en`\|`vi-en` | metadata.json `language` |
| `source` | `custom_lora`\|`custom_embedding` | metadata.json `approach` map |
| `is_custom` | bool | luôn True cho voice từ Colab |
| `supported_backends` | list[str] | `supported_backends_for(voice_id, source)` |
| `demo_url` | str? | `/api/tts/voices/{vid}/demo` sau khi auto-gen |
| `created_at` | str? | metadata.json `created_at` |
| `metadata` | dict | `{approach_details: {...}}` |

### `VieNeuTTSProvider.synthesize()` — handle custom voice

```python
# server/audio/tts/vieneu_provider.py — bổ sung _resolve_custom_voice

async def synthesize(self, text, voice, output_path, **kwargs):
    await self._ensure_engine()
    
    voice_info = await self._registry.get(voice)  # VoiceRegistry singleton
    
    # === Bổ sung handle custom voice ===
    if voice_info.source == "custom_lora":
        # Load LoRA adapter (chỉ khi chưa load đúng adapter này)
        target_path = settings.data_dir / "voice_gallery" / voice / "lora"
        if self._current_lora != voice:
            await asyncio.to_thread(
                self._engine.load_lora_adapter, str(target_path)
            )
            self._current_lora = voice
        # Engine load_lora_adapter cũng auto reload voices.json từ folder đó
        voice_data = await asyncio.to_thread(
            self._engine.get_preset_voice, voice_info.metadata.get("preset_key")
        )
    
    elif voice_info.source == "custom_embedding":
        # Voice chỉ là codes prefix, không cần adapter
        if self._current_lora is not None:
            # Đang load LoRA của voice khác → unload về base
            await asyncio.to_thread(self._engine.unload_lora_adapter)
            self._current_lora = None
        # Custom voices.json đã được merge vào engine._preset_voices lúc import
        voice_data = await asyncio.to_thread(
            self._engine.get_preset_voice, voice
        )
    
    else:  # preset hoặc voice clone qua ref_audio
        # ... existing logic ...
        pass
    
    # === End custom voice handling ===
    
    # Continue với engine.infer như cũ
    audio_np = await asyncio.to_thread(
        self._engine.infer, text=text, voice=voice_data, ...
    )
    ...
```

**Quan trọng**: LoRA load/unload tốn ~3–8s và VRAM bouncing. AIFlow phải:
1. Cache `_current_lora` để skip nếu cùng voice
2. Khuyến nghị 1 project = 1 voice (đã đúng theo spec 06 — 1 project 1 voice profile)
3. Pipeline orchestrator gọi synth full_narration 1 lần → load LoRA 1 lần / project

### DB schema — bổ sung spec 02

`Config` table (key-value) đủ cho voice metadata. KHÔNG cần bảng riêng.

```python
# Lưu mỗi custom voice 1 row:
Config(
    key=f"tts.custom_voices.{voice_id}",
    value=json.dumps(voice_info.to_dict())
)
```

Hoặc nếu Phase 5+ user có >50 voices → migrate sang bảng `CustomVoice` riêng.

### File system layout

```
storage/
├── voice_gallery/                          ← Custom voice files (REVIEW-02 #11)
│   ├── phuong-anh-female/
│   │   ├── metadata.json                       ← VoiceInfo
│   │   ├── voices.json                         ← VieNeu preset format
│   │   ├── demo.mp3
│   │   ├── README.md
│   │   ├── lora/                                ← Path A only
│   │   │   ├── adapter_model.safetensors
│   │   │   ├── adapter_config.json
│   │   │   └── tokenizer*.json
│   │   └── training_log.txt                     ← Path A only
│   └── another-voice-id/
│       └── ...
└── ...
```

`storage/voice_gallery/` nằm trong `.gitignore` (PII, có thể dung lượng lớn).

## Acceptance criteria

- [ ] Spec rõ 2 path A/B với decision tree khi nào dùng cái nào
- [ ] Notebook Colab `colab/train_custom_voice.ipynb` chạy end-to-end trên T4 free tier không cần Pro
- [ ] Notebook hỗ trợ cả Path A (LoRA) và Path B (embedding) trong 1 file, user chọn cell tương ứng
- [ ] Output `.zip` schema validate được bằng JSON schema
- [ ] Endpoint `/api/tts/voices/custom/import` accept zip, extract đúng path, register voice mới
- [ ] `VieNeuTTSProvider.synthesize` resolve được custom voice (cả LoRA và embedding) mà không break preset/zero-shot path
- [ ] LoRA caching: cùng project synthesize 5 scene với same voice → load LoRA 1 lần
- [ ] Voice delete cleanup `storage/voice_gallery/{voice_id}/` hoàn toàn
- [ ] License notice trong package: nếu approach=lora_finetune, README ghi rõ adapter Apache 2.0 + base model voices CC BY-NC 4.0
- [ ] Demo file 1 câu sample, render lúc export, embedded vào zip
- [ ] Notebook có error handling thân thiện: traceback raw bị catch, message tiếng Việt rõ ràng

## Phase mapping

| Component | Phase |
|-----------|-------|
| Spec 11 + Colab notebook | 5.0 (sau khi spec 10 implement xong) |
| `/api/tts/voices/custom/*` endpoints | 5.1 |
| `VieNeuTTSProvider` LoRA load/unload integration | 5.1 |
| Voice Gallery UI (upload, list, test, delete) | 5.2 |
| Voice cloning từ in-app upload (Path B in-app, no Colab) | 5.3 |
| Auto-pre-warm voice khi project gen start | 5.3 |

## Open questions

1. **Voice quality scoring**: AIFlow có nên auto-test voice mới import (synth 5 câu chuẩn → user score) trước khi mark "ready"?
2. **Voice sharing**: User có muốn export voice cho user khác không? Cần spec license + privacy disclaimer (giọng PII).
3. **Multi-LoRA stacking**: Có hữu ích khi mix 2 voice không (vd: nhân vật A 70% + B 30%)? Hiện PEFT có hỗ trợ nhưng VieNeu chưa test → defer.
4. **Quantize LoRA**: 30-80 MB cho 1 voice OK; nếu user có 50 voices = 4GB → cần quant int8? Defer Phase 6.
5. **Auto-resume**: Colab disconnect 12h limit. Notebook phải save checkpoint mỗi N steps lên Drive — nếu disconnect, user re-run cell train sẽ resume từ checkpoint cuối. Đã thiết kế.

## References

- VieNeu fine-tune source: `D:/Project/AIFlow/VieNeu-TTS/finetune/` — đã đọc và lift logic
- PEFT LoRA docs: <https://huggingface.co/docs/peft/main/en/conceptual_guides/lora>
- VieNeu voices.json spec: `pnnbao-ump/VieNeu-TTS/blob/main/voices.json`
- Spec 10 — TTS provider interface và VoiceInfo
