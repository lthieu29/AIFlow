"""Tests for Quality Gates G4 (audio quality) and G5 (subtitle quality).

Task 3.3.3 — Quality Gates G4-G5

Tests cover:
    G4 — check_audio_quality:
        - File existence and size checks (G4.1)
        - Silent audio detection (G4.3)
        - Sample rate check (G4.5)
        - Channel count check (G4.6)
        - Duration warning (G4.2) — logged, does not fail
        - ffprobe unavailable — graceful degradation

    G5 — check_subtitle_quality:
        - Empty segments list (G5.1)
        - Invalid timing: start >= end
        - Overlapping segments
        - Coverage warning (< 50%) — logged, does not fail
        - Valid segments pass
        - Missing attributes on segment objects
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers / stubs
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class FakeSegment:
    """Minimal subtitle segment stub."""
    start_sec: float
    end_sec: float
    text: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# G4 — check_audio_quality
# ─────────────────────────────────────────────────────────────────────────────

class TestG4AudioQuality:
    """Tests for G4 audio quality gate."""

    # ── G4.1 — file existence and size ────────────────────────────────────────

    def test_fails_when_file_missing(self, tmp_path):
        from server.pipeline.gates.g4_audio_quality import check_audio_quality
        audio = tmp_path / "nonexistent.mp3"
        result = check_audio_quality(audio)
        assert result.gate_id == "G4"
        assert result.status == "failed"
        assert "G4.1" in result.message
        assert "not found" in result.message.lower()

    def test_fails_when_file_too_small(self, tmp_path):
        from server.pipeline.gates.g4_audio_quality import check_audio_quality
        audio = tmp_path / "tiny.mp3"
        audio.write_bytes(b"x" * 100)  # 100 bytes — well below 10 KB
        result = check_audio_quality(audio)
        assert result.status == "failed"
        assert "G4.1" in result.message
        assert "small" in result.message.lower()

    def test_fails_at_exactly_10kb(self, tmp_path):
        """Boundary: exactly 10 KB (10240 bytes) should fail (must be > 10 KB)."""
        from server.pipeline.gates.g4_audio_quality import (
            _MIN_AUDIO_SIZE_BYTES,
            check_audio_quality,
        )
        audio = tmp_path / "boundary.mp3"
        audio.write_bytes(b"x" * _MIN_AUDIO_SIZE_BYTES)
        # ffprobe will fail on fake data — patch it out
        with patch("server.pipeline.gates.g4_audio_quality._probe_audio_stream", return_value=None):
            result = check_audio_quality(audio)
        assert result.status == "failed"
        assert "G4.1" in result.message

    def test_passes_at_10kb_plus_one(self, tmp_path):
        """Boundary: 10 KB + 1 byte should pass the size check."""
        from server.pipeline.gates.g4_audio_quality import (
            _MIN_AUDIO_SIZE_BYTES,
            check_audio_quality,
        )
        audio = tmp_path / "just_over.mp3"
        audio.write_bytes(b"x" * (_MIN_AUDIO_SIZE_BYTES + 1))
        # Patch ffprobe to return a valid stream (no silence, good sample rate, stereo)
        fake_stream = {"sample_rate": "44100", "channels": 2}
        with patch("server.pipeline.gates.g4_audio_quality._probe_audio_stream", return_value=fake_stream):
            result = check_audio_quality(audio)
        assert result.status == "passed"

    # ── G4.3 — silence detection ──────────────────────────────────────────────

    def test_fails_when_audio_silent_via_rms_tag(self, tmp_path):
        from server.pipeline.gates.g4_audio_quality import (
            _MIN_AUDIO_SIZE_BYTES,
            check_audio_quality,
        )
        audio = tmp_path / "silent.mp3"
        audio.write_bytes(b"x" * (_MIN_AUDIO_SIZE_BYTES + 1))
        # Simulate ffprobe returning a stream with mean_volume at silence threshold
        fake_stream = {
            "sample_rate": "44100",
            "channels": 2,
            "tags": {"mean_volume": "-65.0 dB"},
        }
        with patch("server.pipeline.gates.g4_audio_quality._probe_audio_stream", return_value=fake_stream):
            result = check_audio_quality(audio)
        assert result.status == "failed"
        assert "G4.3" in result.message
        assert "silent" in result.message.lower()

    def test_fails_when_nb_samples_is_zero(self, tmp_path):
        from server.pipeline.gates.g4_audio_quality import (
            _MIN_AUDIO_SIZE_BYTES,
            check_audio_quality,
        )
        audio = tmp_path / "zero_samples.mp3"
        audio.write_bytes(b"x" * (_MIN_AUDIO_SIZE_BYTES + 1))
        fake_stream = {
            "sample_rate": "44100",
            "channels": 2,
            "nb_samples": "0",
        }
        with patch("server.pipeline.gates.g4_audio_quality._probe_audio_stream", return_value=fake_stream):
            result = check_audio_quality(audio)
        assert result.status == "failed"
        assert "G4.3" in result.message

    def test_passes_when_audio_has_signal(self, tmp_path):
        from server.pipeline.gates.g4_audio_quality import (
            _MIN_AUDIO_SIZE_BYTES,
            check_audio_quality,
        )
        audio = tmp_path / "good.mp3"
        audio.write_bytes(b"x" * (_MIN_AUDIO_SIZE_BYTES + 1))
        fake_stream = {
            "sample_rate": "44100",
            "channels": 2,
            "tags": {"mean_volume": "-20.0 dB"},
        }
        with patch("server.pipeline.gates.g4_audio_quality._probe_audio_stream", return_value=fake_stream):
            result = check_audio_quality(audio)
        assert result.status == "passed"

    # ── G4.5 — sample rate ────────────────────────────────────────────────────

    def test_fails_when_sample_rate_too_low(self, tmp_path):
        from server.pipeline.gates.g4_audio_quality import (
            _MIN_AUDIO_SIZE_BYTES,
            check_audio_quality,
        )
        audio = tmp_path / "low_rate.mp3"
        audio.write_bytes(b"x" * (_MIN_AUDIO_SIZE_BYTES + 1))
        fake_stream = {"sample_rate": "8000", "channels": 1}  # 8 kHz — below 16 kHz
        with patch("server.pipeline.gates.g4_audio_quality._probe_audio_stream", return_value=fake_stream):
            result = check_audio_quality(audio)
        assert result.status == "failed"
        assert "G4.5" in result.message
        assert "8000" in result.message

    def test_passes_at_exactly_16khz(self, tmp_path):
        from server.pipeline.gates.g4_audio_quality import (
            _MIN_AUDIO_SIZE_BYTES,
            check_audio_quality,
        )
        audio = tmp_path / "16khz.mp3"
        audio.write_bytes(b"x" * (_MIN_AUDIO_SIZE_BYTES + 1))
        fake_stream = {"sample_rate": "16000", "channels": 1}
        with patch("server.pipeline.gates.g4_audio_quality._probe_audio_stream", return_value=fake_stream):
            result = check_audio_quality(audio)
        assert result.status == "passed"

    def test_passes_at_44khz(self, tmp_path):
        from server.pipeline.gates.g4_audio_quality import (
            _MIN_AUDIO_SIZE_BYTES,
            check_audio_quality,
        )
        audio = tmp_path / "44khz.mp3"
        audio.write_bytes(b"x" * (_MIN_AUDIO_SIZE_BYTES + 1))
        fake_stream = {"sample_rate": "44100", "channels": 2}
        with patch("server.pipeline.gates.g4_audio_quality._probe_audio_stream", return_value=fake_stream):
            result = check_audio_quality(audio)
        assert result.status == "passed"

    # ── G4.6 — channel count ──────────────────────────────────────────────────

    def test_fails_when_channels_invalid(self, tmp_path):
        from server.pipeline.gates.g4_audio_quality import (
            _MIN_AUDIO_SIZE_BYTES,
            check_audio_quality,
        )
        audio = tmp_path / "surround.mp3"
        audio.write_bytes(b"x" * (_MIN_AUDIO_SIZE_BYTES + 1))
        fake_stream = {"sample_rate": "44100", "channels": 6}  # 5.1 surround
        with patch("server.pipeline.gates.g4_audio_quality._probe_audio_stream", return_value=fake_stream):
            result = check_audio_quality(audio)
        assert result.status == "failed"
        assert "G4.6" in result.message
        assert "6" in result.message

    def test_passes_mono(self, tmp_path):
        from server.pipeline.gates.g4_audio_quality import (
            _MIN_AUDIO_SIZE_BYTES,
            check_audio_quality,
        )
        audio = tmp_path / "mono.mp3"
        audio.write_bytes(b"x" * (_MIN_AUDIO_SIZE_BYTES + 1))
        fake_stream = {"sample_rate": "22050", "channels": 1}
        with patch("server.pipeline.gates.g4_audio_quality._probe_audio_stream", return_value=fake_stream):
            result = check_audio_quality(audio)
        assert result.status == "passed"

    def test_passes_stereo(self, tmp_path):
        from server.pipeline.gates.g4_audio_quality import (
            _MIN_AUDIO_SIZE_BYTES,
            check_audio_quality,
        )
        audio = tmp_path / "stereo.mp3"
        audio.write_bytes(b"x" * (_MIN_AUDIO_SIZE_BYTES + 1))
        fake_stream = {"sample_rate": "48000", "channels": 2}
        with patch("server.pipeline.gates.g4_audio_quality._probe_audio_stream", return_value=fake_stream):
            result = check_audio_quality(audio)
        assert result.status == "passed"

    # ── G4.2 — duration warning (does not block) ──────────────────────────────

    def test_duration_warning_does_not_fail(self, tmp_path):
        """G4.2 duration mismatch is a warning — gate should still pass."""
        from server.pipeline.gates.g4_audio_quality import (
            _MIN_AUDIO_SIZE_BYTES,
            check_audio_quality,
        )
        audio = tmp_path / "wrong_duration.mp3"
        audio.write_bytes(b"x" * (_MIN_AUDIO_SIZE_BYTES + 1))
        fake_stream = {"sample_rate": "44100", "channels": 2}
        with (
            patch("server.pipeline.gates.g4_audio_quality._probe_audio_stream", return_value=fake_stream),
            patch("server.pipeline.gates.g4_audio_quality.probe_duration", return_value=5.0),
        ):
            # expected=10s, actual=5s → 50% deviation > 20% tolerance
            result = check_audio_quality(audio, expected_duration=10.0)
        assert result.status == "passed"  # warning only, not a failure

    def test_duration_within_tolerance_passes(self, tmp_path):
        from server.pipeline.gates.g4_audio_quality import (
            _MIN_AUDIO_SIZE_BYTES,
            check_audio_quality,
        )
        audio = tmp_path / "good_duration.mp3"
        audio.write_bytes(b"x" * (_MIN_AUDIO_SIZE_BYTES + 1))
        fake_stream = {"sample_rate": "44100", "channels": 2}
        with (
            patch("server.pipeline.gates.g4_audio_quality._probe_audio_stream", return_value=fake_stream),
            patch("server.pipeline.gates.g4_audio_quality.probe_duration", return_value=10.1),
        ):
            # expected=10s, actual=10.1s → 1% deviation — within 20%
            result = check_audio_quality(audio, expected_duration=10.0)
        assert result.status == "passed"

    # ── ffprobe unavailable — graceful degradation ────────────────────────────

    def test_passes_when_ffprobe_unavailable(self, tmp_path):
        """When ffprobe is not found, stream checks are skipped and gate passes."""
        from server.pipeline.gates.g4_audio_quality import (
            _MIN_AUDIO_SIZE_BYTES,
            check_audio_quality,
        )
        audio = tmp_path / "no_ffprobe.mp3"
        audio.write_bytes(b"x" * (_MIN_AUDIO_SIZE_BYTES + 1))
        with patch("server.pipeline.gates.g4_audio_quality._probe_audio_stream", return_value=None):
            result = check_audio_quality(audio)
        assert result.status == "passed"

    # ── Gate ID ───────────────────────────────────────────────────────────────

    def test_gate_id_is_g4(self, tmp_path):
        from server.pipeline.gates.g4_audio_quality import check_audio_quality
        audio = tmp_path / "missing.mp3"
        result = check_audio_quality(audio)
        assert result.gate_id == "G4"


# ─────────────────────────────────────────────────────────────────────────────
# G5 — check_subtitle_quality
# ─────────────────────────────────────────────────────────────────────────────

class TestG5SubtitleQuality:
    """Tests for G5 subtitle quality gate."""

    # ── G5.1 — non-empty segments ─────────────────────────────────────────────

    def test_fails_when_segments_empty(self):
        from server.pipeline.gates.g5_subtitle_quality import check_subtitle_quality
        result = check_subtitle_quality([])
        assert result.gate_id == "G5"
        assert result.status == "failed"
        assert "G5.1" in result.message
        assert "empty" in result.message.lower()

    def test_passes_with_single_valid_segment(self):
        from server.pipeline.gates.g5_subtitle_quality import check_subtitle_quality
        segs = [FakeSegment(start_sec=0.0, end_sec=2.0, text="Hello")]
        result = check_subtitle_quality(segs)
        assert result.status == "passed"
        assert result.gate_id == "G5"

    def test_passes_with_multiple_valid_segments(self):
        from server.pipeline.gates.g5_subtitle_quality import check_subtitle_quality
        segs = [
            FakeSegment(start_sec=0.0, end_sec=2.0, text="Hello"),
            FakeSegment(start_sec=2.5, end_sec=5.0, text="World"),
            FakeSegment(start_sec=5.5, end_sec=8.0, text="Goodbye"),
        ]
        result = check_subtitle_quality(segs)
        assert result.status == "passed"

    # ── Invalid timing: start >= end ──────────────────────────────────────────

    def test_fails_when_start_equals_end(self):
        from server.pipeline.gates.g5_subtitle_quality import check_subtitle_quality
        segs = [FakeSegment(start_sec=1.0, end_sec=1.0, text="Zero duration")]
        result = check_subtitle_quality(segs)
        assert result.status == "failed"
        assert "start_sec" in result.message or "invalid" in result.message.lower()

    def test_fails_when_start_after_end(self):
        from server.pipeline.gates.g5_subtitle_quality import check_subtitle_quality
        segs = [FakeSegment(start_sec=5.0, end_sec=2.0, text="Reversed")]
        result = check_subtitle_quality(segs)
        assert result.status == "failed"

    def test_fails_when_second_segment_has_invalid_timing(self):
        from server.pipeline.gates.g5_subtitle_quality import check_subtitle_quality
        segs = [
            FakeSegment(start_sec=0.0, end_sec=2.0, text="OK"),
            FakeSegment(start_sec=3.0, end_sec=3.0, text="Bad"),  # start == end
        ]
        result = check_subtitle_quality(segs)
        assert result.status == "failed"

    # ── Overlapping segments ──────────────────────────────────────────────────

    def test_fails_when_segments_overlap(self):
        from server.pipeline.gates.g5_subtitle_quality import check_subtitle_quality
        segs = [
            FakeSegment(start_sec=0.0, end_sec=3.0, text="First"),
            FakeSegment(start_sec=2.0, end_sec=5.0, text="Overlaps first"),
        ]
        result = check_subtitle_quality(segs)
        assert result.status == "failed"
        assert "overlap" in result.message.lower()

    def test_fails_when_out_of_order_segments_overlap(self):
        """Segments provided out of order that overlap should still be detected."""
        from server.pipeline.gates.g5_subtitle_quality import check_subtitle_quality
        segs = [
            FakeSegment(start_sec=2.0, end_sec=5.0, text="Second"),
            FakeSegment(start_sec=0.0, end_sec=3.0, text="First — overlaps second"),
        ]
        result = check_subtitle_quality(segs)
        assert result.status == "failed"

    def test_passes_when_segments_adjacent_no_gap(self):
        """Segments that touch (end == next start) should not be considered overlapping."""
        from server.pipeline.gates.g5_subtitle_quality import check_subtitle_quality
        segs = [
            FakeSegment(start_sec=0.0, end_sec=2.0, text="First"),
            FakeSegment(start_sec=2.0, end_sec=4.0, text="Second — starts exactly at first end"),
        ]
        result = check_subtitle_quality(segs)
        assert result.status == "passed"

    def test_passes_when_segments_have_gap(self):
        from server.pipeline.gates.g5_subtitle_quality import check_subtitle_quality
        segs = [
            FakeSegment(start_sec=0.0, end_sec=2.0, text="First"),
            FakeSegment(start_sec=3.0, end_sec=5.0, text="Second — gap of 1s"),
        ]
        result = check_subtitle_quality(segs)
        assert result.status == "passed"

    # ── Coverage warning (does not block) ─────────────────────────────────────

    def test_low_coverage_does_not_fail(self):
        """Coverage < 50% is a warning — gate should still pass."""
        from server.pipeline.gates.g5_subtitle_quality import check_subtitle_quality
        # 2s of subtitles over a 10s video = 20% coverage
        segs = [FakeSegment(start_sec=0.0, end_sec=2.0, text="Short")]
        result = check_subtitle_quality(segs, video_duration=10.0)
        assert result.status == "passed"

    def test_high_coverage_passes(self):
        from server.pipeline.gates.g5_subtitle_quality import check_subtitle_quality
        # 8s of subtitles over a 10s video = 80% coverage
        segs = [
            FakeSegment(start_sec=0.0, end_sec=4.0, text="Part 1"),
            FakeSegment(start_sec=4.5, end_sec=8.5, text="Part 2"),
        ]
        result = check_subtitle_quality(segs, video_duration=10.0)
        assert result.status == "passed"

    def test_no_video_duration_skips_coverage_check(self):
        """When video_duration is None, coverage check is skipped."""
        from server.pipeline.gates.g5_subtitle_quality import check_subtitle_quality
        segs = [FakeSegment(start_sec=0.0, end_sec=1.0, text="Tiny")]
        result = check_subtitle_quality(segs, video_duration=None)
        assert result.status == "passed"

    # ── Missing attributes ────────────────────────────────────────────────────

    def test_fails_when_segment_missing_start_sec(self):
        from server.pipeline.gates.g5_subtitle_quality import check_subtitle_quality

        class BadSeg:
            end_sec = 2.0

        result = check_subtitle_quality([BadSeg()])
        assert result.status == "failed"
        assert "start_sec" in result.message or "missing" in result.message.lower()

    def test_fails_when_segment_missing_end_sec(self):
        from server.pipeline.gates.g5_subtitle_quality import check_subtitle_quality

        class BadSeg:
            start_sec = 0.0

        result = check_subtitle_quality([BadSeg()])
        assert result.status == "failed"

    # ── Gate ID ───────────────────────────────────────────────────────────────

    def test_gate_id_is_g5(self):
        from server.pipeline.gates.g5_subtitle_quality import check_subtitle_quality
        result = check_subtitle_quality([])
        assert result.gate_id == "G5"

    # ── Integration with SubtitleSegment from composer ────────────────────────

    def test_accepts_composer_subtitle_segment(self):
        """G5 should accept SubtitleSegment objects from server.render.composer."""
        from server.pipeline.gates.g5_subtitle_quality import check_subtitle_quality
        from server.render.composer import SubtitleSegment

        segs = [
            SubtitleSegment(text="Hello", start_sec=0.0, end_sec=2.0),
            SubtitleSegment(text="World", start_sec=2.5, end_sec=5.0),
        ]
        result = check_subtitle_quality(segs, video_duration=10.0)
        assert result.status == "passed"

    def test_rejects_overlapping_composer_segments(self):
        from server.pipeline.gates.g5_subtitle_quality import check_subtitle_quality
        from server.render.composer import SubtitleSegment

        segs = [
            SubtitleSegment(text="First", start_sec=0.0, end_sec=3.0),
            SubtitleSegment(text="Overlap", start_sec=2.0, end_sec=5.0),
        ]
        result = check_subtitle_quality(segs)
        assert result.status == "failed"


# ─────────────────────────────────────────────────────────────────────────────
# Gates package re-exports
# ─────────────────────────────────────────────────────────────────────────────

class TestGatesPackageExports:
    """Verify G4 and G5 are accessible via the gates package."""

    def test_check_audio_quality_exported(self):
        from server.pipeline.gates import check_audio_quality
        assert callable(check_audio_quality)

    def test_check_subtitle_quality_exported(self):
        from server.pipeline.gates import check_subtitle_quality
        assert callable(check_subtitle_quality)
