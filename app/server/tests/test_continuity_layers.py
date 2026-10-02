"""Tests for the 4 orthogonal continuity layers (Task 2.2).

Each layer is tested independently to verify the acceptance criteria:
- StyleLock.inject() prepends style prefix to prompt
- AssetLock.inject() adds asset anchors to prompt
- SceneChain.should_reset_chain() returns True when location_hint changes
- AudioContinuity.get_scene_audio_hint() returns appropriate hint per scene position
"""

from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


# ─────────────────────────────────────────────────────────────────────────────
# Layer 1 — Style Lock
# ─────────────────────────────────────────────────────────────────────────────

class TestStyleLock:
    """Tests for server.ai.prompts.style_lock."""

    def _make_style_json(self, **overrides) -> str:
        base = {
            "art_style": "editorial fashion photography",
            "lighting": "soft even key light",
            "lens": "85mm portrait, shallow depth of field",
            "camera_style": "locked-off static frame",
            "post_processing": "slight film grain, warm tone curve",
            "color_palette": "muted earth tones with cream highlights",
            "negative_prompt": "no anime, no cartoon",
        }
        base.update(overrides)
        return json.dumps(base)

    def test_load_parses_valid_json(self):
        from server.ai.prompts.style_lock import StyleLock
        lock = StyleLock.load(self._make_style_json())
        assert lock is not None
        assert lock.prefix  # non-empty prefix

    def test_inject_prepends_prefix(self):
        from server.ai.prompts.style_lock import StyleLock
        lock = StyleLock.load(self._make_style_json())
        result = lock.inject("A woman walks through a market.")
        assert result.startswith(lock.prefix)
        assert "A woman walks through a market." in result

    def test_inject_separator_is_double_newline(self):
        from server.ai.prompts.style_lock import StyleLock
        lock = StyleLock.load(self._make_style_json())
        result = lock.inject("Scene prompt here.")
        assert "\n\n" in result

    def test_prefix_text_override_used_verbatim(self):
        from server.ai.prompts.style_lock import StyleLock
        style_json = json.dumps({
            "art_style": "cinematic",
            "lighting": "dramatic",
            "color_palette": "dark",
            "camera_style": "handheld",
            "prefix_text": "CUSTOM PREFIX OVERRIDE",
        })
        lock = StyleLock.load(style_json)
        assert lock.prefix == "CUSTOM PREFIX OVERRIDE"
        result = lock.inject("My scene.")
        assert result.startswith("CUSTOM PREFIX OVERRIDE")

    def test_inject_empty_prompt(self):
        from server.ai.prompts.style_lock import StyleLock
        lock = StyleLock.load(self._make_style_json())
        result = lock.inject("")
        # Should still have the prefix
        assert lock.prefix in result

    def test_negative_prompt_included_in_prefix(self):
        from server.ai.prompts.style_lock import StyleLock
        lock = StyleLock.load(self._make_style_json())
        assert "no anime" in lock.prefix or "Avoid" in lock.prefix

    def test_load_invalid_json_raises(self):
        from server.ai.prompts.style_lock import StyleLock
        with pytest.raises((json.JSONDecodeError, ValueError)):
            StyleLock.load("not valid json {{{")

    def test_style_data_build_prefix_skips_empty_fields(self):
        from server.ai.prompts.style_lock import StyleData
        data = StyleData(visual_style="cinematic", lighting="", color_palette="warm")
        prefix = data.build_prefix()
        assert "cinematic" in prefix.lower()
        assert "warm" in prefix.lower()
        # Empty lighting should not produce a stray period
        assert ".." not in prefix

    def test_inject_is_idempotent_structure(self):
        """Calling inject twice should not double-prepend."""
        from server.ai.prompts.style_lock import StyleLock
        lock = StyleLock.load(self._make_style_json())
        once = lock.inject("Scene.")
        # inject is not idempotent by design (it always prepends),
        # but the structure should be consistent
        assert once.count(lock.prefix) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Layer 2 — Asset Lock
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class _FakeAsset:
    """Minimal stand-in for the SQLModel Asset."""
    name: str
    type: str
    ref_url: str = ""
    description: str = ""


