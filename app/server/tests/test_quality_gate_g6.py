"""Tests for Quality Gate G6 (final video quality check).

Task 2.5 — Quality Gate G6

Tests cover:
    G6.1 — File size sanity (> 500 KB)
    G6.2 — Duration check (±2s tolerance)
    G6.3 — Resolution check (aspect ratio → expected dimensions)
    G6.4 — Audio stream present
    G6.5 — No black frames (all-black detection)
    Override — skip all checks when override=True
    Package exports — G6FinalVideoGate accessible via gates package
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# ─── Helpers ──────────────────────────────────────────────────────────────────

_MIN_SIZE = 500 * 1024 + 1  # 500 KB + 1 byte — just over the threshold


def _make_video_file(tmp_path: Path, size: int = _MIN_SIZE) -> Path:
    """Create a fake video file of the given size."""
    p = tmp_path / "final.mp4"
    p.write_bytes(b"\x00" * size)
    return p


def _good_probe(width: int = 1080, height: int = 1920, duration: float = 30.0) -> dict:
    """Return a minimal ffprobe-style dict for a valid 9:16 video."""
    return {
        "streams": [
            {
                "codec_type": "video",
                "width": width,
                "height": height,
                "duration": str(duration),
            },
            {
                "codec_type": "audio",
                "channels": 2,
            },
        ],
        "format": {
            "duration": str(duration),
        },
    }


def _no_audio_probe(width: int = 1080, height: int = 1920, duration: float = 30.0) -> dict:
    """Return a probe dict with no audio stream."""
    return {
        "streams": [
            {
                "codec_type": "video",
                "width": width,
                "height": height,
                "duration": str(duration),
            },
        ],
        "format": {"duration": str(duration)},
    }


# ─── G6.1 — File size ─────────────────────────────────────────────────────────

class TestG6FileSize:
    """G6.1 — file must exist and be > 500 KB."""

    def test_fails_when_file_missing(self, tmp_path):
        from server.pipeline.gates.g6_final_video import G6FinalVideoGate
        gate = G6FinalVideoGate()
        result = gate.check(tmp_path / "nonexistent.mp4")
        assert result.passed is False
        assert "G6.1" in (result.error or "")
        assert "not found" in (result.error or "").lower()

    def test_fails_when_file_too_small(self, tmp_path):
        from server.pipeline.gates.g6_final_video import G6FinalVideoGate
        p = _make_video_file(tmp_path, size=1000)
        gate = G6FinalVideoGate()
        result = gate.check(p)
        assert result.passed is False
        assert "G6.1" in (result.error or "")

    def test_fails_at_exactly_500kb(self, tmp_path):
        from server.pipeline.gates.g6_final_video import G6FinalVideoGate, _MIN_FILE_SIZE_BYTES
        p = _make_video_file(tmp_path, size=_MIN_FILE_SIZE_BYTES)
        gate = G6FinalVideoGate()
        with patch("server.pipeline.gates.g6_final_video._probe_video", return_value=None):
            with patch("server.pipeline.gates.g6_final_video._check_black_frames",
                       return_value={"all_black": False, "skipped": True}):
                result = gate.check(p)
        assert result.passed is False
        assert "G6.1" in (result.error or "")

    def test_passes_at_500kb_plus_one(self, tmp_path):
        from server.pipeline.gates.g6_final_video import G6FinalVideoGate, _MIN_FILE_SIZE_BYTES
        p = _make_video_file(tmp_path, size=_MIN_FILE_SIZE_BYTES + 1)
        gate = G6FinalVideoGate()
        with patch("server.pipeline.gates.g6_final_video._probe_video",
                   return_value=_good_probe()):
            with patch("server.pipeline.gates.g6_final_video._check_black_frames",
                       return_value={"all_black": False, "skipped": False,
                                     "sampled_brightnesses": [120.0]}):
                result = gate.check(p)
        assert result.passed is True


# ─── G6.2 — Duration check ────────────────────────────────────────────────────

class TestG6Duration:
    """G6.2 — actual duration within ±2s of expected."""

    def _run(self, tmp_path, actual_dur, expected_dur, aspect=None):
        from server.pipeline.gates.g6_final_video import G6FinalVideoGate
        p = _make_video_file(tmp_path)
        gate = G6FinalVideoGate()
        probe = _good_probe(duration=actual_dur)
        with patch("server.pipeline.gates.g6_final_video._probe_video", return_value=probe):
            with patch("server.pipeline.gates.g6_final_video._check_black_frames",
                       return_value={"all_black": False, "skipped": False,
                                     "sampled_brightnesses": [100.0]}):
                return gate.check(p, expected_duration=expected_dur, aspect_ratio=aspect)

    def test_passes_when_within_tolerance(self, tmp_path):
        result = self._run(tmp_path, actual_dur=30.0, expected_dur=31.5)
        assert result.passed is True

    def test_passes_at_exactly_2s_deviation(self, tmp_path):
        result = self._run(tmp_path, actual_dur=30.0, expected_dur=32.0)
        assert result.passed is True

    def test_fails_when_over_2s_deviation(self, tmp_path):
        result = self._run(tmp_path, actual_dur=30.0, expected_dur=33.0)
        assert result.passed is False
        assert "G6.2" in (result.error or "")

    def test_fails_when_under_by_more_than_2s(self, tmp_path):
        result = self._run(tmp_path, actual_dur=30.0, expected_dur=27.0)
        assert result.passed is False
        assert "G6.2" in (result.error or "")

    def test_skipped_when_no_expected_duration(self, tmp_path):
        """When expected_duration is None, G6.2 is skipped and gate passes."""
        result = self._run(tmp_path, actual_dur=30.0, expected_dur=None)
        assert result.passed is True


# ─── G6.3 — Resolution check ─────────────────────────────────────────────────

class TestG6Resolution:
    """G6.3 — width/height must match project aspect ratio."""

    def _run(self, tmp_path, width, height, aspect_ratio):
        from server.pipeline.gates.g6_final_video import G6FinalVideoGate
        p = _make_video_file(tmp_path)
        gate = G6FinalVideoGate()
        probe = _good_probe(width=width, height=height)
        with patch("server.pipeline.gates.g6_final_video._probe_video", return_value=probe):
            with patch("server.pipeline.gates.g6_final_video._check_black_frames",
                       return_value={"all_black": False, "skipped": False,
                                     "sampled_brightnesses": [100.0]}):
                return gate.check(p, aspect_ratio=aspect_ratio)

    def test_passes_9_16_correct_resolution(self, tmp_path):
        result = self._run(tmp_path, 1080, 1920, "9:16")
        assert result.passed is True

    def test_passes_16_9_correct_resolution(self, tmp_path):
        result = self._run(tmp_path, 1920, 1080, "16:9")
        assert result.passed is True

    def test_passes_1_1_correct_resolution(self, tmp_path):
        result = self._run(tmp_path, 1080, 1080, "1:1")
        assert result.passed is True

    def test_fails_wrong_resolution_for_9_16(self, tmp_path):
        result = self._run(tmp_path, 1920, 1080, "9:16")  # 16:9 dims for 9:16 ratio
        assert result.passed is False
        assert "G6.3" in (result.error or "")
        assert "1920" in (result.error or "") or "1080" in (result.error or "")

    def test_fails_wrong_resolution_for_16_9(self, tmp_path):
        result = self._run(tmp_path, 1080, 1920, "16:9")  # 9:16 dims for 16:9 ratio
        assert result.passed is False
        assert "G6.3" in (result.error or "")

    def test_skipped_when_no_aspect_ratio(self, tmp_path):
        """When aspect_ratio is None, G6.3 is skipped."""
        result = self._run(tmp_path, 640, 480, None)
        assert result.passed is True


# ─── G6.4 — Audio stream present ─────────────────────────────────────────────

class TestG6AudioStream:
    """G6.4 — at least 1 audio stream must be present."""

    def test_fails_when_no_audio_stream(self, tmp_path):
        from server.pipeline.gates.g6_final_video import G6FinalVideoGate
        p = _make_video_file(tmp_path)
        gate = G6FinalVideoGate()
        probe = _no_audio_probe()
        with patch("server.pipeline.gates.g6_final_video._probe_video", return_value=probe):
            with patch("server.pipeline.gates.g6_final_video._check_black_frames",
                       return_value={"all_black": False, "skipped": True}):
                result = gate.check(p)
        assert result.passed is False
        assert "G6.4" in (result.error or "")
        assert "audio" in (result.error or "").lower()

    def test_passes_with_one_audio_stream(self, tmp_path):
        from server.pipeline.gates.g6_final_video import G6FinalVideoGate
        p = _make_video_file(tmp_path)
        gate = G6FinalVideoGate()
        probe = _good_probe()  # has 1 audio stream
        with patch("server.pipeline.gates.g6_final_video._probe_video", return_value=probe):
            with patch("server.pipeline.gates.g6_final_video._check_black_frames",
                       return_value={"all_black": False, "skipped": False,
                                     "sampled_brightnesses": [100.0]}):
                result = gate.check(p)
        assert result.passed is True
        assert result.details.get("audio_stream_count", 0) >= 1


# ─── G6.5 — Black frame detection ────────────────────────────────────────────

class TestG6BlackFrames:
    """G6.5 — reject if all sampled frames are black."""

    def test_fails_when_all_frames_black(self, tmp_path):
        from server.pipeline.gates.g6_final_video import G6FinalVideoGate
        p = _make_video_file(tmp_path)
        gate = G6FinalVideoGate()
        probe = _good_probe()
        black_result = {
            "all_black": True,
            "sampled_brightnesses": [1.0, 2.0, 0.5, 1.5, 0.0],
            "skipped": False,
        }
        with patch("server.pipeline.gates.g6_final_video._probe_video", return_value=probe):
            with patch("server.pipeline.gates.g6_final_video._check_black_frames",
                       return_value=black_result):
                result = gate.check(p)
        assert result.passed is False
        assert "G6.5" in (result.error or "")
        assert "black" in (result.error or "").lower()

    def test_passes_when_frames_have_content(self, tmp_path):
        from server.pipeline.gates.g6_final_video import G6FinalVideoGate
        p = _make_video_file(tmp_path)
        gate = G6FinalVideoGate()
        probe = _good_probe()
        bright_result = {
            "all_black": False,
            "sampled_brightnesses": [80.0, 90.0, 75.0, 85.0, 95.0],
            "skipped": False,
        }
        with patch("server.pipeline.gates.g6_final_video._probe_video", return_value=probe):
            with patch("server.pipeline.gates.g6_final_video._check_black_frames",
                       return_value=bright_result):
                result = gate.check(p)
        assert result.passed is True

    def test_passes_when_only_some_frames_black(self, tmp_path):
        """Only ALL-black triggers failure; partial black is OK."""
        from server.pipeline.gates.g6_final_video import G6FinalVideoGate
        p = _make_video_file(tmp_path)
        gate = G6FinalVideoGate()
        probe = _good_probe()
        mixed_result = {
            "all_black": False,
            "sampled_brightnesses": [0.0, 0.0, 80.0, 0.0, 0.0],
            "skipped": False,
        }
        with patch("server.pipeline.gates.g6_final_video._probe_video", return_value=probe):
            with patch("server.pipeline.gates.g6_final_video._check_black_frames",
                       return_value=mixed_result):
                result = gate.check(p)
        assert result.passed is True

    def test_passes_when_black_frame_check_skipped(self, tmp_path):
        """If ffmpeg is unavailable, black frame check is skipped (not a failure)."""
        from server.pipeline.gates.g6_final_video import G6FinalVideoGate
        p = _make_video_file(tmp_path)
        gate = G6FinalVideoGate()
        probe = _good_probe()
        with patch("server.pipeline.gates.g6_final_video._probe_video", return_value=probe):
            with patch("server.pipeline.gates.g6_final_video._check_black_frames",
                       return_value={"all_black": False, "skipped": True,
                                     "reason": "ffmpeg not found"}):
                result = gate.check(p)
        assert result.passed is True


# ─── Override ─────────────────────────────────────────────────────────────────

class TestG6Override:
    """Manual override skips all checks."""

    def test_override_passes_even_with_missing_file(self, tmp_path):
        from server.pipeline.gates.g6_final_video import G6FinalVideoGate
        gate = G6FinalVideoGate()
        result = gate.check(tmp_path / "nonexistent.mp4", override=True)
        assert result.passed is True
        assert result.score == 1.0
        assert result.details.get("override") is True
        assert result.error is None

    def test_override_passes_even_with_tiny_file(self, tmp_path):
        from server.pipeline.gates.g6_final_video import G6FinalVideoGate
        p = _make_video_file(tmp_path, size=100)
        gate = G6FinalVideoGate()
        result = gate.check(p, override=True)
        assert result.passed is True

    def test_override_passes_even_with_wrong_resolution(self, tmp_path):
        from server.pipeline.gates.g6_final_video import G6FinalVideoGate
        p = _make_video_file(tmp_path)
        gate = G6FinalVideoGate()
        # Wrong resolution for 9:16 — but override=True should skip
        result = gate.check(p, aspect_ratio="9:16", override=True)
        assert result.passed is True


# ─── G6Result.to_gate_result ──────────────────────────────────────────────────

class TestG6ResultConversion:
    """G6Result.to_gate_result() converts to standard GateResult."""

    def test_passed_result_converts_correctly(self):
        from server.pipeline.gates.g6_final_video import G6Result
        r = G6Result(passed=True, score=0.9, details={}, error=None)
        gate_result = r.to_gate_result()
        assert gate_result.gate_id == "G6"
        assert gate_result.status == "passed"
        assert gate_result.message == ""

    def test_failed_result_converts_correctly(self):
        from server.pipeline.gates.g6_final_video import G6Result
        r = G6Result(passed=False, score=0.5, details={}, error="G6.4: No audio stream.")
        gate_result = r.to_gate_result()
        assert gate_result.gate_id == "G6"
        assert gate_result.status == "failed"
        assert "G6.4" in gate_result.message

    def test_custom_gate_id(self):
        from server.pipeline.gates.g6_final_video import G6Result
        r = G6Result(passed=True, score=1.0, details={}, error=None)
        gate_result = r.to_gate_result(gate_id="G6_CUSTOM")
        assert gate_result.gate_id == "G6_CUSTOM"


# ─── Score calculation ────────────────────────────────────────────────────────

class TestG6Score:
    """Score reflects fraction of checks passed."""

    def test_score_is_1_when_all_pass(self, tmp_path):
        from server.pipeline.gates.g6_final_video import G6FinalVideoGate
        p = _make_video_file(tmp_path)
        gate = G6FinalVideoGate()
        probe = _good_probe()
        with patch("server.pipeline.gates.g6_final_video._probe_video", return_value=probe):
            with patch("server.pipeline.gates.g6_final_video._check_black_frames",
                       return_value={"all_black": False, "skipped": False,
                                     "sampled_brightnesses": [100.0]}):
                result = gate.check(p)
        assert result.passed is True
        assert result.score == 1.0

    def test_score_is_0_when_file_missing(self, tmp_path):
        from server.pipeline.gates.g6_final_video import G6FinalVideoGate
        gate = G6FinalVideoGate()
        result = gate.check(tmp_path / "missing.mp4")
        assert result.passed is False
        assert result.score == 0.0


# ─── Package exports ──────────────────────────────────────────────────────────

class TestGatesPackageExportsG6:
    """G6 symbols are accessible via the gates package."""

    def test_g6_gate_class_exported(self):
        from server.pipeline.gates import G6FinalVideoGate
        assert callable(G6FinalVideoGate)

    def test_g6_result_exported(self):
        from server.pipeline.gates import G6Result
        assert G6Result is not None

    def test_check_final_video_exported(self):
        from server.pipeline.gates import check_final_video
        assert callable(check_final_video)


# ─── Convenience function ─────────────────────────────────────────────────────

class TestCheckFinalVideoConvenience:
    """check_final_video() is a thin wrapper around G6FinalVideoGate.check()."""

    def test_convenience_function_returns_g6_result(self, tmp_path):
        from server.pipeline.gates.g6_final_video import G6Result, check_final_video
        p = _make_video_file(tmp_path)
        with patch("server.pipeline.gates.g6_final_video._probe_video",
                   return_value=_good_probe()):
            with patch("server.pipeline.gates.g6_final_video._check_black_frames",
                       return_value={"all_black": False, "skipped": False,
                                     "sampled_brightnesses": [100.0]}):
                result = check_final_video(p)
        assert isinstance(result, G6Result)
        assert result.passed is True

    def test_convenience_function_override(self, tmp_path):
        from server.pipeline.gates.g6_final_video import check_final_video
        result = check_final_video(tmp_path / "missing.mp4", override=True)
        assert result.passed is True
