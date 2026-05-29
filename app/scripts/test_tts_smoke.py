#!/usr/bin/env python
"""TTS smoke test for AIFlow — Vietnamese voice (edge_tts).

Loads settings from .env, creates a TTSService, synthesises a short
Vietnamese sentence with ``vi-VN-HoaiMyNeural``, and asserts the output
file exists and is larger than 1 KB.

Usage::

    cd app/
    python scripts/test_tts_smoke.py

Requirements:
    - .env file with AIFLOW_GEMINI_API_KEY set (required by Settings)
    - ``pip install edge_tts`` (or ``pip install -e .[dev]``)
    - Network access to speech.platform.bing.com:443
    - FFmpeg available on PATH or in vendor/ (for re-encoding + duration probe)
"""

import sys
from pathlib import Path

# Allow running from repo root or app/ directory
_app_dir = Path(__file__).resolve().parent.parent
if str(_app_dir) not in sys.path:
    sys.path.insert(0, str(_app_dir))

# Vietnamese test sentence
_TEST_TEXT = (
    "Xin chào, đây là AIFlow. "
    "Hệ thống tổng hợp giọng nói đang hoạt động."
)
_TEST_VOICE = "vi-VN-HoaiMyNeural"
_MIN_SIZE_BYTES = 1024  # 1 KB


def main() -> None:
    print("─── AIFlow TTS Smoke Test ───")
    print(f"  Voice : {_TEST_VOICE}")
    print(f"  Text  : {_TEST_TEXT!r}")
    print()

    # ── 1. Load settings ──────────────────────────────────────────────────────
    print("Loading settings from .env ...")
    try:
        from server.config import load_settings, ConfigError
        settings = load_settings()
    except Exception as exc:
        print(f"❌ Config error: {exc}", file=sys.stderr)
        sys.exit(1)
    print("  ✓ Settings loaded")

    # ── 2. Create TTSService ──────────────────────────────────────────────────
    print("\nCreating TTSService ...")
    try:
        from server.audio.tts.service import TTSService
        service = TTSService(settings)
    except Exception as exc:
        print(f"❌ Failed to create TTSService: {exc}", file=sys.stderr)
        sys.exit(1)
    print("  ✓ TTSService created")

    # ── 3. Synthesise ─────────────────────────────────────────────────────────
    print(f"\nSynthesising with voice={_TEST_VOICE!r} ...")
    try:
        from server.audio.tts import TTSError
        result = service.synthesize(_TEST_TEXT, voice=_TEST_VOICE)
    except TTSError as exc:
        print(f"❌ Synthesis failed: {exc.message} (backend={exc.backend})", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"❌ Unexpected error during synthesis: {exc}", file=sys.stderr)
        sys.exit(1)

    # ── 4. Assertions ─────────────────────────────────────────────────────────
    output_path: Path = result.output_path
    duration_sec: float = result.duration_sec

    print(f"\n  Output path : {output_path}")
    print(f"  Duration    : {duration_sec:.2f}s")

    # Assert file exists
    if not output_path.exists():
        print(f"❌ Output file does not exist: {output_path}", file=sys.stderr)
        sys.exit(1)
    print("  ✓ File exists")

    # Assert file size > 1 KB
    file_size = output_path.stat().st_size
    print(f"  File size   : {file_size:,} bytes")
    if file_size < _MIN_SIZE_BYTES:
        print(
            f"❌ File too small: {file_size} bytes < {_MIN_SIZE_BYTES} bytes minimum",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"  ✓ File size OK (> {_MIN_SIZE_BYTES} bytes)")

    # Assert duration is positive
    if duration_sec <= 0:
        print(f"❌ Duration invalid: {duration_sec:.2f}s", file=sys.stderr)
        sys.exit(1)
    print(f"  ✓ Duration OK ({duration_sec:.2f}s)")

    print(f"\n✅ TTS smoke test PASSED — {output_path}")
    sys.exit(0)


if __name__ == "__main__":
    main()
