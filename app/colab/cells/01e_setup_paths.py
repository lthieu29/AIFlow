"""Cell 1e — Setup Python path + HF cache.

HF cache → Drive để model VieNeu (~3-4 GB) survive session restart.
"""
import os
import sys
from pathlib import Path

import cells._shared as shared

sys.path.insert(0, str(shared.REPO_DIR / 'src'))
sys.path.insert(0, str(shared.REPO_DIR))
os.chdir(shared.REPO_DIR)

if shared.DRIVE_DIR is None:
    raise SystemExit('❌ Chạy Cell 1b (mount drive) trước.')

os.environ['HF_HOME'] = str(shared.DRIVE_DIR / 'hf_cache')
Path(os.environ['HF_HOME']).mkdir(parents=True, exist_ok=True)

print(f'✅ Python path: {shared.REPO_DIR}/src')
print(f'✅ HF cache:    {os.environ["HF_HOME"]}')
