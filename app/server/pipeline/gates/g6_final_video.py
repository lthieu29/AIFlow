"""G6 — Final video quality check gate.

Phase 2.5 implementation: validates the composed MP4 before delivery
(pipeline step 13 — after composer.py produces final.mp4).

Checks performed (per spec 07 §G6):
    G6.1 — File size sanity: > 500 KB
    G6.2 — Duration check: actual duration within ±2s of expected duration
    G6.3 — Resolution check: width/height match project aspect ratio
            (9:16 → 1080×1920, 16:9 → 1920×1080, 1:1 → 1080×1080)
    G6.4 — Audio stream present: at least 1 audio stream detected
    G6.5 — No black frames: sample 5 frames at 20/40/60/80/100% of duration,
            reject if ALL sampled frames are black (mean brightness < 5)

Critical failures (G6.1, G6.3, G6.4, G6.5) block the pipeline.
Duration check (G6.2) is critical when expected_duration is provided.

Manual override: pass ``override=True`` to skip all checks and return passed.

Classes:
    G6FinalVideoGate — stateless gate class with check() method

Functions:
    check_final_video — module-level convenience wrapper
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from loguru import logger

from server.pipeline.quality_gate import GateResult
from server.render.ffmpeg_utils import find_ffmpeg, find_ffprobe

# ─── Constants ────────────────────────────────────────────────────────────────

# G6.1 — minimum file size
_MIN_FILE_SIZE_BYTES: int = 500 * 1024  # 500 KB

# G6.2 — acceptable duration deviation (±2 seconds absolute)
_DURATION_TOLERANCE_SEC: float = 2.0

# G6.5 — black frame brightness threshold (mean pixel value 0–255)
_BLACK_FRAME_BRIGHTNESS_THRESHOLD: float = 5.0

# G6.5 — number of frames to sample for black-frame detection
_BLACK_FRAME_SAMPLE_COUNT: int = 5

# G6.3 — expected resolutions per aspect ratio (width × height)
_ASPECT_RATIO_RESOLUTIONS: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
}


# ─── Gate class ───────────────────────────────────────────────────────────────

class G6FinalVideoGate:
    """Final video quality gate — validates the composed MP4 before delivery.

    The gate is stateless; each call to ``check()`` is independent.

    Usage::

        gate = G6FinalVideoGate()
        result = gate.check(
            output_path="storage/output/42/final.mp4",
            expected_duration=30.0,
            aspect_ratio="9:16",
        )
        if not result.passed:
            print(result.error)
    """

    def check(
        self,
        output_path: "str | Path",
        expected_duration: Optional[float] = None,
        aspect_ratio: Optional[str] = None,
        override: bool = False,
    ) -> "G6Result":
        """Run G6 quality checks on the composed MP4.

        Args:
            output_path:       Path to the final.mp4 file to validate.
            expected_duration: Expected total duration in seconds (used for
                               G6.2 duration check). If None, G6.2 is skipped.
            aspect_ratio:      Project aspect ratio string, e.g. "9:16", "16:9",
                               "1:1". If None, G6.3 resolution check is skipped.
            override:          If True, skip all checks and return passed.
                               Useful for manual user acceptance.

        Returns:
            G6Result with passed, score, details, and error fields.
        """
        output_path = Path(output_path)

        # ── Manual override ───────────────────────────────────────────────────
        if override:
            logger.info("G6: manual override — skipping all checks for {}", output_path.name)
            return G6Result(
                passed=True,
                score=1.0,
                details={"override": True},
                error=None,
            )

        details: dict = {}
        checks_passed = 0
        checks_total = 0

        # ── G6.1 — file size sanity ───────────────────────────────────────────
        checks_total += 1
        if not output_path.exists():
            return G6Result(
                passed=False,
                score=0.0,
                details={"file_exists": False},
                error=f"G6.1: Output file not found: {output_path}",
            )

        file_size = output_path.stat().st_size
        details["file_size_bytes"] = file_size
        if file_size <= _MIN_FILE_SIZE_BYTES:
            return G6Result(
                passed=False,
                score=0.0,
                details=details,
                error=(
                    f"G6.1: File too small: {file_size} bytes "
                    f"(minimum {_MIN_FILE_SIZE_BYTES} bytes / 500 KB). "
                    "File may be empty or corrupt."
                ),
            )
        checks_passed += 1
        logger.debug("G6.1: file size OK — {} bytes", file_size)

        # ── Probe video/audio streams via ffprobe ─────────────────────────────
        probe_data = _probe_video(output_path)
        if probe_data is None:
            logger.warning(
                "G6: ffprobe not available — skipping stream checks (G6.2, G6.3, G6.4)"
            )
        else:
            video_stream = _get_video_stream(probe_data)
            audio_streams = _get_audio_streams(probe_data)
            format_info = probe_data.get("format", {})

            # ── G6.2 — duration check ─────────────────────────────────────────
            if expected_duration is not None and expected_duration > 0:
                checks_total += 1
                actual_duration = _get_duration(format_info, video_stream)
                details["actual_duration_sec"] = actual_duration
                details["expected_duration_sec"] = expected_duration
                if actual_duration is not None:
                    deviation = abs(actual_duration - expected_duration)
                    details["duration_deviation_sec"] = round(deviation, 3)
                    if deviation > _DURATION_TOLERANCE_SEC:
                        return G6Result(
                            passed=False,
                            score=checks_passed / checks_total,
                            details=details,
                            error=(
                                f"G6.2: Duration mismatch — actual {actual_duration:.2f}s "
                                f"vs expected {expected_duration:.2f}s "
                                f"(deviation {deviation:.2f}s > tolerance ±{_DURATION_TOLERANCE_SEC}s)."
                            ),
                        )
                    checks_passed += 1
                    logger.debug(
                        "G6.2: duration OK — actual={:.2f}s expected={:.2f}s deviation={:.2f}s",
                        actual_duration,
                        expected_duration,
                        deviation,
                    )
                else:
                    logger.warning("G6.2: could not determine video duration — skipping check")

            # ── G6.3 — resolution check ───────────────────────────────────────
            if aspect_ratio is not None and video_stream is not None:
                checks_total += 1
                width = _get_int(video_stream, "width")
                height = _get_int(video_stream, "height")
                details["actual_width"] = width
                details["actual_height"] = height
                details["aspect_ratio"] = aspect_ratio

                expected_res = _ASPECT_RATIO_RESOLUTIONS.get(aspect_ratio)
                if expected_res is not None:
                    exp_w, exp_h = expected_res
                    details["expected_width"] = exp_w
                    details["expected_height"] = exp_h
                    if width != exp_w or height != exp_h:
                        return G6Result(
                            passed=False,
                            score=checks_passed / checks_total,
                            details=details,
                            error=(
                                f"G6.3: Resolution mismatch — actual {width}×{height} "
                                f"vs expected {exp_w}×{exp_h} for aspect ratio {aspect_ratio!r}."
                            ),
                        )
                    checks_passed += 1
                    logger.debug(
                        "G6.3: resolution OK — {}×{} for aspect ratio {}",
                        width,
                        height,
                        aspect_ratio,
                    )
                else:
                    logger.warning(
                        "G6.3: unknown aspect ratio {!r} — skipping resolution check",
                        aspect_ratio,
                    )

            # ── G6.4 — audio stream present ───────────────────────────────────
            checks_total += 1
            audio_count = len(audio_streams)
            details["audio_stream_count"] = audio_count
            if audio_count < 1:
                return G6Result(
                    passed=False,
                    score=checks_passed / checks_total,
                    details=details,
                    error="G6.4: No audio stream detected in the output video.",
                )
            checks_passed += 1
            logger.debug("G6.4: audio stream OK — {} stream(s) found", audio_count)

        # ── G6.5 — no black frames ────────────────────────────────────────────
        checks_total += 1
        black_frame_result = _check_black_frames(output_path, probe_data)
        details["black_frame_check"] = black_frame_result
        if black_frame_result.get("all_black", False):
            sampled = black_frame_result.get("sampled_brightnesses", [])
            return G6Result(
                passed=False,
                score=checks_passed / checks_total,
                details=details,
                error=(
                    f"G6.5: All {len(sampled)} sampled frames appear black "
                    f"(mean brightness < {_BLACK_FRAME_BRIGHTNESS_THRESHOLD}). "
                    f"Sampled brightnesses: {sampled}."
                ),
            )
        checks_passed += 1
        logger.debug("G6.5: black frame check OK — {}", black_frame_result)

        # ── All checks passed ─────────────────────────────────────────────────
        score = checks_passed / checks_total if checks_total > 0 else 1.0
        logger.info(
            "G6: Final video quality check passed — {} ({}/{} checks)",
            output_path.name,
            checks_passed,
            checks_total,
        )
        return G6Result(passed=True, score=score, details=details, error=None)


# ─── Result dataclass ─────────────────────────────────────────────────────────

from dataclasses import dataclass, field as _field


@dataclass
class G6Result:
    """Result of the G6 final video quality gate.

    Attributes:
        passed:  True if all checks passed (or override=True).
        score:   Float 0–1 representing fraction of checks passed.
        details: Dict of per-check metadata (sizes, durations, etc.).
        error:   Human-readable error message, or None on success.
    """
    passed: bool
    score: float
    details: dict = _field(default_factory=dict)
    error: Optional[str] = None

    def to_gate_result(self, gate_id: str = "G6") -> GateResult:
        """Convert to the standard GateResult used by the pipeline.

        Args:
            gate_id: Gate identifier string (default "G6").

        Returns:
            GateResult compatible with the rest of the pipeline.
        """
        return GateResult(
            gate_id=gate_id,
            status="passed" if self.passed else "failed",
            message=self.error or "",
        )


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _probe_video(video_path: Path) -> Optional[dict]:
    """Use ffprobe to extract full stream + format metadata as a dict.

    Args:
        video_path: Path to the video file.

    Returns:
        Dict with "streams" and "format" keys, or None if ffprobe is
        unavailable or the probe fails.
    """
    ffprobe = find_ffprobe()
    if ffprobe is None:
        logger.warning("G6: ffprobe not found — stream checks will be skipped")
        return None

    cmd = [
        str(ffprobe),
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        str(video_path),
    ]
    try:
        output = subprocess.check_output(cmd, encoding="utf-8", stderr=subprocess.DEVNULL)
        return json.loads(output)
    except (subprocess.CalledProcessError, json.JSONDecodeError, OSError) as exc:
        logger.warning("G6: ffprobe probe failed for {}: {}", video_path.name, exc)
        return None


def _get_video_stream(probe_data: dict) -> Optional[dict]:
    """Return the first video stream from probe data, or None."""
    for stream in probe_data.get("streams", []):
        if stream.get("codec_type") == "video":
            return stream
    return None


def _get_audio_streams(probe_data: dict) -> list[dict]:
    """Return all audio streams from probe data."""
    return [
        s for s in probe_data.get("streams", [])
        if s.get("codec_type") == "audio"
    ]


def _get_duration(format_info: dict, video_stream: Optional[dict]) -> Optional[float]:
    """Extract duration in seconds from format or stream info.

    Prefers format-level duration (more reliable for MP4 containers).

    Args:
        format_info:  ffprobe format dict.
        video_stream: ffprobe video stream dict (fallback).

    Returns:
        Duration as float, or None if not determinable.
    """
    # Try format-level duration first
    val = format_info.get("duration")
    if val is not None:
        try:
            return float(val)
        except (ValueError, TypeError):
            pass

    # Fallback: video stream duration
    if video_stream is not None:
        val = video_stream.get("duration")
        if val is not None:
            try:
                return float(val)
            except (ValueError, TypeError):
                pass

    return None


def _get_int(d: dict, key: str) -> Optional[int]:
    """Safely extract an integer value from a dict."""
    val = d.get(key)
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _check_black_frames(
    video_path: Path,
    probe_data: Optional[dict],
) -> dict:
    """Sample frames at regular intervals and check for black content.

    Samples ``_BLACK_FRAME_SAMPLE_COUNT`` frames at 20/40/60/80/100% of the
    video duration.  A frame is considered black if its mean pixel brightness
    (0–255 scale) is below ``_BLACK_FRAME_BRIGHTNESS_THRESHOLD``.

    If ALL sampled frames are black, the check fails.

    Args:
        video_path:  Path to the video file.
        probe_data:  ffprobe output dict (used to get duration). May be None.

    Returns:
        Dict with keys:
            - "all_black": bool — True if all frames are black
            - "sampled_brightnesses": list[float] — brightness per frame
            - "skipped": bool — True if check was skipped (no ffmpeg/duration)
    """
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        logger.warning("G6.5: ffmpeg not found — skipping black frame check")
        return {"all_black": False, "skipped": True, "reason": "ffmpeg not found"}

    # Determine video duration
    duration: Optional[float] = None
    if probe_data is not None:
        format_info = probe_data.get("format", {})
        video_stream = _get_video_stream(probe_data)
        duration = _get_duration(format_info, video_stream)

    if duration is None or duration <= 0:
        logger.warning("G6.5: could not determine video duration — skipping black frame check")
        return {"all_black": False, "skipped": True, "reason": "duration unknown"}

    # Calculate sample timestamps at 20/40/60/80/100% of duration
    sample_positions = [
        duration * pct / 100.0
        for pct in (20, 40, 60, 80, 100)
    ]
    # Clamp last sample to slightly before end to avoid EOF issues
    sample_positions[-1] = min(sample_positions[-1], duration - 0.1)
    sample_positions = [max(0.0, t) for t in sample_positions]

    brightnesses: list[float] = []

    with tempfile.TemporaryDirectory() as tmpdir:
        for i, timestamp in enumerate(sample_positions):
            frame_path = Path(tmpdir) / f"frame_{i:02d}.png"
            cmd = [
                str(ffmpeg),
                "-y",
                "-ss", f"{timestamp:.3f}",
                "-i", str(video_path),
                "-frames:v", "1",
                "-vf", "scale=64:64",  # downscale for fast processing
                str(frame_path),
            ]
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    timeout=30,
                )
                if result.returncode != 0 or not frame_path.exists():
                    logger.debug(
                        "G6.5: frame extraction failed at t={:.2f}s (rc={})",
                        timestamp,
                        result.returncode,
                    )
                    continue

                # Measure mean brightness using ffprobe signalstats
                brightness = _measure_frame_brightness(frame_path, ffmpeg)
                if brightness is not None:
                    brightnesses.append(brightness)
                    logger.debug(
                        "G6.5: frame at t={:.2f}s brightness={:.2f}",
                        timestamp,
                        brightness,
                    )
            except (subprocess.TimeoutExpired, OSError) as exc:
                logger.warning("G6.5: frame extraction error at t={:.2f}s: {}", timestamp, exc)

    if not brightnesses:
        logger.warning("G6.5: no frames could be sampled — skipping black frame check")
        return {"all_black": False, "skipped": True, "reason": "no frames sampled"}

    all_black = all(b < _BLACK_FRAME_BRIGHTNESS_THRESHOLD for b in brightnesses)
    return {
        "all_black": all_black,
        "sampled_brightnesses": [round(b, 2) for b in brightnesses],
        "skipped": False,
    }


def _measure_frame_brightness(frame_path: Path, ffmpeg_bin: Path) -> Optional[float]:
    """Measure the mean brightness of a PNG frame using FFmpeg signalstats.

    Uses ``ffmpeg -vf signalstats`` to extract the YAVG (luma average) value,
    which represents mean brightness on a 0–255 scale.

    Args:
        frame_path: Path to the PNG frame file.
        ffmpeg_bin: Path to the ffmpeg binary.

    Returns:
        Mean brightness as float (0–255), or None if measurement fails.
    """
    cmd = [
        str(ffmpeg_bin),
        "-i", str(frame_path),
        "-vf", "signalstats",
        "-f", "null",
        "-",
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            encoding="utf-8",
            timeout=15,
        )
        # signalstats outputs to stderr; look for YAVG line
        stderr = result.stderr
        for line in stderr.splitlines():
            if "YAVG" in line:
                # Format: "... YAVG:12.34 ..."
                parts = line.split("YAVG:")
                if len(parts) >= 2:
                    val_str = parts[1].split()[0]
                    try:
                        return float(val_str)
                    except ValueError:
                        pass
        return None
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.debug("G6.5: brightness measurement failed for {}: {}", frame_path.name, exc)
        return None


# ─── Module-level convenience function ───────────────────────────────────────

def check_final_video(
    output_path: "str | Path",
    expected_duration: Optional[float] = None,
    aspect_ratio: Optional[str] = None,
    override: bool = False,
) -> G6Result:
    """Convenience wrapper — create a G6FinalVideoGate and run check().

    Args:
        output_path:       Path to the final.mp4 file to validate.
        expected_duration: Expected total duration in seconds (G6.2).
        aspect_ratio:      Project aspect ratio string, e.g. "9:16" (G6.3).
        override:          If True, skip all checks and return passed.

    Returns:
        G6Result with passed, score, details, and error fields.
    """
    return G6FinalVideoGate().check(
        output_path=output_path,
        expected_duration=expected_duration,
        aspect_ratio=aspect_ratio,
        override=override,
    )
