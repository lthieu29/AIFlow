# Colab cells — train_custom_voice

Mỗi file `.py` trong folder này là 1 cell trong notebook
[`../train_custom_voice.ipynb`](../train_custom_voice.ipynb). Notebook chỉ là
vỏ điều phối — logic thực nằm ở đây để dễ edit trong IDE (syntax highlight,
lint, AI complete).

## Nguyên tắc

- **Mỗi file 1 cell**, không import lẫn nhau (trừ `_shared`)
- **State chia sẻ** qua dict global `_state` trong [`_shared.py`](_shared.py)
- **Cell chạy tuần tự** — cell sau giả định cell trước đã chạy thành công
- **Defensive**: cell nào dùng state thì gọi `require_state(...)` để fail-fast với message hữu ích
- **Idempotent khi có thể**: re-run cell setup không phá output của cell sau

## Cấu trúc state

```python
_state = {
    'mode': 'lora' | 'embedding',  # set bởi 02b/02c
    'data_ready': bool,
    'config': {                     # set bởi 03e
        'voice_id': str,
        'display_name': str,
        'description': str,
        'language': str,
        'gender': str,
        'preset_key': str,          # chỉ Path A
        'hyperparams': dict,        # chỉ Path A
        'ref_text': str,            # chỉ Path B
    },
    
    # Path A intermediate
    'num_samples': int,             # set bởi 02b
    'total_duration_sec': float,    # set bởi 02b
    'encoded_path': Path,           # set bởi 04b
    'tokenizer': ...,               # set bởi 04c, free bởi 04h
    'base_model': ...,              # set bởi 04c, free bởi 04h
    'lora_model': ...,              # set bởi 04d, free bởi 04h
    'trainer': ...,                 # set bởi 04e, free bởi 04h
    'lora_dir': Path,               # set bởi 04f
    'training_log_path': Path,
    'train_seconds': float,
    
    # Path B intermediate
    'ref_audio_path': Path,         # set bởi 02c
    'ref_duration_sec': float,
    
    # Common output
    'voices_json_path': Path,       # set bởi 04g (Path A) hoặc 04 (Path B)
    'output_dir': Path,
    
    # Test (Cell 5)
    'engine': ...,                  # set bởi 05a
    'demo_mp3': Path,               # set bởi 05b
    'demo_text': str,
    
    # Export (Cell 6)
    'package_dir': Path,            # set bởi 06a
    'metadata': dict,
    'zip_path': Path,               # set bởi 06b
}
```

## Danh sách cells

### Phần 1 — Setup
| File | Mục đích |
|------|----------|
| `_shared.py` | State + helpers + presets |
| `01a_runtime_detect.py` | Detect GPU/TPU/CPU → RUNTIME |
| `01b_drive_mount.py` | Mount Google Drive |
| `01c_clone_repo.py` | Clone VieNeu-TTS source |
| `01d_install_deps.py` | pip install |
| `01e_setup_paths.py` | Python path + HF cache → Drive |
| `01f_init_state.py` | Tạo work dir + summary |

### Phần 2 — Upload data
| File | Mục đích |
|------|----------|
| `02b_upload_path_a.py` | Path A: upload zip + validate |
| `02c_upload_path_b.py` | Path B: upload 1 file ref |
| `02d_verify_state.py` | Check data_ready trước khi tiếp |

### Phần 3 — Config
| File | Mục đích |
|------|----------|
| `03a_voice_metadata.py` | Widgets cho voice_id, name, language, gender |
| `03b_ref_text_input.py` | (Path B) Widget cho ref_text |
| `03c_quality_preset.py` | (Path A) Dropdown preset GPU-aware |
| `03d_advanced_override.py` | (Path A optional) Sliders override hyperparams |
| `03e_save_config.py` | Validate + collect → `_state['config']` |

### Phần 4 — Train/Encode
| File | Mục đích |
|------|----------|
| `04_path_b_encode.py` | (Path B) Encode 1 ref → voices.json |
| `04a_filter_dataset.py` | (Path A) Chuẩn hoá metadata.csv |
| `04b_encode_dataset.py` | (Path A) NeuCodec encode toàn bộ dataset |
| `04c_load_base_model.py` | (Path A) Load VieNeu-TTS-0.3B + tokenizer |
| `04d_setup_lora.py` | (Path A) Apply PEFT LoRA adapter |
| `04e_train_loop.py` | (Path A) Trainer.train() + Drive checkpoint |
| `04f_save_adapter.py` | (Path A) Save adapter_model.safetensors |
| `04g_build_voices_json.py` | (Path A) Voices.json từ sample đại diện |
| `04h_cleanup_vram.py` | Free training artifacts trước test |

### Phần 5 — Test
| File | Mục đích |
|------|----------|
| `05a_load_engine.py` | Load VieNeu engine + apply LoRA nếu có |
| `05b_test_synthesis.py` | Widget gen sample + play inline |

### Phần 6 — Export
| File | Mục đích |
|------|----------|
| `06a_build_metadata.py` | metadata.json + README |
| `06b_pack_zip.py` | Copy artifacts + zip + Drive backup |
| `06c_download_export.py` | Trigger download + in hướng dẫn |

## Edit workflow

1. Mở file `.py` cần sửa trong VS Code/Cursor
2. Sửa trực tiếp — IDE highlight Python syntax, lint imports, type check (mypy)
3. Push lên GitHub
4. Trong notebook Colab: chạy lại cell setup notebook đầu tiên (clone repo) →
   chạy lại cell `%run cells/XX_name.py` cần test
5. Repeat

## Test local (không cần Colab)

Vài cell có thể test offline trước khi push lên Colab. Ví dụ:

```bash
cd app/colab
python -m pytest cells/test_runtime_detect.py  # nếu viết test
```

Hoặc chạy thẳng (chú ý cell có `from google.colab import files` sẽ fail local):

```bash
python cells/_shared.py  # chỉ load module, không lỗi gì
```

## Convention naming

- `NN_name.py` — N là số phần (1-6), `name` snake_case mô tả ngắn
- `NN[a-z]_name.py` — sub-cell trong cùng phần, theo thứ tự alphabet
- File `.py` chạy được standalone qua `%run` — KHÔNG có `def main()` wrapper
- Logic phức tạp → wrap function trong file đó, gọi luôn ở module level
