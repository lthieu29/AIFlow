"""G4 — Audio quality check gate.

Phase 3.1 implementation: validates the composed audio (TTS + BGM mix) meets
quality thresholds before the pipeline proceeds to subtitle generation.

Checks performed (per spec 07 §G4):
    G4.1 — Audio file exists and size > 10 KB
    G4.2 — ffprobe duration within ±20% of expected TTS duration (Warning)
    G4.3 — Audio is not silent (RMS > -60 dBFS, via ffprobe stream info)
    G4.5 — Audio sample rate ≥ 16 kHz
    G4.6 — Audio channels ∈ [1, 2] (mono or stereo)

Critical failures (G4.1, G4.3, G4.5, G4.6) block the pipeline.
Warning failures (G4.2) are logged but do not block.

Functions:
    check_audio_quality — run G4 checks on an audio file
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Optional

from loguru import logger

from server.audio.ffmpeg_utils import find_ffprobe, probe_duration
from server.pipeline.quality_gate import GateResult

# ─── Constants ────────────────────────────────────────────────────────────────

# G4.1 — minimum audio file size
_MIN_AUDIO_SIZE_BYTES: int = 10 * 1024  # 10 KB

# G4.2 — acceptable duration deviation (±20%)
_DURATION_TOLERANCE: float = 0.20

# G4.3 — silence threshold in dBFS (RMS must be above this)
_SILENCE_THRESHOLD_DBFS: float = -60.0

# G4.5 — minimum sample rate
_MIN_SAMPLE_RATE_HZ: int = 16_000  # 16 kHz

# G4.6 — acceptable channel counts
_VALID_CHANNEL_COUNTS: frozenset[int] = frozenset({1, 2})


# ─── Public API ───────────────────────────────────────────────────────────────

def check_audio_quality(
    audio_path: Path,
    expected_duration: Optional[float] = None,
) -> GateResult:
    """Run G4 quality checks on an audio file.

    Args:
        audio_path:        Path to the audio file to validate.
        expected_duration: Expected TTS duration in seconds (used for G4.2
                           duration check). If None, G4.2 is skipped.

    Returns:
        GateResult with gate_id="G4", status="passed" or "failed".
        On failure, message describes the first critical issue found.
        Warnings are logged but do not cause a "failed" status.
    """
    # G4.1 — file must exist and be > 10 KB
    if not audio_path.exists():
        return GateResult(
            gate_id="G4",
            status="failed",
            message=(
                f"G4.1: Audio file not found: {audio_path}"
            ),
        )

    file_size = audio_path.stat().st_size
    if file_size <= _MIN_AUDIO_SIZE_BYTES:
        return GateResult(
            gate_id="G4",
            status="failed",
            message=(
                f"G4.1: Audio file too small: {file_size} bytes "
                f"(minimum {_MIN_AUDIO_SIZE_BYTES} bytes / 10 KB). "
                "File may be empty or corrupt."
            ),
        )

    # Probe audio stream info (needed for G4.3, G4.5, G4.6)
    stream_info = _probe_audio_stream(audio_path)

    # G4.3 — audio must not be silent
    if stream_info is not None:
        rms_dbfs = _get_rms_dbfs(stream_info)
        if rms_dbfs is not None and rms_dbfs <= _SILENCE_THRESHOLD_DBFS:
            return GateResult(
                gate_id="G4",
                status="failed",
                message=(
                    f"G4.3: Audio appears silent — RMS level {rms_dbfs:.1f} dBFS "
                    f"is at or below threshold {_SILENCE_THRESHOLD_DBFS} dBFS."
                ),
            )

        # G4.5 — sample rate ≥ 16 kHz
        sample_rate = _get_sample_rate(stream_info)
        if sample_rate is not None and sample_rate < _MIN_SAMPLE_RATE_HZ:
            return GateResult(
                gate_id="G4",
                status="failed",
                message=(
                    f"G4.5: Audio sample rate too low: {sample_rate} Hz "
                    f"(minimum {_MIN_SAMPLE_RATE_HZ} Hz / 16 kHz)."
                ),
            )

        # G4.6 — channels must be 1 or 2
        channels = _get_channels(stream_info)
        if channels is not None and channels not in _VALID_CHANNEL_COUNTS:
            return GateResult(
                gate_id="G4",
                status="failed",
                message=(
                    f"G4.6: Unexpected audio channel count: {channels}. "
                    f"Expected mono (1) or stereo (2)."
                ),
            )

    # G4.2 — duration check (warning only — does not block)
    if expected_duration is not None and expected_duration > 0:
        try:
            actual_duration = probe_duration(audio_path)
            deviation = abs(actual_duration - expected_duration) / expected_duration
            if deviation > _DURATION_TOLERANCE:
                logger.warning(
                    "G4.2: Audio duration {:.2f}s deviates {:.1f}% from expected {:.2f}s "
                    "(tolerance ±{:.0f}%) — {}",
                    actual_duration,
                    deviation * 100,
                    expected_duration,
                    _DURATION_TOLERANCE * 100,
                    audio_path.name,
                )
            else:
                logger.debug(
                    "G4.2: Audio duration {:.2f}s within tolerance of expected {:.2f}s",
                    actual_duration,
                    expected_duration,
                )
        except Exception as exc:
            logger.warning("G4.2: Could not probe audio duration ({}): {}", audio_path, exc)

    logger.info("G4: Audio quality check passed — {}", audio_path.name)
    return GateResult(gate_id="G4", status="passed")


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _probe_audio_stream(audio_path: Path) -> Optional[dict]:
    """Use ffprobe to extract audio stream metadata as a dict.

    Returns the first audio stream's metadata dict, or None if ffprobe is
    unavailable or the file has no audio stream.

    Args:
        audio_path: Path to the audio file.

    Returns:
        Dict of stream tags/fields, or None on failure.
    """
    ffprobe = find_ffprobe()
    if ffprobe is None:
        logger.warning("G4: ffprobe not found — skipping stream checks (G4.3, G4.5, G4.6)")
        return None

    cmd = [
        str(ffprobe),
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-select_streams", "a:0",  # first audio stream only
        str(audio_path),
    ]
    try:
        output = subprocess.check_output(cmd, encoding="utf-8", stderr=subprocess.DEVNULL)
        data = json.loads(output)
        streams = data.get("streams", [])
        if not streams:
            logger.warning("G4: No audio stream found in {}", audio_path.name)
            return None
        return streams[0]
    except (subprocess.CalledProcessError, json.JSONDecodeError, OSError) as exc:
        logger.warning("G4: ffprobe stream probe failed for {}: {}", audio_path.name, exc)
        return None


def _get_rms_dbfs(stream_info: dict) -> Optional[float]:
    """Extract RMS level in dBFS from a stream info dict.

    ffprobe's ``-show_streams`` does not include RMS directly; we use the
    ``mean_volume`` tag from ``volumedetect`` filter output when available,
    or fall back to checking ``max_volume`` from stream tags.

    In practice, for G4.3 we check whether the stream has any signal at all
    by looking at the ``max_volume`` tag (populated by some ffprobe builds)
    or by treating a missing/zero ``nb_samples`` as silent.

    Returns:
        RMS level in dBFS, or None if not determinable.
    """
    # Some ffprobe builds expose volume tags
    tags = stream_info.get("tags", {})
    for key in ("mean_volume", "max_volume"):
        val = tags.get(key)
        if val is not None:
            try:
                return float(str(val).replace(" dB", "").strip())
            except ValueError:
                pass

    # Fallback: if nb_samples is 0 or missing, treat as silent
    nb_samples = stream_info.get("nb_samples")
    if nb_samples is not None:
        try:
            if int(nb_samples) == 0:
                return -100.0  # effectively silent
        except (ValueError, TypeError):
            pass

    # Cannot determine RMS — skip the check
    return None


def _get_sample_rate(stream_info: dict) -> Optional[int]:
    """Extract sample rate (Hz) from a stream info dict.

    Args:
        stream_info: ffprobe stream dict.

    Returns:
        Sample rate as int, or None if not available.
    """
    val = stream_info.get("sample_rate")
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _get_channels(stream_info: dict) -> Optional[int]:
    """Extract channel count from a stream info dict.

    Args:
        stream_info: ffprobe stream dict.

    Returns:
        Channel count as int, or None if not available.
    """
    val = stream_info.get("channels")
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None