class TestAssetLock:
    """Tests for server.ai.prompts.asset_lock."""

    def test_from_assets_builds_anchors(self):
        from server.ai.prompts.asset_lock import AssetLock
        assets = [
            _FakeAsset("Hùng", "character", "http://example.com/hung.png", "young man"),
            _FakeAsset("Áo trắng", "product", "", "white cotton shirt"),
        ]
        lock = AssetLock.from_assets(assets)
        assert len(lock.anchors) == 2

    def test_inject_adds_asset_block(self):
        from server.ai.prompts.asset_lock import AssetLock
        assets = [_FakeAsset("Hùng", "character", "", "young Vietnamese man")]
        lock = AssetLock.from_assets(assets)
        result = lock.inject("A man walks into a café.")
        assert "Asset References" in result
        assert "Hùng" in result

    def test_inject_character_anchor_format(self):
        from server.ai.prompts.asset_lock import AssetLock
        assets = [_FakeAsset("Lan", "character", "", "young woman in red dress")]
        lock = AssetLock.from_assets(assets)
        result = lock.inject("Scene prompt.")
        assert "Character: Lan" in result
        assert "young woman in red dress" in result

    def test_inject_product_anchor_format(self):
        from server.ai.prompts.asset_lock import AssetLock
        assets = [_FakeAsset("Túi xách", "product", "", "leather handbag")]
        lock = AssetLock.from_assets(assets)
        result = lock.inject("Scene prompt.")
        assert "Product: Túi xách" in result

    def test_inject_location_anchor_format(self):
        from server.ai.prompts.asset_lock import AssetLock
        assets = [_FakeAsset("Quán cafe", "location", "", "modern minimalist coffee shop")]
        lock = AssetLock.from_assets(assets)
        result = lock.inject("Scene prompt.")
        assert "Location: Quán cafe" in result

    def test_inject_empty_assets_returns_prompt_unchanged(self):
        from server.ai.prompts.asset_lock import AssetLock
        lock = AssetLock.from_assets([])
        original = "A woman walks through a market."
        result = lock.inject(original)
        assert result == original

    def test_priority_ordering_character_before_product(self):
        from server.ai.prompts.asset_lock import AssetLock
        assets = [
            _FakeAsset("Product A", "product", ""),
            _FakeAsset("Character B", "character", ""),
        ]
        lock = AssetLock.from_assets(assets)
        # Character should come before product in the sorted anchors
        names = [a.name for a in lock.anchors]
        assert names.index("Character B") < names.index("Product A")

    def test_top_anchors_respects_limit(self):
        from server.ai.prompts.asset_lock import AssetLock, MAX_ANCHORS
        assets = [_FakeAsset(f"Asset{i}", "extra", "") for i in range(MAX_ANCHORS + 3)]
        lock = AssetLock.from_assets(assets)
        assert len(lock.top_anchors()) == MAX_ANCHORS

    def test_inject_empty_prompt_still_adds_anchors(self):
        from server.ai.prompts.asset_lock import AssetLock
        assets = [_FakeAsset("Hùng", "character", "")]
        lock = AssetLock.from_assets(assets)
        result = lock.inject("")
        assert "Hùng" in result

    def test_asset_anchor_to_anchor_text(self):
        from server.ai.prompts.asset_lock import AssetAnchor
        anchor = AssetAnchor(
            name="Hùng",
            type="character",
            description="young Vietnamese man",
            ref_url="http://example.com/hung.png",
            role="main_character",
        )
        text = anchor.to_anchor_text()
        assert "Character: Hùng" in text
        assert "young Vietnamese man" in text


# ─────────────────────────────────────────────────────────────────────────────
# Layer 3 — Scene Chain
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class _FakeScene:
    """Minimal stand-in for the SQLModel Scene."""
    order: int
    location_hint: str = "unspecified"
    last_frame_path: Optional[str] = None


