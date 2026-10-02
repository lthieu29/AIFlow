"""Unit tests for FlowSDK video generation (Task 1.2).

Tests cover:
- VIDEO_MODELS registry and resolve_video_model()
- extract_operation_names() helper
- extract_video_workflows() helper
- extract_video_operations() helper
- FlowSDK.gen_video() — mocked extension
- FlowSDK.check_async() — mocked extension
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.flow.sdk import (
    VIDEO_MODELS,
    VIDEO_MODEL_KEYS,
    DEFAULT_VIDEO_MODEL_KEY,
    CAPTCHA_VIDEO,
    VIDEO_I2V_URL,
    VIDEO_POLL_URL,
    FlowSDK,
    extract_operation_names,
    extract_video_operations,
    extract_video_workflows,
    resolve_video_model,
)


# ── VIDEO_MODELS registry ─────────────────────────────────────────────────────

class TestVideoModelsRegistry:
    def test_veo3_key_present(self):
        assert "VEO3" in VIDEO_MODELS

    def test_veo3_fast_key_present(self):
        assert "VEO3_FAST" in VIDEO_MODELS

    def test_veo3_lite_key_present(self):
        assert "VEO3_LITE" in VIDEO_MODELS

    def test_veo3_maps_to_real_model_identifier(self):
        # Must map to an actual veo model string, not a placeholder
        assert VIDEO_MODELS["VEO3"].startswith("veo_")

    def test_veo3_fast_same_as_veo3(self):
        assert VIDEO_MODELS["VEO3_FAST"] == VIDEO_MODELS["VEO3"]

    def test_veo3_lite_different_from_veo3(self):
        assert VIDEO_MODELS["VEO3_LITE"] != VIDEO_MODELS["VEO3"]

    def test_video_model_keys_has_both_tiers(self):
        assert "PAYGATE_TIER_ONE" in VIDEO_MODEL_KEYS
        assert "PAYGATE_TIER_TWO" in VIDEO_MODEL_KEYS

    def test_tier_one_has_fast_quality(self):
        tier = VIDEO_MODEL_KEYS["PAYGATE_TIER_ONE"]
        assert "fast" in tier
        assert "VIDEO_ASPECT_RATIO_LANDSCAPE" in tier["fast"]
        assert "VIDEO_ASPECT_RATIO_PORTRAIT" in tier["fast"]

    def test_tier_two_fast_uses_ultra_suffix(self):
        tier = VIDEO_MODEL_KEYS["PAYGATE_TIER_TWO"]
        assert "ultra" in tier["fast"]["VIDEO_ASPECT_RATIO_LANDSCAPE"]


# ── resolve_video_model ───────────────────────────────────────────────────────

class TestResolveVideoModel:
    def test_simple_veo3_lookup(self):
        result = resolve_video_model("VEO3")
        assert result == VIDEO_MODELS["VEO3"]

    def test_simple_veo3_lite_lookup(self):
        result = resolve_video_model("VEO3_LITE")
        assert result == VIDEO_MODELS["VEO3_LITE"]

    def test_unknown_key_falls_back_to_default(self):
        result = resolve_video_model("UNKNOWN_MODEL")
        assert result == VIDEO_MODELS[DEFAULT_VIDEO_MODEL_KEY]

    def test_full_resolution_tier_one_portrait(self):
        result = resolve_video_model(
            "VEO3",
            paygate_tier="PAYGATE_TIER_ONE",
            aspect_ratio="VIDEO_ASPECT_RATIO_PORTRAIT",
            quality="fast",
        )
        expected = VIDEO_MODEL_KEYS["PAYGATE_TIER_ONE"]["fast"]["VIDEO_ASPECT_RATIO_PORTRAIT"]
        assert result == expected

    def test_full_resolution_tier_two_landscape(self):
        result = resolve_video_model(
            "VEO3",
            paygate_tier="PAYGATE_TIER_TWO",
            aspect_ratio="VIDEO_ASPECT_RATIO_LANDSCAPE",
            quality="fast",
        )
        expected = VIDEO_MODEL_KEYS["PAYGATE_TIER_TWO"]["fast"]["VIDEO_ASPECT_RATIO_LANDSCAPE"]
        assert result == expected

    def test_full_resolution_quality_level(self):
        result = resolve_video_model(
            "VEO3",
            paygate_tier="PAYGATE_TIER_ONE",
            aspect_ratio="VIDEO_ASPECT_RATIO_LANDSCAPE",
            quality="quality",
        )
        expected = VIDEO_MODEL_KEYS["PAYGATE_TIER_ONE"]["quality"]["VIDEO_ASPECT_RATIO_LANDSCAPE"]
        assert result == expected

    def test_full_resolution_unknown_tier_falls_back_to_tier_one(self):
        result = resolve_video_model(
            "VEO3",
            paygate_tier="PAYGATE_TIER_UNKNOWN",
            aspect_ratio="VIDEO_ASPECT_RATIO_LANDSCAPE",
            quality="fast",
        )
        # Should fall back to TIER_ONE
        expected = VIDEO_MODEL_KEYS["PAYGATE_TIER_ONE"]["fast"]["VIDEO_ASPECT_RATIO_LANDSCAPE"]
        assert result == expected


# ── extract_operation_names ───────────────────────────────────────────────────

class TestExtractOperationNames:
    def test_old_schema_operations(self):
        resp = {
            "data": {
                "operations": [
                    {"operation": {"name": "op/abc123"}},
                    {"operation": {"name": "op/def456"}},
                ]
            }
        }
        names = extract_operation_names(resp)
        assert names == ["op/abc123", "op/def456"]

    def test_new_schema_workflows(self):
        resp = {
            "data": {
                "workflows": [
                    {"name": "wf/xyz789"},
                ]
            }
        }
        names = extract_operation_names(resp)
        assert names == ["wf/xyz789"]

    def test_old_schema_takes_priority_over_workflows(self):
        resp = {
            "data": {
                "operations": [{"operation": {"name": "op/first"}}],
                "workflows": [{"name": "wf/second"}],
            }
        }
        names = extract_operation_names(resp)
        assert names == ["op/first"]

    def test_empty_response(self):
        assert extract_operation_names({}) == []
        assert extract_operation_names(None) == []

    def test_inline_name_on_op(self):
        # Some variants inline the name at top level of the op dict
        resp = {
            "data": {
                "operations": [{"name": "op/inline"}]
            }
        }
        names = extract_operation_names(resp)
        assert names == ["op/inline"]


# ── extract_video_workflows ───────────────────────────────────────────────────

class TestExtractVideoWorkflows:
    def test_extracts_workflow_with_primary_media_id(self):
        media_id = str(uuid.uuid4())
        resp = {
            "data": {
                "workflows": [
                    {
                        "name": "wf/abc",
                        "metadata": {"primaryMediaId": media_id},
                    }
                ]
            }
        }
        workflows = extract_video_workflows(resp)
        assert len(workflows) == 1
        assert workflows[0]["name"] == "wf/abc"
        assert workflows[0]["primary_media_id"] == media_id

    def test_skips_workflow_without_primary_media_id(self):
        resp = {
            "data": {
                "workflows": [
                    {"name": "wf/no-media"},
                ]
            }
        }
        workflows = extract_video_workflows(resp)
        assert workflows == []

    def test_empty_for_old_schema(self):
        resp = {
            "data": {
                "operations": [{"operation": {"name": "op/abc"}}]
            }
        }
        assert extract_video_workflows(resp) == []

    def test_empty_response(self):
        assert extract_video_workflows({}) == []


# ── extract_video_operations ──────────────────────────────────────────────────

class TestExtractVideoOperations:
    def _make_poll_resp(
        self,
        name: str,
        status: str,
        media_id: str | None = None,
        fife_url: str | None = None,
    ) -> dict[str, Any]:
        video_meta: dict[str, Any] = {}
        if media_id:
            video_meta["mediaId"] = media_id
        if fife_url:
            video_meta["fifeUrl"] = fife_url
        return {
            "data": {
                "operations": [
                    {
                        "status": status,
                        "operation": {
                            "name": name,
                            "metadata": {"video": video_meta},
                        },
                    }
                ]
            }
        }

    def test_successful_operation(self):
        mid = str(uuid.uuid4())
        fife = f"https://flow-content.google/video/{mid}?Expires=123"
        resp = self._make_poll_resp("op/abc", "MEDIA_GENERATION_STATUS_SUCCESSFUL", mid, fife)
        ops = extract_video_operations(resp, requested=["op/abc"])
        assert len(ops) == 1
        assert ops[0]["done"] is True
        assert ops[0]["status"] == "MEDIA_GENERATION_STATUS_SUCCESSFUL"
        assert ops[0]["error"] is None
        assert len(ops[0]["media_entries"]) == 1
        assert ops[0]["media_entries"][0]["media_id"] == mid

    def test_pending_operation(self):
        resp = self._make_poll_resp("op/abc", "MEDIA_GENERATION_STATUS_PENDING")
        ops = extract_video_operations(resp, requested=["op/abc"])
        assert ops[0]["done"] is False
        assert ops[0]["media_entries"] == []

    def test_failed_operation(self):
        resp = self._make_poll_resp("op/abc", "MEDIA_GENERATION_STATUS_FAILED")
        ops = extract_video_operations(resp, requested=["op/abc"])
        assert ops[0]["done"] is True
        assert ops[0]["error"] == "MEDIA_GENERATION_STATUS_FAILED"

    def test_missing_operation_returns_not_done(self):
        resp = self._make_poll_resp("op/other", "MEDIA_GENERATION_STATUS_PENDING")
        ops = extract_video_operations(resp, requested=["op/missing"])
        assert ops[0]["name"] == "op/missing"
        assert ops[0]["done"] is False

    def test_uuid_recovered_from_fife_url(self):
        # Flow often omits mediaId but embeds UUID in fifeUrl
        mid = str(uuid.uuid4())
        fife = f"https://flow-content.google/video/{mid}?Expires=123"
        resp = self._make_poll_resp("op/abc", "MEDIA_GENERATION_STATUS_SUCCESSFUL", None, fife)
        ops = extract_video_operations(resp, requested=["op/abc"])
        assert ops[0]["media_entries"][0]["media_id"] == mid

    def test_preserves_requested_order(self):
        resp = {
            "data": {
                "operations": [
                    {"status": "MEDIA_GENERATION_STATUS_PENDING", "operation": {"name": "op/b"}},
                    {"status": "MEDIA_GENERATION_STATUS_PENDING", "operation": {"name": "op/a"}},
                ]
            }
        }
        ops = extract_video_operations(resp, requested=["op/a", "op/b"])
        assert ops[0]["name"] == "op/a"
        assert ops[1]["name"] == "op/b"


# ── FlowSDK.gen_video (mocked) ────────────────────────────────────────────────

class TestFlowSDKGenVideo:
    """Tests for FlowSDK.gen_video() using a mocked FlowClient."""

    def _make_sdk(self, api_request_side_effect=None, api_request_return=None):
        """Create a FlowSDK with a mocked client."""
        mock_client = MagicMock()
        mock_client.get_token.return_value = "ya29.fake_token"
        if api_request_side_effect:
            mock_client.api_request = AsyncMock(side_effect=api_request_side_effect)
        elif api_request_return is not None:
            mock_client.api_request = AsyncMock(return_value=api_request_return)
        else:
            mock_client.api_request = AsyncMock(return_value={})
        return FlowSDK(client=mock_client)

    def _make_upload_resp(self, media_id: str) -> dict[str, Any]:
        return {"status": 200, "data": {"media": {"name": media_id}}}

    def _make_video_submit_resp(self, op_name: str) -> dict[str, Any]:
        return {
            "status": 200,
            "data": {
                "operations": [
                    {"operation": {"name": op_name}}
                ]
            }
        }

    @pytest.fixture
    def tmp_image(self, tmp_path: Path) -> Path:
        """Create a minimal PNG file for testing."""
        img = tmp_path / "start.png"
        # Minimal 1x1 PNG bytes
        img.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00"
            b"\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18"
            b"\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        return img

    @pytest.mark.asyncio
    async def test_gen_video_returns_operation_name(self, tmp_image: Path):
        op_name = "operations/video-gen/abc123"
        upload_media_id = str(uuid.uuid4())

        # First call = upload, second call = video submit
        responses = [
            self._make_upload_resp(upload_media_id),
            self._make_video_submit_resp(op_name),
        ]
        sdk = self._make_sdk(api_request_side_effect=responses)

        with patch.object(sdk, "_fetch_paygate_tier", new=AsyncMock(return_value="PAYGATE_TIER_ONE")):
            result = await sdk.gen_video(
                start_image=tmp_image,
                prompt="A beautiful sunset",
                project_id="test-project-123",
            )

        assert result == op_name

    @pytest.mark.asyncio
    async def test_gen_video_raises_if_image_not_found(self):
        sdk = self._make_sdk()
        with pytest.raises(FileNotFoundError, match="start_image not found"):
            await sdk.gen_video(
                start_image=Path("/nonexistent/image.png"),
                prompt="test",
            )

    @pytest.mark.asyncio
    async def test_gen_video_raises_on_upload_error(self, tmp_image: Path):
        sdk = self._make_sdk(api_request_return={"error": "extension_disconnected"})
        with patch.object(sdk, "_fetch_paygate_tier", new=AsyncMock(return_value="PAYGATE_TIER_ONE")):
            with pytest.raises(RuntimeError, match="image upload failed"):
                await sdk.gen_video(
                    start_image=tmp_image,
                    prompt="test",
                    project_id="proj-123",
                )

    @pytest.mark.asyncio
    async def test_gen_video_raises_if_no_operation_name(self, tmp_image: Path):
        upload_media_id = str(uuid.uuid4())
        responses = [
            self._make_upload_resp(upload_media_id),
            {"status": 200, "data": {"operations": []}},  # empty operations
        ]
        sdk = self._make_sdk(api_request_side_effect=responses)
        with patch.object(sdk, "_fetch_paygate_tier", new=AsyncMock(return_value="PAYGATE_TIER_ONE")):
            with pytest.raises(RuntimeError, match="no operation names"):
                await sdk.gen_video(
                    start_image=tmp_image,
                    prompt="test",
                    project_id="proj-123",
                )

    @pytest.mark.asyncio
    async def test_gen_video_uses_captcha_video(self, tmp_image: Path):
        op_name = "operations/video-gen/xyz"
        upload_media_id = str(uuid.uuid4())
        responses = [
            self._make_upload_resp(upload_media_id),
            self._make_video_submit_resp(op_name),
        ]
        sdk = self._make_sdk(api_request_side_effect=responses)
        with patch.object(sdk, "_fetch_paygate_tier", new=AsyncMock(return_value="PAYGATE_TIER_ONE")):
            await sdk.gen_video(
                start_image=tmp_image,
                prompt="test",
                project_id="proj-123",
            )

        # Second call (video submit) should use VIDEO_GENERATION captcha
        second_call_kwargs = sdk._client.api_request.call_args_list[1][1]
        assert second_call_kwargs.get("captcha_action") == CAPTCHA_VIDEO

    @pytest.mark.asyncio
    async def test_gen_video_uses_correct_endpoint(self, tmp_image: Path):
        op_name = "operations/video-gen/xyz"
        upload_media_id = str(uuid.uuid4())
        responses = [
            self._make_upload_resp(upload_media_id),
            self._make_video_submit_resp(op_name),
        ]
        sdk = self._make_sdk(api_request_side_effect=responses)
        with patch.object(sdk, "_fetch_paygate_tier", new=AsyncMock(return_value="PAYGATE_TIER_ONE")):
            await sdk.gen_video(
                start_image=tmp_image,
                prompt="test",
                project_id="proj-123",
            )

        second_call_kwargs = sdk._client.api_request.call_args_list[1][1]
        assert second_call_kwargs.get("url") == VIDEO_I2V_URL

    @pytest.mark.asyncio
    async def test_gen_video_portrait_aspect(self, tmp_image: Path):
        op_name = "operations/video-gen/portrait"
        upload_media_id = str(uuid.uuid4())
        responses = [
            self._make_upload_resp(upload_media_id),
            self._make_video_submit_resp(op_name),
        ]
        sdk = self._make_sdk(api_request_side_effect=responses)
        with patch.object(sdk, "_fetch_paygate_tier", new=AsyncMock(return_value="PAYGATE_TIER_ONE")):
            result = await sdk.gen_video(
                start_image=tmp_image,
                prompt="test",
                aspect="9:16",
                project_id="proj-123",
            )
        assert result == op_name

        # Verify the request body uses portrait aspect
        second_call_kwargs = sdk._client.api_request.call_args_list[1][1]
        body = second_call_kwargs.get("body", {})
        assert body["requests"][0]["aspectRatio"] == "VIDEO_ASPECT_RATIO_PORTRAIT"


# ── FlowSDK.check_async (mocked) ─────────────────────────────────────────────

class TestFlowSDKCheckAsync:
    def _make_sdk(self, api_request_return: dict[str, Any]):
        mock_client = MagicMock()
        mock_client.api_request = AsyncMock(return_value=api_request_return)
        return FlowSDK(client=mock_client)

    def _make_poll_resp(self, op_name: str, status: str) -> dict[str, Any]:
        return {
            "status": 200,
            "data": {
                "operations": [
                    {
                        "status": status,
                        "operation": {"name": op_name},
                    }
                ]
            }
        }

    @pytest.mark.asyncio
    async def test_check_async_returns_raw_response(self):
        op_name = "operations/video-gen/abc"
        poll_resp = self._make_poll_resp(op_name, "MEDIA_GENERATION_STATUS_PENDING")
        sdk = self._make_sdk(api_request_return=poll_resp)

        result = await sdk.check_async(op_name)
        assert result == poll_resp

    @pytest.mark.asyncio
    async def test_check_async_uses_poll_endpoint(self):
        op_name = "operations/video-gen/abc"
        poll_resp = self._make_poll_resp(op_name, "MEDIA_GENERATION_STATUS_PENDING")
        sdk = self._make_sdk(api_request_return=poll_resp)

        await sdk.check_async(op_name)

        call_kwargs = sdk._client.api_request.call_args[1]
        assert call_kwargs.get("url") == VIDEO_POLL_URL

    @pytest.mark.asyncio
    async def test_check_async_sends_operation_name_in_body(self):
        op_name = "operations/video-gen/abc"
        poll_resp = self._make_poll_resp(op_name, "MEDIA_GENERATION_STATUS_PENDING")
        sdk = self._make_sdk(api_request_return=poll_resp)

        await sdk.check_async(op_name)

        call_kwargs = sdk._client.api_request.call_args[1]
        body = call_kwargs.get("body", {})
        assert body["operations"][0]["operation"]["name"] == op_name

    @pytest.mark.asyncio
    async def test_check_async_no_captcha(self):
        op_name = "operations/video-gen/abc"
        poll_resp = self._make_poll_resp(op_name, "MEDIA_GENERATION_STATUS_PENDING")
        sdk = self._make_sdk(api_request_return=poll_resp)

        await sdk.check_async(op_name)

        call_kwargs = sdk._client.api_request.call_args[1]
        # check_async should NOT use captcha
        assert call_kwargs.get("captcha_action") is None

    @pytest.mark.asyncio
    async def test_check_async_raises_on_transport_error(self):
        sdk = self._make_sdk(api_request_return={"error": "extension_disconnected"})
        with pytest.raises(RuntimeError, match="check_async failed"):
            await sdk.check_async("operations/video-gen/abc")

    @pytest.mark.asyncio
    async def test_check_async_does_not_loop(self):
        """check_async must make exactly ONE api_request call."""
        op_name = "operations/video-gen/abc"
        poll_resp = self._make_poll_resp(op_name, "MEDIA_GENERATION_STATUS_PENDING")
        sdk = self._make_sdk(api_request_return=poll_resp)

        await sdk.check_async(op_name)

        assert sdk._client.api_request.call_count == 1
