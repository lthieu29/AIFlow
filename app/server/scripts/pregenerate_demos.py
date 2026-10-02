"""Pre-generate TTS demo files for the 5 preset voices.

After running this script, every preset voice in ``voice_catalog.py`` has a
playable demo MP3 at ``storage/voice_gallery/{voice_id}/demo.mp3`` so the
VoiceGallery UI can preview the voice without re-synthesising on every load.

The script is idempotent: existing demos are skipped unless ``--force`` is
passed. Synthesis goes through ``TTSService`` so each preset uses the same
provider chain (vieneu primary, edge_tts fallback) the runtime uses.

Usage::

    python -m server.scripts.pregenerate_demos
    python -m server.scripts.pregenerate_demos --force
    python -m server.scripts.pregenerate_demos --voice Binh --voice Lan

Exit codes:
    0 — every requested voice produced a demo (or already had one)
    1 — at least one voice failed (the rest still wrote what they could)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from loguru import logger

from server.audio.tts.voice_catalog import PRESET_VOICE_METADATA, VoiceInfo

# Sample line per voice — short (≈8-12 s when spoken) and locale-appropriate.
_SAMPLE_TEXT: dict[str, str] = {
    "Binh": "Xin chào, tôi là giọng đọc Bình. Hôm nay là một ngày đẹp trời để kể câu chuyện của bạn.",
    "Lan": "Xin chào, tôi là giọng đọc Lan. Hôm nay là một ngày đẹp trời để kể câu chuyện của bạn.",
    "Nam": "Xin chào, tôi là giọng đọc Nam. Hôm nay là một ngày đẹp trời để kể câu chuyện của bạn.",
    "vi-VN-HoaiMyNeural": "Xin chào, tôi là Hoài My. Tôi rất vui được kể câu chuyện cùng bạn hôm nay.",
    "vi-VN-NamMinhNeural": "Xin chào, tôi là Nam Minh. Tôi rất vui được kể câu chuyện cùng bạn hôm nay.",
}

_DEFAULT_TEXT = (
    "Xin chào, đây là bản giọng đọc thử cho dự án AIFlow."
)

_GALLERY_SUBDIR = "voice_gallery"


def _resolve_demo_path(data_dir: Path, voice_id: str) -> Path:
    """Return ``{data_dir}/voice_gallery/{voice_id}/demo.mp3``."""
    return data_dir / _GALLERY_SUBDIR / voice_id / "demo.mp3"


def _generate_one(
    voice: VoiceInfo,
    out_path: Path,
    force: bool,
) -> tuple[bool, str]:
    """Generate the demo MP3 for *voice* at *out_path*.

    Returns ``(ok, detail)``.  ``ok=True`` covers both new generations and
    skipped-existing files; ``ok=False`` means the synthesis attempt failed
    and the demo is still missing.
    """
    from server.audio.tts.service import TTSService
    from server.config import load_settings

    if out_path.is_file() and not force:
        return True, f"đã có ({out_path.stat().st_size} B) — bỏ qua"

    out_path.parent.mkdir(parents=True, exist_ok=True)

    text = _SAMPLE_TEXT.get(voice.id, _DEFAULT_TEXT)
    settings = load_settings()
    service = TTSService(settings)

    try:
        result = service.synthesize(
            text=text,
            voice=voice.id,
            output_path=out_path,
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"synth thất bại: {exc}"

    size = out_path.stat().st_size if out_path.is_file() else 0
    if size <= 0:
        return False, f"file rỗng tại {out_path}"

    return True, (
        f"backend={result.backend} duration={result.duration_sec:.2f}s "
        f"size={size} B → {out_path}"
    )


def _select_voices(filter_ids: list[str]) -> list[VoiceInfo]:
    if not filter_ids:
        return list(PRESET_VOICE_METADATA)
    requested = {v.lower() for v in filter_ids}
    selected = [v for v in PRESET_VOICE_METADATA if v.id.lower() in requested]
    missing = requested - {v.id.lower() for v in selected}
    if missing:
        logger.warning(
            "[pregenerate_demos] voice id(s) không có trong preset: {}",
            ", ".join(sorted(missing)),
        )
    return selected


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint.  Returns the exit code."""
    parser = argparse.ArgumentParser(
        prog="pregenerate_demos",
        description="Pre-generate demo MP3 files for the 5 preset TTS voices.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing demos (default: skip when demo.mp3 exists).",
    )
    parser.add_argument(
        "--voice",
        action="append",
        default=[],
        metavar="VOICE_ID",
        help=(
            "Generate only the listed voice (case-insensitive). May be passed "
            "multiple times. Default: every preset voice."
        ),
    )
    args = parser.parse_args(argv)

    from server.config import load_settings

    settings = load_settings()
    data_dir = Path(settings.data_dir)
    voices = _select_voices(args.voice)
    if not voices:
        logger.error("[pregenerate_demos] no voices selected — nothing to do.")
        return 1

    logger.info(
        "[pregenerate_demos] generating demos for {} voice(s) into {}/{}",
        len(voices),
        data_dir,
        _GALLERY_SUBDIR,
    )

    failures = 0
    for voice in voices:
        out_path = _resolve_demo_path(data_dir, voice.id)
        ok, detail = _generate_one(voice, out_path, args.force)
        prefix = "OK " if ok else "FAIL"
        logger.info("[pregenerate_demos] {} {} ({}): {}", prefix, voice.id, voice.backend, detail)
        if not ok:
            failures += 1

    logger.info(
        "[pregenerate_demos] done — {}/{} voices ready ({} failed)",
        len(voices) - failures,
        len(voices),
        failures,
    )
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
