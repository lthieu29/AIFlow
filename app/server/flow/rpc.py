"""Current Flow protobuf RPC contract, verified against the Angular client and live Lite requests."""
from __future__ import annotations

import base64
import hashlib
import mimetypes
import re
import uuid
from pathlib import Path
from typing import Any

from server.flow.client import FlowClient


class FlowRPCError(RuntimeError):
    """Safe transport diagnostics; no response body or browser credentials."""
    def __init__(self, response: dict):
        raw_code = str(response.get("error") or "FLOW_RPC_FAILED").split(":", 1)[0]
        self.code = raw_code if re.fullmatch(r"[A-Z0-9_]+", raw_code) else "FLOW_RPC_FAILED"
        self.status_code = response.get("status") if isinstance(response.get("status"), int) else None
        self.rpc_status_code = response.get("rpcStatus") if isinstance(response.get("rpcStatus"), int) else None
        self.request_sent = response.get("requestSent")
        self.phase = response.get("phase") if response.get("phase") in ("session", "captcha", "fetch", "decode") else None
        self.source_error_type = response.get("errorType") if response.get("errorType") in (
            "TypeError", "ReferenceError", "SyntaxError", "Error",
        ) else None
        super().__init__(self.code)


def field(value: Any, index: int, default=None):
    return value[index] if isinstance(value, list) and len(value) > index and value[index] is not None else default


def client_context(project_id: str) -> list:
    # eK: tool=22, projectId field6, recaptchaContext field11.
    return [None, 22, None, None, None, project_id, None, None, None, None, ["", 1]]


def metadata() -> list:
    return [None, None, None, None, str(uuid.uuid4()), str(uuid.uuid4())]


def video_request(prompt: str, model_key: str, aspect: str, project_id: str, media_id: str | None = None) -> list:
    if aspect not in ("9:16", "16:9"):
        raise ValueError("Flow video supports 9:16 or 16:9.")
    structured_prompt = [None, None, [[[prompt]]]]
    item = [structured_prompt, model_key, 1 if aspect == "9:16" else 2, None]
    if media_id:
        item.extend([[None, media_id], metadata()])
    else:
        item.append(metadata())
    return [[item], client_context(project_id), [str(uuid.uuid4()), 2]]


class FlowRPC:
    def __init__(self, client: FlowClient):
        self.client = client

    async def preflight_ui(self, project_id: str) -> None:
        response = await self.client.flow_ui_request(project_id, preflight_only=True)
        if response.get("error") or response.get("status", 200) >= 400:
            raise FlowRPCError(response)

    async def submit_ui(self, prompt: str, aspect: str, project_id: str, reference_image: Path | None = None,
                        allow_silent_video: bool = False, reference_mode: str = "ingredients") -> str:
        if aspect not in ("16:9", "9:16"):
            raise ValueError("Flow video supports 9:16 or 16:9.")
        if reference_mode not in ("ingredients", "first_frame") or (reference_mode == "first_frame" and reference_image is None):
            raise ValueError("Invalid reference_mode or missing first-frame PNG.")
        reference = None
        if reference_image is not None:
            if reference_image.stat().st_size > 5 * 1024**2:
                raise ValueError("Flow reference PNG must be at most 5 MiB.")
            data = reference_image.read_bytes()
            if not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) > 5 * 1024**2:
                raise ValueError("Flow reference must be a PNG image at most 5 MiB.")
            digest = hashlib.sha256(data).hexdigest()
            reference = {"base64": base64.b64encode(data).decode("ascii"), "sha256": digest,
                         "name": f"aiflow-reference-{digest}.png"}
        response = await self.client.flow_ui_request(project_id, prompt, aspect, allow_silent_video=allow_silent_video,
                                                    reference_mode=reference_mode,
                                                    **({"reference": reference} if reference else {}))
        if response.get("error") or response.get("status", 200) >= 400:
            raise FlowRPCError(response)
        data = response.get("data") or {}
        media_id = data.get("mediaId")
        if data.get("projectId") != project_id or not isinstance(media_id, str) or not re.fullmatch(r"[0-9a-fA-F-]{36}", media_id):
            raise FlowRPCError({"error": "FLOW_UI_SUBMISSION_UNCONFIRMED", "requestSent": True})
        return f"rpc:{project_id}:{media_id}"

    async def preflight(self, project_id: str) -> None:
        """Inspect page capability without executing captcha or submitting a request."""
        response = await self.client.flow_rpc_request(
            "YhhmEf", [], project_id, captcha_action="VIDEO_GENERATION", preflight_only=True,
        )
        if response.get("error") or response.get("status", 200) >= 400:
            raise FlowRPCError(response)

    async def request(self, rpc_id: str, body: list, project_id: str, action: str | None = None) -> Any:
        response = await self.client.flow_rpc_request(rpc_id, body, project_id, captcha_action=action)
        if response.get("error") or response.get("status", 200) >= 400:
            raise FlowRPCError(response)
        if not isinstance(response.get("data"), list):
            raise RuntimeError(f"Flow RPC {rpc_id} returned no protobuf payload.")
        return response["data"]

    async def submit(
        self, prompt: str, model_key: str, aspect: str, project_id: str, start_image: Path | None = None,
    ) -> str:
        media_id = None
        if start_image is not None:
            mime = mimetypes.guess_type(str(start_image))[0] or "image/png"
            upload = [
                client_context(project_id), base64.b64encode(start_image.read_bytes()).decode("ascii"),
                mime, True, None, None, None, False, start_image.name,
            ]
            response = await self.request("maseQ", upload, project_id, "UPLOAD_IMAGE")
            media_id = field(field(response, 0), 0)
            if not media_id:
                raise RuntimeError("Flow image upload returned no media ID.")
        response = await self.request(
            "eb1hJf" if media_id else "YhhmEf",
            video_request(prompt, model_key, aspect, project_id, media_id), project_id, "VIDEO_GENERATION",
        )
        entries = field(response, 3, [])
        generated_id = field(field(entries, 0), 0)
        if not generated_id:
            raise RuntimeError("Flow video submission returned no media ID.")
        # Keep enough information to poll on the same project tab after a restart.
        return f"rpc:{project_id}:{generated_id}"

    async def check_async(self, operation_name: str) -> dict[str, Any]:
        _, project_id, media_id = operation_name.split(":", 2)
        response = await self.request("jwpduf", [None, None, [[media_id]]], project_id)
        entries = field(response, 2, [])
        media = next((entry for entry in entries if field(entry, 0) == media_id), None)
        state = field(field(field(media, 5), 8), 0)
        done = state in (3, 4, 5, 7)
        operation: dict[str, Any] = {"name": operation_name, "done": done}
        if state in (4, 5, 7):
            operation["error"] = {"message": "Google Flow video generation failed or was canceled."}
        elif state == 3:
            # Poll responses omit the downloadable URL; GetMedia returns it.
            media = await self.request("as29s", [media_id], project_id)
            url = field(field(field(media, 7), 0), 8)
            if not isinstance(url, str) or not url.startswith("https://"):
                raise RuntimeError("Generated Flow video has no downloadable URL.")
            operation["metadata"] = {"video": {"mediaId": media_id, "fifeUrl": url}}
        return {"status": 200, "data": {"operations": [{
            "operation": operation,
            "status": "MEDIA_GENERATION_STATUS_SUCCESSFUL" if state == 3
            else "MEDIA_GENERATION_STATUS_FAILED" if done else "MEDIA_GENERATION_STATUS_PENDING",
        }]}}
