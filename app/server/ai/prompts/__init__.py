"""server.ai.prompts — 4 orthogonal continuity layers for Veo3 prompt synthesis.

Layers
------
Layer 1 — Style Lock      (style_lock.py)
Layer 2 — Asset Lock      (asset_lock.py)
Layer 3 — Scene Chain     (scene_chain.py)
Layer 4 — Audio Continuity (audio_continuity.py)
"""

from server.ai.prompts.asset_lock import AssetAnchor, AssetLock
from server.ai.prompts.audio_continuity import AudioContinuity, AudioPlan
from server.ai.prompts.scene_chain import SceneChain
from server.ai.prompts.style_lock import StyleData, StyleLock

__all__ = [
    # Layer 1
    "StyleLock",
    "StyleData",
    # Layer 2
    "AssetLock",
    "AssetAnchor",
    # Layer 3
    "SceneChain",
    # Layer 4
    "AudioContinuity",
    "AudioPlan",
]
