"""Cell 6c — Download zip về máy + in hướng dẫn import."""
from google.colab import files

from cells._shared import _state, banner, require_state

require_state('config', 'zip_path')

cfg = _state['config']
zip_path = _state['zip_path']

print('📥 Đang download về máy bạn...')
files.download(str(zip_path))

banner('🎉 HOÀN TẤT!')
print()
print('Cách import vào AIFlow:')
print(f'  1. Mở AIFlow → Voice Gallery → Import Custom Voice')
print(f'  2. Kéo file {zip_path.name} vào')
print(f'  3. Voice ID "{cfg["voice_id"]}" sẽ xuất hiện trong dropdown TTS')
print()
print('Hoặc qua CLI:')
print(f'  curl -X POST http://127.0.0.1:8101/api/tts/voices/custom/import \\')
print(f'       -F "file=@{zip_path.name}"')
print()
print('Backup: file đã lưu trên Drive `MyDrive/aiflow_voices/`.')
