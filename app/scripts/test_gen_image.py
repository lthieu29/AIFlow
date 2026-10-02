"""Smoke test for gen_image — Phase 0 Task 0.5.

Usage:
    python scripts/test_gen_image.py

Prerequisites:
    1. Agent server running: python -m server.main
    2. AIFlow Bridge extension installed and enabled in Chrome
    3. Navigate to https://labs.google/fx/tools/flow (to capture Bearer token)

The script waits for the extension to connect and a Bearer token to be
captured, then calls gen_image() with a simple test prompt and asserts
the output file exists and is > 50 KB.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Ensure the project root is on sys.path when run as a script
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


async def main() -> None:
    from server.flow.client import FlowClient
    from server.flow.sdk import FlowSDK

    print("=" * 60)
    print("AIFlow — gen_image smoke test")
    print("=" * 60)

    flow_client = FlowClient()
    sdk = FlowSDK(client=flow_client)

    # Step 1: Wait for extension to connect
    print("\n[1/3] Waiting for AIFlow Bridge extension to connect...")
    print("      Make sure the extension is enabled in Chrome.")
    try:
        await flow_client.wait_for_extension(timeout=60.0)
        print("      [OK] Extension connected")
    except TimeoutError as exc:
        print(f"      [FAIL] {exc}")
        sys.exit(1)

    # Step 2: Wait for Bearer token
    print("\n[2/3] Waiting for Bearer token...")
    print("      Navigate to https://labs.google/fx/tools/flow to trigger capture.")
    try:
        token = await flow_client.wait_for_token(timeout=120.0)
        print(f"      [OK] Token captured (length={len(token)})")
    except TimeoutError as exc:
        print(f"      [FAIL] {exc}")
        sys.exit(1)

    # Step 3: Generate image
    print("\n[3/3] Generating image...")
    print("      Prompt: 'A simple red cube on white background'")
    print("      Model: GEM_PIX_2 | Aspect: 9:16")
    print("      (This may take 30-60 seconds -- reCAPTCHA + image gen)")

    try:
        out_path = await sdk.gen_image(
            prompt="A simple red cube on white background",
            model="GEM_PIX_2",
            aspect="9:16",
        )
    except RuntimeError as exc:
        print(f"\n      [FAIL] gen_image failed: {exc}")
        sys.exit(1)
    except TimeoutError as exc:
        print(f"\n      [FAIL] Timed out: {exc}")
        sys.exit(1)

    # Assertions
    assert out_path.exists(), f"Output file does not exist: {out_path}"
    file_size = out_path.stat().st_size
    assert file_size > 50 * 1024, (
        f"Output file too small: {file_size} bytes (expected > 51200)"
    )

    print(f"\n      [OK] Image saved: {out_path}")
    print(f"      [OK] File size: {file_size:,} bytes ({file_size / 1024:.1f} KB)")

    print("\n" + "=" * 60)
    print("gen_image smoke test PASSED")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
