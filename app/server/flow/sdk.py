"""Flow SDK — Phase 1: gen_image + gen_video (i2v) + check_async.

Lifted and adapted from flowboard/agent/flowboard/services/flow_sdk.py.
Phase 0 shipped gen_image(). Phase 1 adds gen_video() (async submission)
and check_async() (single-shot poll) for image-to-video generation.

Architecture:
  - FlowSDK.gen_image() builds the request body and calls FlowClient.api_request()
  - FlowSDK.gen_video() submits an async i2v request, returns operation_name
  - FlowSDK.check_async() polls batchCheckAsync, returns raw response dict
  - FlowClient.api_request() sends the request to the Chrome extension over WS
  - The extension performs the fetch with Bearer token + reCAPTCHA token
  - The extension POSTs the response to /api/ext/callback
  - ext_callback.py calls FlowClient.resolve_callback() to resolve the future
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any, Optional

import httpx
from loguru import logger

from server.flow.client import FlowClient

# ── Endpoints ─────────────────────────────────────────────────────────────────

FLOW_API_BASE = "https://aisandbox-pa.googleapis.com"
FLOW_CREDITS_URL = f"{FLOW_API_BASE}/v1/credits"

# Google Flow's public API key — appears verbatim in every aisandbox-pa request.
# Not a secret; hardcoded in the web client.
_FLOW_API_KEY = "AIzaSyBtrm0o5ab1c-Ec8ZuLcGt3oJAA5VWt3pY"


def _generate_images_url(project_id: str) -> str:
    return f"{FLOW_API_BASE}/v1/projects/{project_id}/flowMedia:batchGenerateImages"


# Video generation endpoints (async i2v)
VIDEO_I2V_URL = f"{FLOW_API_BASE}/v1/video:batchAsyncGenerateVideoStartImage"
VIDEO_POLL_URL = f"{FLOW_API_BASE}/v1/video:batchCheckAsyncVideoGenerationStatus"


# ── Image model registry ──────────────────────────────────────────────────────

# Maps user-facing model keys to the actual Flow model identifier.
# GEM_PIX_2 is the default (Pro quality). NARWHAL is the lighter/faster option.
IMAGE_MODELS: dict[str, str] = {
    "GEM_PIX_2": "GEM_PIX_2",       # Default — Pro quality image model
    "NARWHAL": "NARWHAL",            # Lighter / faster option
    # Flowboard aliases (for compatibility)
    "NANO_BANANA_PRO": "GEM_PIX_2",
    "NANO_BANANA_2": "NARWHAL",
}

DEFAULT_IMAGE_MODEL_KEY = "GEM_PIX_2"

# ── Video model registry ──────────────────────────────────────────────────────

# Maps user-facing video model keys to the actual Flow model identifiers.
# These are verified against real Flow web request bodies (curl exports from
# labs.google's Network tab). The keys are tier + aspect aware — see
# VIDEO_MODEL_KEYS for the full per-tier/quality/aspect mapping.
#
# Simplified user-facing aliases for the most common use cases:
#   VEO3      → fast quality, adapts to aspect via VIDEO_MODEL_KEYS
#   VEO3_FAST → same as VEO3 (explicit alias)
#   VEO3_LITE → lite quality (fewer credits, faster)
VIDEO_MODELS: dict[str, str] = {
    "VEO3": "veo_3_1_i2v_s_fast",           # Default — fast quality (Tier 1 landscape)
    "VEO3_FAST": "veo_3_1_i2v_s_fast",      # Explicit fast alias
    "VEO3_LITE": "veo_3_1_i2v_lite",        # Lite / fewer credits
    "VEO3_QUALITY": "veo_3_1_i2v_s",        # Highest fidelity, slowest
}

DEFAULT_VIDEO_MODEL_KEY = "VEO3"

# Full per-tier/quality/aspect video model key table.
# Verified from real PRO and ULTRA PLAN curl exports (see flowboard reference).
# Tier 2 (Ultra) fast models use the `_ultra` suffix; quality models are shared.
VIDEO_MODEL_KEYS: dict[str, dict[str, dict[str, str]]] = {
    "PAYGATE_TIER_ONE": {
        "lite": {
            "VIDEO_ASPECT_RATIO_LANDSCAPE": "veo_3_1_i2v_lite",
            "VIDEO_ASPECT_RATIO_PORTRAIT": "veo_3_1_i2v_lite",
        },
        "fast": {
            "VIDEO_ASPECT_RATIO_LANDSCAPE": "veo_3_1_i2v_s_fast",
            "VIDEO_ASPECT_RATIO_PORTRAIT": "veo_3_1_i2v_s_fast_portrait",
        },
        "quality": {
            "VIDEO_ASPECT_RATIO_LANDSCAPE": "veo_3_1_i2v_s",
            "VIDEO_ASPECT_RATIO_PORTRAIT": "veo_3_1_i2v_s_portrait",
        },
    },
    "PAYGATE_TIER_TWO": {
        "lite": {
            "VIDEO_ASPECT_RATIO_LANDSCAPE": "veo_3_1_i2v_lite",
            "VIDEO_ASPECT_RATIO_PORTRAIT": "veo_3_1_i2v_lite",
        },
        "fast": {
            "VIDEO_ASPECT_RATIO_LANDSCAPE": "veo_3_1_i2v_s_fast_ultra",
            "VIDEO_ASPECT_RATIO_PORTRAIT": "veo_3_1_i2v_s_fast_portrait_ultra",
        },
        "quality": {
            "VIDEO_ASPECT_RATIO_LANDSCAPE": "veo_3_1_i2v_s",
            "VIDEO_ASPECT_RATIO_PORTRAIT": "veo_3_1_i2v_s_portrait",
        },
        "lite_relaxed": {
            "VIDEO_ASPECT_RATIO_LANDSCAPE": "veo_3_1_i2v_lite_low_priority",
            "VIDEO_ASPECT_RATIO_PORTRAIT": "veo_3_1_i2v_lite_low_priority",
        },
        "fast_relaxed": {
            "VIDEO_ASPECT_RATIO_LANDSCAPE": "veo_3_1_i2v_s_fast_ultra_relaxed",
            "VIDEO_ASPECT_RATIO_PORTRAIT": "veo_3_1_i2v_s_fast_ultra_relaxed",
        },
    },
}

DEFAULT_VIDEO_QUALITY = "fast"

# reCAPTCHA action for video generation
CAPTCHA_VIDEO = "VIDEO_GENERATION"


def resolve_video_model(
    model_name: str,
    paygate_tier: Optional[str] = None,
    aspect_ratio: Optional[str] = None,
    quality: Optional[str] = None,
) -> str:
    """Map a video model key to the actual Flow model identifier.

    Supports two resolution modes:
    1. Simple: pass ``model_name`` from VIDEO_MODELS (e.g. "VEO3") — returns
       the mapped identifier directly (tier/aspect-agnostic shortcut).
    2. Full: pass ``paygate_tier`` + ``aspect_ratio`` + optional ``quality``
       to resolve from the per-tier VIDEO_MODEL_KEYS table.

    Falls back to the VEO3 default for unknown / missing keys.

    Args:
        model_name: User-facing model key (e.g. "VEO3", "VEO3_LITE").
        paygate_tier: Optional paygate tier for full resolution
                      ("PAYGATE_TIER_ONE" or "PAYGATE_TIER_TWO").
        aspect_ratio: Optional Flow aspect ratio string
                      ("VIDEO_ASPECT_RATIO_LANDSCAPE" or "VIDEO_ASPECT_RATIO_PORTRAIT").
        quality: Optional quality level ("fast", "lite", "quality", etc.).

    Returns:
        The Flow model identifier string.
    """
    # Full resolution via tier/aspect/quality table
    if paygate_tier and aspect_ratio:
        q = (quality or DEFAULT_VIDEO_QUALITY).lower()
        tier_map = (
            VIDEO_MODEL_KEYS.get(paygate_tier)
            or VIDEO_MODEL_KEYS.get("PAYGATE_TIER_ONE")
            or {}
        )
        quality_map = tier_map.get(q) or tier_map.get(DEFAULT_VIDEO_QUALITY) or {}
        result = quality_map.get(aspect_ratio)
        if result:
            return result

    # Simple lookup from VIDEO_MODELS dict
    if isinstance(model_name, str) and model_name in VIDEO_MODELS:
        return VIDEO_MODELS[model_name]
    return VIDEO_MODELS[DEFAULT_VIDEO_MODEL_KEY]


# ── reCAPTCHA action strings ──────────────────────────────────────────────────

# reCAPTCHA action for image generation
CAPTCHA_IMAGE = "IMAGE_GENERATION"

# Minimum file size for a valid generated image (50 KB)
MIN_IMAGE_SIZE_BYTES = 50 * 1024

# Static headers that work against labs.google
_API_HEADERS = {
    "content-type": "text/plain;charset=UTF-8",
    "accept": "*/*",
    "origin": "https://labs.google",
    "referer": "https://labs.google/",
}

# Valid paygate tiers
_VALID_TIERS = {"PAYGATE_TIER_ONE", "PAYGATE_TIER_TWO"}


def resolve_image_model(model_name: Optional[str]) -> str:
    """Map a model key to the actual Flow model identifier.

    Falls back to GEM_PIX_2 (Pro default) for unknown / missing keys so a
    stale caller can't break dispatch.

    Args:
        model_name: User-facing model key (e.g. "GEM_PIX_2", "NARWHAL",
                    "NANO_BANANA_PRO"). Case-sensitive.

    Returns:
        The Flow model identifier string.
    """
    if isinstance(model_name, str) and model_name in IMAGE_MODELS:
        return IMAGE_MODELS[model_name]
    return IMAGE_MODELS[DEFAULT_IMAGE_MODEL_KEY]


def _client_context(project_id: str, paygate_tier: str) -> dict[str, Any]:
    """Build the clientContext block for a Flow API request.

    The recaptchaContext.token is left empty — the extension fills it in
    before firing the fetch when captchaAction is set.
    """
    if paygate_tier not in _VALID_TIERS:
        raise ValueError(
            f"invalid paygate_tier {paygate_tier!r} — must be one of {sorted(_VALID_TIERS)}"
        )
    return {
        "projectId": str(project_id),
        "recaptchaContext": {
            "applicationType": "RECAPTCHA_APPLICATION_TYPE_WEB",
            "token": "",
        },
        "sessionId": f";{int(time.time() * 1000)}",
        "tool": "PINHOLE",
        "userPaygateTier": paygate_tier,
    }


def _extract_inner_api_error(resp: Any) -> Optional[str]:
    """Surface a Flow API error from the response envelope.

    flow_client.api_request returns {"id", "status", "data"} even when the
    underlying call failed. HTTP status >= 400 or data.error indicates failure.
    """
    if not isinstance(resp, dict):
        return None
    status = resp.get("status")
    data = resp.get("data") if isinstance(resp.get("data"), dict) else None
    err = data.get("error") if isinstance(data, dict) else None
    has_status_err = isinstance(status, int) and status >= 400
    has_data_err = isinstance(err, dict)
    if not (has_status_err or has_data_err):
        return None
    if has_data_err:
        reasons: list[str] = []
        for detail in err.get("details") or []:
            if isinstance(detail, dict):
                r = detail.get("reason")
                if isinstance(r, str) and r:
                    reasons.append(r)
        msg = err.get("message") or err.get("status") or "API error"
        return f"{reasons[0]}: {msg}" if reasons else str(msg)
    return f"API_{status}"


def extract_media_entries(resp: Any) -> list[dict[str, Any]]:
    """Pull media entries out of a batchGenerateImages response.

    Returns a list of {"media_id", "url", "mediaType"} dicts.
    "url" is the signed FIFE URL for downloading the image bytes.
    """
    if not isinstance(resp, dict):
        return []
    data = resp.get("data")
    if not isinstance(data, dict):
        return []
    media = data.get("media")
    if not isinstance(media, list):
        return []
    out: list[dict[str, Any]] = []
    for m in media:
        if not isinstance(m, dict):
            continue
        media_id = m.get("name")
        if not isinstance(media_id, str) or not media_id:
            continue
        url: Optional[str] = None
        kind = "image"
        image = m.get("image") if isinstance(m.get("image"), dict) else None
        video = m.get("video") if isinstance(m.get("video"), dict) else None
        if image is not None:
            gen = image.get("generatedImage")
            if isinstance(gen, dict):
                candidate = gen.get("fifeUrl")
                if isinstance(candidate, str):
                    url = candidate
            kind = "image"
        elif video is not None:
            gen = video.get("generatedVideo") or video.get("generatedImage")
            if isinstance(gen, dict):
                candidate = gen.get("fifeUrl")
                if isinstance(candidate, str):
                    url = candidate
            kind = "video"
        out.append({"media_id": media_id, "url": url, "mediaType": kind})
    return out


# ── UUID extraction from FIFE URLs ────────────────────────────────────────────

import re as _re

_UUID_IN_URL_RE = _re.compile(
    r"/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    _re.IGNORECASE,
)


def _media_id_from_url(url: Optional[str]) -> Optional[str]:
    """Extract a UUID media_id from a Flow CDN URL path."""
    if not isinstance(url, str):
        return None
    m = _UUID_IN_URL_RE.search(url)
    return m.group(1) if m else None


def extract_operation_names(resp: Any) -> list[str]:
    """Pull operation.name values out of a batchAsyncGenerateVideo* response.

    Supports two response shapes:
    - OLD (Lite/Fast/Quality): ``data.operations[].operation.name``
    - NEW (Low Priority): ``data.workflows[].name``

    Returns a list of operation name strings.
    """
    if not isinstance(resp, dict):
        return []
    data = resp.get("data")
    if not isinstance(data, dict):
        return []
    names: list[str] = []
    ops = data.get("operations")
    if isinstance(ops, list):
        for op in ops:
            if not isinstance(op, dict):
                continue
            inner = op.get("operation") if isinstance(op.get("operation"), dict) else None
            if inner is None:
                name = op.get("name")
            else:
                name = inner.get("name")
            if isinstance(name, str) and name:
                names.append(name)
    if names:
        return names
    # NEW workflow schema — data.workflows[] instead of data.operations[]
    workflows = data.get("workflows")
    if isinstance(workflows, list):
        for wf in workflows:
            if not isinstance(wf, dict):
                continue
            name = wf.get("name")
            if isinstance(name, str) and name:
                names.append(name)
    return names


def extract_video_workflows(resp: Any) -> list[dict[str, Any]]:
    """Pull workflow entries out of a NEW-schema video submit response.

    Returns ``[{"name": <workflow_name>, "primary_media_id": <uuid>}, ...]``.
    Empty list when the response is OLD-schema (operations-based) or has no
    workflows. Used for low-priority (0-credit) model submissions that don't
    yield operation names — polling goes to /v1/media/<primaryMediaId> instead.
    """
    if not isinstance(resp, dict):
        return []
    data = resp.get("data")
    if not isinstance(data, dict):
        return []
    workflows = data.get("workflows")
    if not isinstance(workflows, list):
        return []
    out: list[dict[str, Any]] = []
    for wf in workflows:
        if not isinstance(wf, dict):
            continue
        name = wf.get("name")
        meta = wf.get("metadata") if isinstance(wf.get("metadata"), dict) else {}
        primary = meta.get("primaryMediaId") if isinstance(meta, dict) else None
        if isinstance(name, str) and name and isinstance(primary, str) and primary:
            out.append({"name": name, "primary_media_id": primary})
    return out


def extract_video_operations(
    resp: Any, *, requested: list[str]
) -> list[dict[str, Any]]:
    """Summarise a batchCheckAsync response into per-operation status dicts.

    Flow's response shape::

        {"data": {"operations": [{
            "status": "MEDIA_GENERATION_STATUS_{PENDING,SUCCESSFUL,FAILED}",
            "operation": {"name": "<id>", "metadata": {"video": {
                "mediaId": "<uuid>", "fifeUrl": "https://flow-content..."
            }}}
        }]}}

    Returns one entry per requested operation name, in order. Missing
    operations are reported as ``done=False`` so the caller can keep polling.

    Each entry has: ``{name, done, media_entries, status, error}``.
    """
    by_name: dict[str, dict[str, Any]] = {}
    if isinstance(resp, dict):
        data = resp.get("data")
        if isinstance(data, dict):
            ops = data.get("operations")
            if isinstance(ops, list):
                for op in ops:
                    if not isinstance(op, dict):
                        continue
                    inner = op.get("operation") if isinstance(op.get("operation"), dict) else op
                    name = inner.get("name") if isinstance(inner, dict) else None
                    if not isinstance(name, str):
                        continue
                    meta = (inner.get("metadata") or {}) if isinstance(inner, dict) else {}
                    video_meta = meta.get("video") if isinstance(meta.get("video"), dict) else {}
                    media_id = video_meta.get("mediaId") if isinstance(video_meta, dict) else None
                    fife = video_meta.get("fifeUrl") if isinstance(video_meta, dict) else None
                    # Flow's video poll response usually omits mediaId and only
                    # provides mediaGenerationId (base64 protobuf, NOT a UUID).
                    # The actual UUID is embedded in the fifeUrl path — recover it.
                    if not (isinstance(media_id, str) and media_id):
                        recovered = _media_id_from_url(fife if isinstance(fife, str) else None)
                        if recovered is None and isinstance(video_meta, dict):
                            recovered = _media_id_from_url(video_meta.get("servingBaseUri"))
                        if recovered is not None:
                            media_id = recovered
                    # Flow puts the status at the top of each op envelope
                    status = op.get("status") if isinstance(op.get("status"), str) else None
                    # Per-op terminal failure (e.g. PUBLIC_ERROR_AUDIO_FILTERED)
                    op_err: Optional[str] = None
                    inner_err = inner.get("error") if isinstance(inner, dict) else None
                    if isinstance(inner_err, dict):
                        msg = inner_err.get("message") or inner_err.get("status") or "operation_failed"
                        op_err = str(msg)
                    if status == "MEDIA_GENERATION_STATUS_FAILED" and op_err is None:
                        op_err = "MEDIA_GENERATION_STATUS_FAILED"
                    done_flag = (
                        status == "MEDIA_GENERATION_STATUS_SUCCESSFUL"
                        or status == "MEDIA_GENERATION_STATUS_FAILED"
                        or bool(inner.get("done") if isinstance(inner, dict) else False)
                        or bool(media_id and fife)
                    )
                    entries = []
                    if done_flag and op_err is None and isinstance(media_id, str):
                        entries.append({
                            "media_id": media_id,
                            "url": fife if isinstance(fife, str) else None,
                            "mediaType": "video",
                        })
                    by_name[name] = {
                        "name": name,
                        "done": done_flag,
                        "media_entries": entries,
                        "status": status,
                        "error": op_err,
                    }

    out: list[dict[str, Any]] = []
    for name in requested:
        out.append(
            by_name.get(name, {"name": name, "done": False, "media_entries": []})
        )
    return out


class FlowSDK:
    """High-level Flow API helpers. Phase 0: gen_image only.

    Requires a running WS server with an extension connected and a Bearer
    token captured. Use FlowClient.wait_for_extension() and
    FlowClient.wait_for_token() before calling gen_image().
    """

    def __init__(self, client: Optional[FlowClient] = None) -> None:
        self._client = client or FlowClient()

    async def _fetch_paygate_tier(self) -> str:
        """Resolve the user's paygate tier from /v1/credits.

        Returns:
            "PAYGATE_TIER_ONE" (Pro) or "PAYGATE_TIER_TWO" (Ultra).

        Raises:
            RuntimeError: If the tier cannot be resolved.
        """
        token = self._client.get_token()
        if not token:
            raise RuntimeError(
                "No Bearer token available. "
                "Make sure the extension is connected and you are logged in to labs.google."
            )
        try:
            async with httpx.AsyncClient(timeout=15.0) as http:
                resp = await http.get(
                    FLOW_CREDITS_URL,
                    params={"key": _FLOW_API_KEY},
                    headers={
                        "authorization": f"Bearer {token}",
                        "origin": "https://labs.google",
                        "referer": "https://labs.google/",
                    },
                )
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Failed to fetch paygate tier: {exc}") from exc

        if resp.status_code != 200:
            raise RuntimeError(
                f"Paygate tier fetch returned HTTP {resp.status_code}. "
                "Token may be expired — navigate to labs.google to refresh."
            )
        try:
            data = resp.json()
        except Exception as exc:
            raise RuntimeError(f"Paygate tier response was not JSON: {exc}") from exc

        tier = data.get("userPaygateTier")
        if tier not in _VALID_TIERS:
            raise RuntimeError(
                f"Unexpected paygate tier {tier!r}. "
                "Expected PAYGATE_TIER_ONE (Pro) or PAYGATE_TIER_TWO (Ultra). "
                "Make sure you have an active Google Flow Pro or Ultra subscription."
            )
        logger.info(f"FlowSDK: paygate tier resolved: {tier}")
        return tier

    async def gen_image(
        self,
        prompt: str,
        model: str = "GEM_PIX_2",
        aspect: str = "9:16",
        project_id: Optional[str] = None,
        storage_dir: Optional[Path] = None,
    ) -> Path:
        """Generate a single image via Google Flow and save it to disk.

        Flow:
          1. Resolve paygate tier from /v1/credits (requires Bearer token)
          2. Build request body with reCAPTCHA placeholder
          3. Send api_request to extension over WS (extension solves captcha + fetches)
          4. Parse response → extract signed FIFE URL
          5. Download image bytes via httpx
          6. Save to storage/media/{project_id}/image_{timestamp}.png
          7. Verify file size > 50 KB
          8. Return Path

        Args:
            prompt: Text prompt for image generation.
            model: Image model key. Default "GEM_PIX_2" (Pro quality).
                   Also accepts "NARWHAL" (faster/lighter).
            aspect: Aspect ratio string. "9:16" (portrait) or "16:9" (landscape).
                    Mapped to Flow's IMAGE_ASPECT_RATIO_* enum.
            project_id: Flow project ID. Auto-generated UUID if not provided.
            storage_dir: Base directory for saving images. Defaults to
                         Path("storage/media").

        Returns:
            Path to the downloaded image file.

        Raises:
            RuntimeError: On API errors, missing token, or file size check failure.
            TimeoutError: If the extension doesn't respond in time.
        """
        # Map aspect ratio string to Flow enum
        aspect_map = {
            "9:16": "IMAGE_ASPECT_RATIO_PORTRAIT",
            "16:9": "IMAGE_ASPECT_RATIO_LANDSCAPE",
            "1:1": "IMAGE_ASPECT_RATIO_SQUARE",
        }
        flow_aspect = aspect_map.get(aspect, "IMAGE_ASPECT_RATIO_PORTRAIT")

        # Resolve paygate tier
        paygate_tier = await self._fetch_paygate_tier()

        # Use provided project_id or generate one
        if not project_id:
            project_id = str(uuid.uuid4())
            logger.debug(f"FlowSDK: auto-generated project_id={project_id}")

        # Resolve model name
        model_name = resolve_image_model(model)
        logger.info(f"FlowSDK: gen_image prompt={prompt!r:.60} model={model_name} aspect={flow_aspect}")

        # Build request body
        ts = int(time.time() * 1000)
        ctx = _client_context(project_id, paygate_tier)
        request_item: dict[str, Any] = {
            "clientContext": {**ctx, "sessionId": f";{ts}"},
            "seed": ts % 1_000_000,
            "structuredPrompt": {"parts": [{"text": prompt}]},
            "imageAspectRatio": flow_aspect,
            "imageModelName": model_name,
        }
        body = {
            "clientContext": ctx,
            "mediaGenerationContext": {"batchId": str(uuid.uuid4())},
            "useNewMedia": True,
            "requests": [request_item],
        }

        # Send request through extension
        logger.info("FlowSDK: sending api_request to extension (captcha=IMAGE_GENERATION)")
        resp = await self._client.api_request(
            url=_generate_images_url(project_id),
            method="POST",
            headers=dict(_API_HEADERS),
            body=body,
            captcha_action=CAPTCHA_IMAGE,
            timeout=120.0,
        )

        # Check for errors
        if isinstance(resp, dict) and resp.get("error"):
            raise RuntimeError(f"FlowSDK gen_image failed: {resp['error']}")

        inner_err = _extract_inner_api_error(resp)
        if inner_err:
            raise RuntimeError(f"FlowSDK gen_image API error: {inner_err}")

        # Extract media entries
        entries = extract_media_entries(resp)
        if not entries:
            raise RuntimeError(
                f"FlowSDK gen_image: no media entries in response. "
                f"Raw response keys: {list(resp.keys()) if isinstance(resp, dict) else type(resp)}"
            )

        entry = entries[0]
        media_id = entry["media_id"]
        signed_url = entry.get("url")

        if not signed_url:
            raise RuntimeError(
                f"FlowSDK gen_image: no signed URL for media_id={media_id}. "
                "Flow may have returned a media entry without a fifeUrl."
            )

        logger.info(f"FlowSDK: image generated media_id={media_id}, downloading...")

        # Determine output path
        base = storage_dir or Path("storage/media")
        out_dir = base / project_id
        out_dir.mkdir(parents=True, exist_ok=True)
        timestamp = int(time.time())
        out_path = out_dir / f"image_{timestamp}.png"

        # Download image bytes
        try:
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as http:
                dl_resp = await http.get(signed_url)
                dl_resp.raise_for_status()
                image_bytes = dl_resp.content
        except httpx.HTTPError as exc:
            raise RuntimeError(f"FlowSDK: failed to download image from signed URL: {exc}") from exc

        # Write to disk
        out_path.write_bytes(image_bytes)
        file_size = out_path.stat().st_size
        logger.info(f"FlowSDK: image saved to {out_path} ({file_size:,} bytes)")

        # Verify file size > 50 KB
        if file_size < MIN_IMAGE_SIZE_BYTES:
            out_path.unlink(missing_ok=True)
            raise RuntimeError(
                f"FlowSDK: downloaded image is too small ({file_size} bytes < {MIN_IMAGE_SIZE_BYTES} bytes). "
                "The image may be corrupt or the generation failed silently."
            )

        return out_path


    async def gen_video(
        self,
        start_image: Path,
        prompt: str,
        duration: int = 8,
        aspect: str = "9:16",
        project_id: Optional[str] = None,
        storage_dir: Optional[Path] = None,
        model: str = "VEO3",
        quality: Optional[str] = None,
    ) -> str:
        """Submit an async image-to-video generation request to Google Flow.

        Uploads the start_image to Flow (as base64), then submits a
        batchAsyncGenerateVideoStartImage request. Returns the operation_name
        string for polling via check_async().

        Flow:
          1. Resolve paygate tier from /v1/credits (requires Bearer token)
          2. Read start_image bytes and base64-encode them
          3. Upload image to Flow via uploadImage endpoint
          4. Build video generation request body
          5. Send api_request to extension (captcha=VIDEO_GENERATION)
          6. Extract and return operation_name from response

        Args:
            start_image: Path to the start frame image (last frame of previous
                         scene, or initial image). Must exist on disk.
            prompt: Text prompt describing the video to generate.
            duration: Video duration in seconds. Default 8.
            aspect: Aspect ratio string. "9:16" (portrait) or "16:9" (landscape).
            project_id: Flow project ID. Auto-generated UUID if not provided.
            storage_dir: Base directory (unused here, kept for API symmetry).
            model: Video model key. Default "VEO3" (fast quality).
            quality: Quality level override ("fast", "lite", "quality").
                     If None, uses the model key's default.

        Returns:
            operation_name string (the async operation ID for polling).

        Raises:
            RuntimeError: On API errors, missing token, upload failure, or
                          no operation name in response.
            FileNotFoundError: If start_image does not exist.
            TimeoutError: If the extension doesn't respond in time.
        """
        import base64 as _b64
        import mimetypes

        if not start_image.exists():
            raise FileNotFoundError(f"start_image not found: {start_image}")

        # Resolve paygate tier
        paygate_tier = await self._fetch_paygate_tier()

        # Use provided project_id or generate one
        if not project_id:
            project_id = str(uuid.uuid4())
            logger.debug(f"FlowSDK gen_video: auto-generated project_id={project_id}")

        # Map aspect ratio string to Flow video enum
        aspect_map = {
            "9:16": "VIDEO_ASPECT_RATIO_PORTRAIT",
            "16:9": "VIDEO_ASPECT_RATIO_LANDSCAPE",
            "1:1": "VIDEO_ASPECT_RATIO_LANDSCAPE",  # Flow doesn't have square video
        }
        flow_aspect = aspect_map.get(aspect, "VIDEO_ASPECT_RATIO_PORTRAIT")

        # Resolve video model key
        model_key = resolve_video_model(
            model_name=model,
            paygate_tier=paygate_tier,
            aspect_ratio=flow_aspect,
            quality=quality,
        )
        logger.info(
            f"FlowSDK gen_video: prompt={prompt!r:.60} model={model_key} "
            f"aspect={flow_aspect} duration={duration}s"
        )

        # Read and base64-encode the start image
        image_bytes = start_image.read_bytes()
        image_b64 = _b64.b64encode(image_bytes).decode("ascii")
        mime_type, _ = mimetypes.guess_type(str(start_image))
        if not mime_type:
            mime_type = "image/png"

        # Upload start image to Flow
        logger.info(f"FlowSDK gen_video: uploading start_image={start_image.name} ({len(image_bytes):,} bytes)")
        upload_body = {
            "clientContext": {
                "projectId": str(project_id),
                "tool": "PINHOLE",
            },
            "fileName": start_image.name,
            "imageBytes": image_b64,
            "isHidden": False,
            "isUserUploaded": True,
            "mimeType": mime_type,
        }
        upload_url = f"{FLOW_API_BASE}/v1/flow/uploadImage"
        upload_resp = await self._client.api_request(
            url=upload_url,
            method="POST",
            headers=dict(_API_HEADERS),
            body=upload_body,
        )
        if isinstance(upload_resp, dict) and upload_resp.get("error"):
            raise RuntimeError(f"FlowSDK gen_video: image upload failed: {upload_resp['error']}")

        # Extract uploaded media_id
        start_media_id: Optional[str] = None
        if isinstance(upload_resp, dict):
            data = upload_resp.get("data")
            if isinstance(data, dict):
                media = data.get("media")
                if isinstance(media, dict):
                    start_media_id = media.get("name")
        if not start_media_id:
            raise RuntimeError(
                f"FlowSDK gen_video: no media_id from upload response. "
                f"Raw keys: {list(upload_resp.keys()) if isinstance(upload_resp, dict) else type(upload_resp)}"
            )
        logger.info(f"FlowSDK gen_video: start_image uploaded as media_id={start_media_id}")

        # Build video generation request body
        ts = int(time.time() * 1000)
        ctx = _client_context(project_id, paygate_tier)
        scene_id = str(uuid.uuid4())
        request_item: dict[str, Any] = {
            "aspectRatio": flow_aspect,
            "seed": ts % 1_000_000,
            "textInput": {"structuredPrompt": {"parts": [{"text": prompt}]}},
            "videoModelKey": model_key,
            "startImage": {"mediaId": start_media_id},
            "metadata": {"sceneId": scene_id},
        }
        body = {
            "clientContext": ctx,
            "mediaGenerationContext": {"batchId": str(uuid.uuid4())},
            "requests": [request_item],
            "useV2ModelConfig": True,
        }

        # Submit async video generation request
        logger.info("FlowSDK gen_video: submitting async video request (captcha=VIDEO_GENERATION)")
        resp = await self._client.api_request(
            url=VIDEO_I2V_URL,
            method="POST",
            headers=dict(_API_HEADERS),
            body=body,
            captcha_action=CAPTCHA_VIDEO,
            timeout=120.0,
        )

        if isinstance(resp, dict) and resp.get("error"):
            raise RuntimeError(f"FlowSDK gen_video failed: {resp['error']}")

        inner_err = _extract_inner_api_error(resp)
        if inner_err:
            raise RuntimeError(f"FlowSDK gen_video API error: {inner_err}")

        # Extract operation name(s)
        op_names = extract_operation_names(resp)
        if not op_names:
            raise RuntimeError(
                f"FlowSDK gen_video: no operation names in response. "
                f"Raw response keys: {list(resp.keys()) if isinstance(resp, dict) else type(resp)}"
            )

        operation_name = op_names[0]
        logger.info(f"FlowSDK gen_video: submitted, operation_name={operation_name}")
        return operation_name

    async def check_async(self, operation_name: str) -> dict[str, Any]:
        """Poll the status of an async video generation operation.

        Makes a single call to batchCheckAsyncVideoGenerationStatus and returns
        the raw response dict. Does NOT loop — the caller decides whether the
        operation is done or still pending.

        Args:
            operation_name: The async operation ID returned by gen_video().

        Returns:
            Response dict from the Flow API. Callers should inspect:
            - resp["data"]["operations"][0]["status"] for generation status
            - "MEDIA_GENERATION_STATUS_SUCCESSFUL" = done
            - "MEDIA_GENERATION_STATUS_PENDING" = still running
            - "MEDIA_GENERATION_STATUS_FAILED" = failed

        Raises:
            RuntimeError: On transport-level errors (extension disconnected, timeout).
        """
        body = {
            "operations": [
                {"operation": {"name": operation_name}}
            ]
        }
        logger.debug(f"FlowSDK check_async: polling operation_name={operation_name}")
        resp = await self._client.api_request(
            url=VIDEO_POLL_URL,
            method="POST",
            headers=dict(_API_HEADERS),
            body=body,
            timeout=60.0,
        )

        if isinstance(resp, dict) and resp.get("error"):
            raise RuntimeError(f"FlowSDK check_async failed: {resp['error']}")

        return resp


# Module-level singleton
_sdk: Optional[FlowSDK] = None


def get_flow_sdk() -> FlowSDK:
    """Return the module-level FlowSDK singleton."""
    global _sdk
    if _sdk is None:
        _sdk = FlowSDK()
    return _sdk
