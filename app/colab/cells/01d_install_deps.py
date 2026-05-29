"""Cell 1d — Install pip dependencies.

~3-5 phút lần đầu. Chạy lại nhanh do pip cache.
"""
import subprocess

PIP_PACKAGES = [
    'sea-g2p>=0.7.5',
    'soundfile',
    'librosa>=0.11.0',
    'tqdm',
    'PyYAML',
    'transformers>=4.40',
    'accelerate',
    'peft>=0.10',
    'datasets',
    'neucodec>=0.0.4',
    'huggingface_hub',
    'ipywidgets',
]

print('📦 Installing dependencies...')
subprocess.run(['pip', 'install', '-q'] + PIP_PACKAGES, check=True)

# vieneu SDK — không kéo gradio nặng
subprocess.run(['pip', 'install', '-q', 'vieneu', '--no-deps'], check=False)

print('✅ Dependencies ready')