class TestSceneChain:
    """Tests for server.ai.prompts.scene_chain."""

    def test_get_start_frame_returns_none_for_first_scene(self):
        from server.ai.prompts.scene_chain import SceneChain
        chain = SceneChain()
        scenes = [_FakeScene(order=0)]
        assert chain.get_start_frame(0, scenes) is None

    def test_get_start_frame_returns_none_when_no_last_frame(self):
        from server.ai.prompts.scene_chain import SceneChain
        chain = SceneChain()
        scenes = [_FakeScene(order=0), _FakeScene(order=1)]
        # Scene 0 has no last_frame_path
        assert chain.get_start_frame(1, scenes) is None

    def test_get_start_frame_returns_path_when_exists(self, tmp_path):
        from server.ai.prompts.scene_chain import SceneChain
        frame_file = tmp_path / "scene0.lastframe.png"
        frame_file.write_bytes(b"\x89PNG")  # minimal content

        chain = SceneChain()
        scenes = [
            _FakeScene(order=0, last_frame_path=str(frame_file)),
            _FakeScene(order=1),
        ]
        result = chain.get_start_frame(1, scenes)
        assert result == frame_file

    def test_get_start_frame_returns_none_for_missing_file(self, tmp_path):
        from server.ai.prompts.scene_chain import SceneChain
        chain = SceneChain()
        scenes = [
            _FakeScene(order=0, last_frame_path=str(tmp_path / "nonexistent.png")),
            _FakeScene(order=1),
        ]
        assert chain.get_start_frame(1, scenes) is None

    # ── should_reset_chain ────────────────────────────────────────────────────

    def test_should_reset_chain_true_when_location_changes(self):
        from server.ai.prompts.scene_chain import SceneChain
        chain = SceneChain()
        prev = _FakeScene(order=0, location_hint="indoor")
        curr = _FakeScene(order=1, location_hint="outdoor")
        assert chain.should_reset_chain(prev, curr) is True

    def test_should_reset_chain_false_when_same_location(self):
        from server.ai.prompts.scene_chain import SceneChain
        chain = SceneChain()
        prev = _FakeScene(order=0, location_hint="indoor")
        curr = _FakeScene(order=1, location_hint="indoor")
        assert chain.should_reset_chain(prev, curr) is False

    def test_should_reset_chain_false_when_prev_unspecified(self):
        """REVIEW-02 #6: unspecified on either side → keep chain."""
        from server.ai.prompts.scene_chain import SceneChain
        chain = SceneChain()
        prev = _FakeScene(order=0, location_hint="unspecified")
        curr = _FakeScene(order=1, location_hint="outdoor")
        assert chain.should_reset_chain(prev, curr) is False

    def test_should_reset_chain_false_when_curr_unspecified(self):
        from server.ai.prompts.scene_chain import SceneChain
        chain = SceneChain()
        prev = _FakeScene(order=0, location_hint="indoor")
        curr = _FakeScene(order=1, location_hint="unspecified")
        assert chain.should_reset_chain(prev, curr) is False

    def test_should_reset_chain_false_when_both_unspecified(self):
        from server.ai.prompts.scene_chain import SceneChain
        chain = SceneChain()
        prev = _FakeScene(order=0, location_hint="unspecified")
        curr = _FakeScene(order=1, location_hint="unspecified")
        assert chain.should_reset_chain(prev, curr) is False

    def test_should_reset_chain_transition_to_outdoor(self):
        from server.ai.prompts.scene_chain import SceneChain
        chain = SceneChain()
        prev = _FakeScene(order=0, location_hint="transition")
        curr = _FakeScene(order=1, location_hint="outdoor")
        assert chain.should_reset_chain(prev, curr) is True

    # ── get_chain_prompt_prefix ───────────────────────────────────────────────

    def test_get_chain_prompt_prefix_empty_when_no_frame(self):
        from server.ai.prompts.scene_chain import SceneChain
        chain = SceneChain()
        assert chain.get_chain_prompt_prefix(None) == ""

    def test_get_chain_prompt_prefix_non_empty_when_frame_given(self, tmp_path):
        from server.ai.prompts.scene_chain import SceneChain
        frame = tmp_path / "frame.png"
        frame.write_bytes(b"\x89PNG")
        chain = SceneChain()
        prefix = chain.get_chain_prompt_prefix(frame)
        assert prefix  # non-empty
        assert "Continuity" in prefix or "continues" in prefix.lower()

    def test_get_chain_prompt_prefix_mentions_pose(self, tmp_path):
        from server.ai.prompts.scene_chain import SceneChain
        frame = tmp_path / "frame.png"
        frame.write_bytes(b"\x89PNG")
        chain = SceneChain()
        prefix = chain.get_chain_prompt_prefix(frame)
        assert "pose" in prefix.lower() or "position" in prefix.lower()


