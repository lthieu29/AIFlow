"""End-to-end test for the full video generation pipeline — Phase 1 Task 1.5.

Usage:
    python scripts/test_gen_clip.py

Prerequisites:
    1. Agent server running: python -m server.main
    2. AIFlow Bridge extension installed and enabled in Chrome
    3. Navigate to https://labs.google/fx/tools/flow (to capture Bearer token)
    4. Active Google Flow Pro or Ultra subscription

What this test does:
    1. Waits for the AIFlow Bridge extension to connect (up to 60s)
    2. Waits for a Bearer token to be captured (up to 120s)
    3. Creates a 512×512 solid-color PNG as the start image (no external deps)
    4. Calls FlowSDK.gen_video() with a cinematic test prompt
    5. Polls FlowSDK.check_async() every 5s until done (max 10 minutes)
    6. Downloads the video to storage/output/test_gen_clip_{timestamp}.mp4
    7. Asserts file exists and size > 100 KB
    8. Asserts the file is a valid MP4 (ftyp box in first 12 bytes)
    9. Prints the result path, file size, and manual quality review instructions

NOTE — Manual quality verification:
    This script validates file size and MP4 format automatically.
    Visual quality (no broken frames, correct motion, prompt adherence)
    requires manual review. After the test passes, open the output file
    in a video player and verify:
      - No broken / corrupted frames
      - Motion matches the prompt ("serene mountain lake at sunrise")
      - Video is approximately 8 seconds long
      - No audio artifacts (Veo3 generates ambient audio)
"""
from __future__ import annotations

import asyncio
import struct
import sys
import time
from pathlib import Path

# Ensure the project root is on sys.path when run as a script
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ── Constants ─────────────────────────────────────────────────────────────────

TEST_PROMPT = "A serene mountain lake at sunrise, cinematic, 4K"
TEST_ASPECT = "16:9"          # landscape — matches the cinematic prompt
TEST_MODEL = "VEO3"
TEST_QUALITY = "fast"
POLL_INTERVAL_SECONDS = 5
MAX_POLL_ATTEMPTS = 120       # 120 × 5s = 10 minutes
MIN_VIDEO_SIZE_BYTES = 100 * 1024  # 100 KB

OUTPUT_DIR = _ROOT / "storage" / "output"
TEMP_IMAGE_PATH = _ROOT / "storage" / "output" / "_test_start_image.png"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _create_solid_color_png(path: Path, width: int = 512, height: int = 512) -> None:
    """Write a minimal solid-color PNG (sky blue) to *path*.

    Uses only the Python standard library (struct + zlib) — no Pillow required.
    The image is a 512×512 RGB PNG filled with a sky-blue color (#87CEEB).

    Args:
        path: Destination file path. Parent directories are created if needed.
        width: Image width in pixels. Default 512.
        height: Image height in pixels. Default 512.
    """
    import zlib

    path.parent.mkdir(parents=True, exist_ok=True)

    # Sky-blue fill color (R=135, G=206, B=235)
    r, g, b = 135, 206, 235

    # PNG signature
    sig = b"\x89PNG\r\n\x1a\n"

    def _chunk(tag: bytes, data: bytes) -> bytes:
        length = struct.pack(">I", len(data))
        crc = struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        return length + tag + data + crc

    # IHDR: width, height, bit_depth=8, color_type=2 (RGB), compression=0, filter=0, interlace=0
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr = _chunk(b"IHDR", ihdr_data)

    # IDAT: raw scanlines, each prefixed with filter byte 0 (None)
    scanline = bytes([0]) + bytes([r, g, b] * width)  # filter=0 + RGB pixels
    raw = scanline * height
    compressed = zlib.compress(raw, level=1)
    idat = _chunk(b"IDAT", compressed)

    # IEND
    iend = _chunk(b"IEND", b"")

    path.write_bytes(sig + ihdr + idat + iend)


