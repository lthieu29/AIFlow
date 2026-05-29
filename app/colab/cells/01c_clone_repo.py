"""Cell 1c — Clone VieNeu-TTS repo cho code finetune/."""
import subprocess

from cells._shared import REPO_DIR

if REPO_DIR.exists():
    print('✅ Repo đã có sẵn (skip clone)')
else:
    print('📥 Cloning VieNeu-TTS (~30s)...')
    subprocess.run(
        ['git', 'clone', '--depth=1',
         'https://github.com/pnnbao97/VieNeu-TTS.git', str(REPO_DIR)],
        check=True,
    )
    print('✅ Cloned')
