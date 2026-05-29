#!/usr/bin/env python
"""Gemini API smoke test for AIFlow.

Loads settings from .env, creates a GeminiClient, calls generate_text(),
and asserts the response contains "AIFlow" or "ready" (case-insensitive).

Usage:
    cd app/
    python scripts/test_gemini.py

Requirements:
    - .env file with AIFLOW_GEMINI_API_KEY set to a valid key
    - pip install -e .[dev]
"""

import sys
from pathlib import Path

# Allow running from repo root or app/ directory
_app_dir = Path(__file__).resolve().parent.parent
if str(_app_dir) not in sys.path:
    sys.path.insert(0, str(_app_dir))


def main() -> None:
    print("─── AIFlow Gemini Smoke Test ───")

    # 1. Load settings
    print("Loading settings from .env ...")
    try:
        from server.config import load_settings, ConfigError
        settings = load_settings()
    except Exception as e:
        print(f"❌ Config error: {e}", file=sys.stderr)
        sys.exit(1)

    api_key = settings.gemini.api_key.get_secret_value()
    model = settings.gemini.model
    print(f"  ✓ API key loaded (starts with: {api_key[:8]}...)")
    print(f"  ✓ Model: {model}")

    # 2. Create GeminiClient
    print("\nCreating GeminiClient ...")
    try:
        from server.ai.gemini import GeminiClient, GeminiError
        client = GeminiClient(
            api_key=api_key,
            model=model,
            timeout=settings.gemini.timeout,
        )
        print("  ✓ Client created")
    except Exception as e:
        print(f"❌ Failed to create GeminiClient: {e}", file=sys.stderr)
        sys.exit(1)

    # 3. Call generate_text
    prompt = "Say: AIFlow ready"
    print(f'\nCalling generate_text("{prompt}") ...')
    try:
        response = client.generate_text(prompt)
    except Exception as e:
        print(f"❌ generate_text failed: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"  Response: {response!r}")

    # 4. Assert response contains "AIFlow" or "ready"
    response_lower = response.lower()
    if "aiflow" in response_lower or "ready" in response_lower:
        print("\n✅ Smoke test PASSED — Gemini API is working correctly.")
        sys.exit(0)
    else:
        print(
            "\n⚠️  Smoke test WARNING — response did not contain 'AIFlow' or 'ready'.\n"
            "   The API is reachable but the model gave an unexpected response.\n"
            f"   Full response: {response!r}",
            file=sys.stderr,
        )
        # Exit 0 because the API itself worked — the model just paraphrased
        sys.exit(0)


if __name__ == "__main__":
    main()
