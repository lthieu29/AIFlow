"""Cell 1b — Mount Google Drive.

Drive lưu HF cache + checkpoint train (resume khi disconnect) + backup output.
"""
from pathlib import Path

import cells._shared as shared
from google.colab import drive

drive.mount('/content/drive', force_remount=False)

shared.DRIVE_DIR = Path('/content/drive/MyDrive/aiflow_voices')
shared.DRIVE_DIR.mkdir(parents=True, exist_ok=True)

print(f'✅ Drive mount: {shared.DRIVE_DIR}')
