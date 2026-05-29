"""Cell 2c — Path B: Upload 1 file ref audio cho persistent embedding."""
from pathlib import Path

from google.colab import files

from cells._shared import (
    WORK_DIR,
    _state,
    banner,
    ensure_16khz_mono,
    validate_audio_file,
)

print('🎙️ Path B — Upload 1 file audio (3-10s)')
uploaded = files.upload()
if not uploaded:
    raise SystemExit('❌ Bạn chưa upload file nào.')

audio_name = list(uploaded.keys())[0]
audio_path = Path(audio_name)

info = validate_audio_file(audio_path)
if not (2.0 <= info['duration'] <= 15.0):
    raise SystemExit(f'❌ Duration {info["duration"]:.1f}s ngoài 3-10s. Sửa file rồi upload lại.')

ref_path = WORK_DIR / 'ref.wav'
converted = ensure_16khz_mono(audio_path, ref_path)

banner('✅ Path B data ready')
print(f'   Duration:   {info["duration"]:.1f}s')
print(f'   Sample rate: {info["sample_rate"]}Hz → 16000Hz')
print(f'   Channels:    {info["channels"]} → mono')
if converted:
    print('   ℹ️ Auto-converted')

print('\n👉 Cell 3b sẽ paste transcript chính xác')

Path(audio_name).unlink(missing_ok=True)
_state['mode'] = 'embedding'
_state['data_ready'] = True
_state['ref_audio_path'] = ref_path
_state['ref_duration_sec'] = info['duration']