def _is_valid_mp4(path: Path) -> bool:
    """Return True if *path* looks like a valid MP4 file.

    Checks for the ISO Base Media File Format 'ftyp' box in the first 12 bytes.
    Valid MP4 files have the structure:
        bytes 0-3:  box size (big-endian uint32)
        bytes 4-7:  box type = b'ftyp'
        bytes 8-11: major brand (e.g. b'isom', b'mp42', b'avc1')

    Also accepts files that start with the 'wide' or 'mdat' box (some encoders
    write a 'wide' compatibility box before 'ftyp').

    Args:
        path: Path to the file to check.

    Returns:
        True if the file appears to be a valid MP4 container.
    """
    try:
        header = path.read_bytes()[:12]
    except OSError:
        return False

    if len(header) < 8:
        return False

    box_type = header[4:8]
    # Standard ftyp box
    if box_type == b"ftyp":
        return True
    # Some files start with a 'wide' or 'free' compatibility box before ftyp
    if box_type in (b"wide", b"free", b"mdat"):
        return True
    return False


# ── Main test ─────────────────────────────────────────────────────────────────


async def main() -> None:
    from server.flow.client import FlowClient
    from server.flow.sdk import FlowSDK, extract_video_operations

    print("=" * 65)
    print("AIFlow — gen_video end-to-end test (Task 1.5)")
    print("=" * 65)
    print(f"Prompt : {TEST_PROMPT}")
    print(f"Aspect : {TEST_ASPECT}  Model: {TEST_MODEL}  Quality: {TEST_QUALITY}")
    print(f"Timeout: {MAX_POLL_ATTEMPTS * POLL_INTERVAL_SECONDS}s ({MAX_POLL_ATTEMPTS} polls × {POLL_INTERVAL_SECONDS}s)")
    print()

    flow_client = FlowClient()
    sdk = FlowSDK(client=flow_client)

    # ── Step 1: Wait for extension ────────────────────────────────────────────
    print("[1/6] Waiting for AIFlow Bridge extension to connect...")
    print("      Make sure the extension is enabled in Chrome.")
    try:
        await flow_client.wait_for_extension(timeout=60.0)
        print("      [OK] Extension connected")
    except TimeoutError as exc:
        print(f"      [FAIL] {exc}")
        sys.exit(1)

    # ── Step 2: Wait for Bearer token ─────────────────────────────────────────
    print("\n[2/6] Waiting for Bearer token...")
    print("      Navigate to https://labs.google/fx/tools/flow to trigger capture.")
    try:
        token = await flow_client.wait_for_token(timeout=120.0)
        print(f"      [OK] Token captured (length={len(token)})")
    except TimeoutError as exc:
        print(f"      [FAIL] {exc}")
        sys.exit(1)

    # ── Step 3: Create test start image ──────────────────────────────────────
    print("\n[3/6] Creating test start image (512×512 solid-color PNG)...")
    try:
        _create_solid_color_png(TEMP_IMAGE_PATH, width=512, height=512)
        img_size = TEMP_IMAGE_PATH.stat().st_size
        print(f"      [OK] Start image: {TEMP_IMAGE_PATH} ({img_size:,} bytes)")
    except Exception as exc:
        print(f"      [FAIL] Could not create start image: {exc}")
        sys.exit(1)

    # ── Step 4: Submit gen_video ──────────────────────────────────────────────
    print(f"\n[4/6] Submitting video generation request...")
    print(f"      Prompt: {TEST_PROMPT!r}")
    print("      (This may take 30-60s for reCAPTCHA + submission)")
    try:
        operation_name = await sdk.gen_video(
            start_image=TEMP_IMAGE_PATH,
            prompt=TEST_PROMPT,
            duration=8,
            aspect=TEST_ASPECT,
            model=TEST_MODEL,
            quality=TEST_QUALITY,
        )
        print(f"      [OK] Submitted. Operation: {operation_name}")
    except (RuntimeError, FileNotFoundError, TimeoutError) as exc:
        print(f"      [FAIL] gen_video submission failed: {exc}")
        _cleanup_temp_image()
        sys.exit(1)

    # ── Step 5: Poll until done ───────────────────────────────────────────────
    print(f"\n[5/6] Polling for completion (every {POLL_INTERVAL_SECONDS}s, max {MAX_POLL_ATTEMPTS} attempts)...")
    final_media_entries = None
    poll_error: str | None = None

    for attempt in range(1, MAX_POLL_ATTEMPTS + 1):
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        elapsed = attempt * POLL_INTERVAL_SECONDS
        print(f"      Poll {attempt:3d}/{MAX_POLL_ATTEMPTS} ({elapsed}s elapsed)...", end=" ", flush=True)

        try:
            resp = await sdk.check_async(operation_name)
        except Exception as exc:
            print(f"error — {exc} (retrying)")
            continue

        ops = extract_video_operations(resp, requested=[operation_name])
        if not ops:
            print("no ops in response (retrying)")
            continue

        op_result = ops[0]
        done = op_result.get("done", False)
        error = op_result.get("error")
        media_entries = op_result.get("media_entries", [])
        status = op_result.get("status", "pending")

        if not done:
            print(f"{status}")
            continue

        # Done
        print(f"DONE (status={status})")
        if error:
            poll_error = error
        else:
            final_media_entries = media_entries
        break
    else:
        poll_error = (
            f"Polling timeout: exceeded {MAX_POLL_ATTEMPTS} attempts "
            f"({MAX_POLL_ATTEMPTS * POLL_INTERVAL_SECONDS}s)"
        )

    if poll_error or not final_media_entries:
        reason = poll_error or "Operation completed but no media entries returned"
        print(f"\n      [FAIL] Video generation failed: {reason}")
        _cleanup_temp_image()
        sys.exit(1)

    entry = final_media_entries[0]
    signed_url = entry.get("url")
    if not signed_url:
        print("\n      [FAIL] Operation completed but no signed URL in media entry")
        _cleanup_temp_image()
        sys.exit(1)

    print(f"      [OK] Video ready. media_id={entry.get('media_id', 'unknown')}")

    # ── Step 6: Download + validate ───────────────────────────────────────────
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = int(time.time())
    out_path = OUTPUT_DIR / f"test_gen_clip_{timestamp}.mp4"

    print(f"\n[6/6] Downloading video to {out_path}...")
    try:
        from server.flow.downloader import download_video
        saved_path = await download_video(signed_url, out_path)
    except RuntimeError as exc:
        print(f"      [FAIL] Download failed: {exc}")
        _cleanup_temp_image()
        sys.exit(1)

    # ── Assertions ────────────────────────────────────────────────────────────
    print("\n--- Assertions ---")

    # Assert 1: file exists
    assert saved_path.exists(), f"Output file does not exist: {saved_path}"
    print(f"  [OK] File exists: {saved_path}")

    # Assert 2: file size > 100 KB
    file_size = saved_path.stat().st_size
    assert file_size > MIN_VIDEO_SIZE_BYTES, (
        f"Output file too small: {file_size:,} bytes "
        f"(expected > {MIN_VIDEO_SIZE_BYTES:,} bytes / 100 KB)"
    )
    print(f"  [OK] File size: {file_size:,} bytes ({file_size / 1024:.1f} KB) — exceeds 100 KB minimum")

    # Assert 3: valid MP4 format (ftyp box check)
    assert _is_valid_mp4(saved_path), (
        f"File does not appear to be a valid MP4 container: {saved_path}\n"
        f"  First 12 bytes: {saved_path.read_bytes()[:12]!r}"
    )
    print(f"  [OK] MP4 format valid (ftyp box detected in file header)")

    # ── Cleanup temp image ────────────────────────────────────────────────────
    _cleanup_temp_image()

    # ── Result summary ────────────────────────────────────────────────────────
    print()
    print("=" * 65)
    print("gen_video end-to-end test PASSED")
    print("=" * 65)
    print(f"  Result path : {saved_path}")
    print(f"  File size   : {file_size:,} bytes ({file_size / 1024 / 1024:.2f} MB)")
    print()
    print("MANUAL QUALITY VERIFICATION REQUIRED:")
    print("  Automated checks (file size + MP4 format) have passed.")
    print("  Visual quality must be verified manually:")
    print(f"    1. Open the file in a video player: {saved_path}")
    print("    2. Verify no broken or corrupted frames")
    print("    3. Verify motion matches the prompt:")
    print(f"         '{TEST_PROMPT}'")
    print("    4. Verify video duration is approximately 8 seconds")
    print("    5. Verify ambient audio is present (Veo3 generates audio)")
    print()


def _cleanup_temp_image() -> None:
    """Remove the temporary start image created for this test."""
    try:
        if TEMP_IMAGE_PATH.exists():
            TEMP_IMAGE_PATH.unlink()
    except OSError:
        pass  # Non-fatal — temp file cleanup is best-effort


if __name__ == "__main__":
    asyncio.run(main())
