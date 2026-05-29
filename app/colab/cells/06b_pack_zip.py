"""Cell 6b — Copy artifact + zip + Drive backup."""
import shutil
import zipfile

from cells._shared import DRIVE_DIR, WORK_DIR, _state, banner, require_state

require_state('mode', 'config', 'package_dir', 'voices_json_path')

cfg = _state['config']
voice_id = cfg['voice_id']
PACKAGE_DIR = _state['package_dir']

# Copy voices.json
shutil.copy(str(_state['voices_json_path']), str(PACKAGE_DIR / 'voices.json'))

# Copy demo.mp3 nếu có
if _state.get('demo_mp3') and _state['demo_mp3'].exists():
    shutil.copy(str(_state['demo_mp3']), str(PACKAGE_DIR / 'demo.mp3'))
else:
    print('⚠️  Chưa có demo.mp3 (Cell 5b chưa chạy). Package vẫn import được nhưng không có preview.')

# Copy LoRA folder nếu Path A
if _state['mode'] == 'lora':
    lora_dest = PACKAGE_DIR / 'lora'
    shutil.copytree(str(_state['lora_dir']), str(lora_dest))
    # Xoá voices.json trong lora/ để tránh nhầm với root voices.json
    (lora_dest / 'voices.json').unlink(missing_ok=True)
    if _state.get('training_log_path'):
        shutil.copy(str(_state['training_log_path']), str(PACKAGE_DIR / 'training_log.txt'))

# Build zip
zip_path = WORK_DIR / f'custom_voice_{voice_id}.zip'
if zip_path.exists():
    zip_path.unlink()

with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
    for item in PACKAGE_DIR.rglob('*'):
        if item.is_file():
            zf.write(item, item.relative_to(PACKAGE_DIR))

size_mb = zip_path.stat().st_size / (1024 * 1024)

# Drive backup
drive_backup = DRIVE_DIR / zip_path.name
shutil.copy(str(zip_path), str(drive_backup))

banner('✅ Zip built + backed up')
print(f'   File:         {zip_path.name}')
print(f'   Size:         {size_mb:.2f} MB')
print(f'   Approach:     {_state["mode"]}')
print(f'   Drive backup: {drive_backup}')

_state['zip_path'] = zip_path
