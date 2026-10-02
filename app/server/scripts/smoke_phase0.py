"""
Phase 0 acceptance smoke test — 7 checks.

Run after `python -m server.main` is up + extension loaded + Flow tab open.

Usage:
    python server/scripts/smoke_phase0.py

Exit code 0 = all checks pass, 1 = any check failed.

Checks 1-2 are standalone (no server required).
Checks 3-7 require a running server + Chrome extension connected.
Checks 4, 5, 7 additionally require the extension to be connected and
a Bearer token captured (open labs.google in Chrome).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# ── Ensure project root is on sys.path when run as a script ──────────────────
_PROJECT_ROOT = Path(__file__).resolve().parents[2]  # app/
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ── Check registry ────────────────────────────────────────────────────────────

_CHECKS: list[tuple[str, "asyncio.coroutines"]] = []


def check(name: str):
    """Decorator that registers an async check function."""
    def decorator(fn):
        _CHECKS.append((name, fn))
        return fn
    return decorator


# ── Check 1: Config loads from .env ──────────────────────────────────────────

@check("Config loads from .env")
async def check_config() -> None:
    from server.config import load_settings
    settings = load_settings()
    key = settings.gemini.api_key.get_secret_value()
    assert key, "AIFLOW_GEMINI_API_KEY is empty"
    assert settings.flow.plan in ("Pro", "Ultra"), (
        f"flow.plan must be Pro or Ultra, got {settings.flow.plan!r}"
    )


# ── Check 2: DB bootstrap succeeded ──────────────────────────────────────────

@check("DB bootstrap succeeded (4 tables: project, job, joblog, config)")
async def check_db() -> None:
    from server.config import load_settings
    from server.db.session import bootstrap_schema, get_engine

    settings = load_settings()
    bootstrap_schema(settings)

    db_path = settings.data_dir / "projects.db"
    assert db_path.exists(), f"DB file not found: {db_path}"

    # Verify the 4 expected tables exist
    engine = get_engine(settings)
    from sqlalchemy import inspect as sa_inspect
    inspector = sa_inspect(engine)
    tables = set(inspector.get_table_names())
    expected = {"project", "job", "joblog", "config"}
    missing = expected - tables
    assert not missing, f"Missing tables: {missing}. Found: {tables}"


# ── Check 3: Agent server reachable ──────────────────────────────────────────

@check("Agent server reachable (GET /api/health → {status: ok})")
async def check_health() -> None:
    try:
        import httpx
    except ImportError as e:
        raise RuntimeError("httpx not installed — run: pip install httpx") from e

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get("http://127.0.0.1:8101/api/health")
    except (httpx.ConnectError, httpx.ConnectTimeout) as e:
        raise RuntimeError(
            "Cannot reach agent server at http://127.0.0.1:8101 — "
            "run: python -m server.main"
        ) from e

    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    data = r.json()
    assert data.get("status") == "ok", f"Expected status=ok, got {data}"


# ── Check 4: Extension is connected ──────────────────────────────────────────

@check("Extension is connected (extension_connected: true)")
async def check_extension() -> None:
    try:
        import httpx
    except ImportError as e:
        raise RuntimeError("httpx not installed — run: pip install httpx") from e

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get("http://127.0.0.1:8101/api/health")
    except (httpx.ConnectError, httpx.ConnectTimeout) as e:
        raise RuntimeError(
            "Cannot reach agent server — run: python -m server.main"
        ) from e

    data = r.json()
    connected = data.get("extension_connected", False)
    assert connected is True, (
        "Extension not connected. "
        "Load the AIFlow Bridge extension in Chrome and wait for it to connect."
    )


# ── Check 5: Bearer token captured ───────────────────────────────────────────

@check("Bearer token captured (FlowClient.get_token() is not None)")
async def check_token() -> None:
    from server.flow.client import FlowClient

    client = FlowClient()
    token = client.get_token()
    if token is None:
        # Try waiting briefly — token may arrive shortly after extension connects
        try:
            token = await asyncio.wait_for(client.wait_for_token(timeout=10.0), timeout=12.0)
        except (TimeoutError, asyncio.TimeoutError) as e:
            raise RuntimeError(
                "No Bearer token captured. "
                "Open https://labs.google/fx/tools/flow in Chrome so the "
                "extension can capture the Bearer token."
            ) from e
    assert token, "Token is empty string"


# ── Check 6: Gemini API works ─────────────────────────────────────────────────

@check("Gemini API works (GeminiClient.health_check() → True)")
async def check_gemini() -> None:
    from server.config import load_settings
    from server.ai.gemini import GeminiClient

    settings = load_settings()
    client = GeminiClient(
        api_key=settings.gemini.api_key.get_secret_value(),
        model=settings.gemini.model,
        timeout=settings.gemini.timeout,
    )
    ok = client.health_check()
    assert ok, (
        "Gemini health_check() returned False. "
        "Check AIFLOW_GEMINI_API_KEY and internet connectivity."
    )


# ── Check 7: Veo3 image gen works ────────────────────────────────────────────

@check("Veo3 image gen works (gen_image → file > 50 KB)")
async def check_image_gen() -> None:
    from server.config import load_settings
    from server.flow.client import FlowClient
    from server.flow.sdk import FlowSDK

    settings = load_settings()

    # Verify extension is connected before attempting gen
    flow_client = FlowClient()
    if not flow_client.is_connected():
        raise RuntimeError(
            "Extension not connected — cannot call gen_image. "
            "Load the AIFlow Bridge extension and open labs.google in Chrome."
        )

    token = flow_client.get_token()
    if not token:
        raise RuntimeError(
            "No Bearer token — cannot call gen_image. "
            "Open https://labs.google/fx/tools/flow in Chrome."
        )

    sdk = FlowSDK(client=flow_client)
    out_dir = settings.data_dir / "media" / "phase0_smoke"

    out_path = await sdk.gen_image(
        prompt="A simple red cube on a white background, studio lighting, 3D render",
        model="GEM_PIX_2",
        aspect="9:16",
        storage_dir=out_dir,
    )

    assert out_path.exists(), f"Output file not found: {out_path}"
    size = out_path.stat().st_size
    assert size > 50 * 1024, (
        f"Generated image too small: {size} bytes (expected > 50 KB). "
        "The image may be corrupt or generation failed silently."
    )


# ── Runner ────────────────────────────────────────────────────────────────────

async def main() -> int:
    print("=" * 60)
    print("AIFlow — Phase 0 Acceptance Smoke Test")
    print("=" * 60)
    print()

    results: list[bool] = []

    for name, fn in _CHECKS:
        try:
            await fn()
            print(f"  ✅ {name}")
            results.append(True)
        except Exception as exc:
            print(f"  ❌ {name}")
            print(f"     → {exc}")
            results.append(False)

    print()
    print("=" * 60)
    passed = sum(results)
    total = len(results)

    if passed == total:
        print(f"🎉 Phase 0 PASSED ({passed}/{total} checks)")
        return 0
    else:
        print(f"💥 Phase 0 FAILED ({passed}/{total} checks)")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