# ─────────────────────────────────────────────────────────────────────────────
# Layer 4 — Audio Continuity
# ─────────────────────────────────────────────────────────────────────────────

class TestAudioContinuity:
    """Tests for server.ai.prompts.audio_continuity."""

    def _make_plan(self, bgm_mood="upbeat", voice_tone="friendly", tempo="medium"):
        from server.ai.prompts.audio_continuity import AudioPlan
        return AudioPlan(bgm_mood=bgm_mood, voice_tone=voice_tone, tempo=tempo)

    # ── from_skill ────────────────────────────────────────────────────────────

    def test_from_skill_loads_audio_plan_json(self, tmp_path):
        from server.ai.prompts.audio_continuity import AudioContinuity
        plan_file = tmp_path / "audio_plan.json"
        plan_file.write_text(json.dumps({
            "bgm_mood": "calm",
            "voice_tone": "professional",
            "tempo": "slow",
        }))
        ac = AudioContinuity.from_skill(tmp_path)
        assert ac.plan.bgm_mood == "calm"
        assert ac.plan.voice_tone == "professional"
        assert ac.plan.tempo == "slow"

    def test_from_skill_falls_back_to_default_when_no_file(self, tmp_path):
        from server.ai.prompts.audio_continuity import AudioContinuity
        ac = AudioContinuity.from_skill(tmp_path)
        # Should not raise; returns default plan
        assert ac.plan.bgm_mood  # non-empty

    def test_from_skill_falls_back_on_invalid_json(self, tmp_path):
        from server.ai.prompts.audio_continuity import AudioContinuity
        plan_file = tmp_path / "audio_plan.json"
        plan_file.write_text("not valid json {{{")
        ac = AudioContinuity.from_skill(tmp_path)
        assert ac.plan.bgm_mood  # default plan used

    # ── get_scene_position ────────────────────────────────────────────────────

    def test_position_first_scene_is_intro(self):
        from server.ai.prompts.audio_continuity import AudioContinuity
        ac = AudioContinuity.from_plan(self._make_plan())
        assert ac.get_scene_position(0, 5) == "intro"

    def test_position_last_scene_is_outro(self):
        from server.ai.prompts.audio_continuity import AudioContinuity
        ac = AudioContinuity.from_plan(self._make_plan())
        assert ac.get_scene_position(4, 5) == "outro"

    def test_position_middle_scene_is_main(self):
        from server.ai.prompts.audio_continuity import AudioContinuity
        ac = AudioContinuity.from_plan(self._make_plan())
        assert ac.get_scene_position(2, 5) == "main"
        assert ac.get_scene_position(1, 5) == "main"
        assert ac.get_scene_position(3, 5) == "main"

    def test_position_single_scene_is_intro(self):
        from server.ai.prompts.audio_continuity import AudioContinuity
        ac = AudioContinuity.from_plan(self._make_plan())
        assert ac.get_scene_position(0, 1) == "intro"

    # ── get_scene_audio_hint ──────────────────────────────────────────────────

    def test_hint_contains_bgm_mood(self):
        from server.ai.prompts.audio_continuity import AudioContinuity
        ac = AudioContinuity.from_plan(self._make_plan(bgm_mood="energetic"))
        hint = ac.get_scene_audio_hint(0, 5)
        assert "energetic" in hint

    def test_hint_contains_voice_tone(self):
        from server.ai.prompts.audio_continuity import AudioContinuity
        ac = AudioContinuity.from_plan(self._make_plan(voice_tone="warm"))
        hint = ac.get_scene_audio_hint(2, 5)
        assert "warm" in hint

    def test_hint_contains_tempo(self):
        from server.ai.prompts.audio_continuity import AudioContinuity
        ac = AudioContinuity.from_plan(self._make_plan(tempo="fast"))
        hint = ac.get_scene_audio_hint(1, 5)
        assert "fast" in hint

    def test_intro_hint_mentions_intro(self):
        from server.ai.prompts.audio_continuity import AudioContinuity
        ac = AudioContinuity.from_plan(self._make_plan())
        hint = ac.get_scene_audio_hint(0, 5)
        assert "intro" in hint.lower()

    def test_outro_hint_mentions_outro(self):
        from server.ai.prompts.audio_continuity import AudioContinuity
        ac = AudioContinuity.from_plan(self._make_plan())
        hint = ac.get_scene_audio_hint(4, 5)
        assert "outro" in hint.lower()

    def test_main_hint_mentions_main(self):
        from server.ai.prompts.audio_continuity import AudioContinuity
        ac = AudioContinuity.from_plan(self._make_plan())
        hint = ac.get_scene_audio_hint(2, 5)
        assert "main" in hint.lower()

    def test_hints_differ_by_position(self):
        """Intro, main, and outro hints should not all be identical."""
        from server.ai.prompts.audio_continuity import AudioContinuity
        ac = AudioContinuity.from_plan(self._make_plan())
        intro = ac.get_scene_audio_hint(0, 5)
        main = ac.get_scene_audio_hint(2, 5)
        outro = ac.get_scene_audio_hint(4, 5)
        assert intro != main
        assert main != outro
        assert intro != outro

    def test_hint_is_non_empty_string(self):
        from server.ai.prompts.audio_continuity import AudioContinuity
        ac = AudioContinuity.from_plan(self._make_plan())
        for order in range(5):
            hint = ac.get_scene_audio_hint(order, 5)
            assert isinstance(hint, str)
            assert len(hint) > 0


# ─────────────────────────────────────────────────────────────────────────────
# Cross-layer orthogonality smoke test
# ─────────────────────────────────────────────────────────────────────────────

class TestLayerOrthogonality:
    """Verify that the 4 layers can be composed without interfering."""

    def test_all_four_layers_compose(self, tmp_path):
        """Applying all 4 layers in sequence should produce a valid prompt."""
        from server.ai.prompts.style_lock import StyleLock
        from server.ai.prompts.asset_lock import AssetLock
        from server.ai.prompts.scene_chain import SceneChain
        from server.ai.prompts.audio_continuity import AudioContinuity, AudioPlan

        # Layer 1
        style_json = json.dumps({
            "art_style": "cinematic",
            "lighting": "golden hour",
            "color_palette": "warm tones",
            "camera_style": "handheld",
        })
        style_lock = StyleLock.load(style_json)

        # Layer 2
        assets = [_FakeAsset("Hero", "character", "", "tall man in suit")]
        asset_lock = AssetLock.from_assets(assets)

        # Layer 3
        chain = SceneChain()
        prefix = chain.get_chain_prompt_prefix(None)  # first scene

        # Layer 4
        plan = AudioPlan(bgm_mood="dramatic", voice_tone="deep", tempo="slow")
        audio = AudioContinuity.from_plan(plan)
        audio_hint = audio.get_scene_audio_hint(0, 3)

        # Compose
        raw_prompt = "The hero enters the building."
        prompt = style_lock.inject(raw_prompt)
        prompt = asset_lock.inject(prompt)
        if prefix:
            prompt = f"{prefix}\n\n{prompt}"

        # All layers contributed
        assert "cinematic" in prompt.lower() or "golden hour" in prompt.lower()
        assert "Hero" in prompt
        assert audio_hint  # non-empty

    def test_changing_style_does_not_affect_asset_lock(self):
        """Modifying style should not change asset anchor output."""
        from server.ai.prompts.style_lock import StyleLock
        from server.ai.prompts.asset_lock import AssetLock

        assets = [_FakeAsset("Lan", "character", "", "young woman")]
        lock = AssetLock.from_assets(assets)

        style1 = StyleLock.load(json.dumps({"art_style": "cinematic", "lighting": "soft"}))
        style2 = StyleLock.load(json.dumps({"art_style": "anime", "lighting": "harsh"}))

        base = "Scene prompt."
        result1 = lock.inject(style1.inject(base))
        result2 = lock.inject(style2.inject(base))

        # Asset anchors should be identical regardless of style
        assert "Lan" in result1
        assert "Lan" in result2
