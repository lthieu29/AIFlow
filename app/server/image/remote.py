"""Bounded Colab transport with process-only credentials and verified images."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import threading
import uuid

import httpx
from PIL import Image, ImageOps
from pydantic import SecretStr

from server.audio.remote import AudioUnavailable, validate_url

MAX_IMAGE = 10 * 1024**2
MAX_RESPONSE = 15 * 1024**2


class ImageUnavailable(ValueError):
    def __init__(self, message: str, state: str = "unreachable"):
        super().__init__(message)
        self.state = state


def digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def request(url: str, token: SecretStr, method: str, path: str, **kwargs) -> dict:
    try:
        url = validate_url(url)
        with httpx.Client(timeout=httpx.Timeout(15, connect=5), follow_redirects=False, trust_env=False) as client:
            with client.stream(method, url + path, headers={"Authorization": f"Bearer {token.get_secret_value()}"}, **kwargs) as response:
                if response.status_code in (401, 403):
                    raise ImageUnavailable("Token Colab ảnh sai hoặc hết phiên.", "unauthorized")
                if response.status_code == 404:
                    raise ImageUnavailable("Worker không còn lưu tác vụ này; kiểm tra Colab. Không tự tạo lại.", "missing_job")
                if response.status_code == 429:
                    raise ImageUnavailable("Worker ảnh đang đầy; kiểm tra lại sau.", "busy")
                if response.status_code not in (200, 202):
                    raise ImageUnavailable("Colab ảnh hoặc tunnel chưa sẵn sàng.")
                content = bytearray()
                for block in response.iter_bytes():
                    content.extend(block)
                    if len(content) > MAX_RESPONSE:
                        raise ImageUnavailable("Phản hồi worker ảnh vượt giới hạn.", "invalid_result")
        data = json.loads(content)
        if not isinstance(data, dict):
            raise ImageUnavailable("Phản hồi worker ảnh không hợp lệ.", "incompatible")
        return data
    except AudioUnavailable as exc:
        message = ("URL Colab ảnh phải là HTTPS Quick Tunnel công khai." if exc.state == "invalid_url"
                   else "Không phân giải được tên miền Colab ảnh; kiểm tra kết nối Internet và tunnel.")
        raise ImageUnavailable(message, exc.state) from exc
    except (httpx.HTTPError, ValueError) as exc:
        if isinstance(exc, ImageUnavailable):
            raise
        raise ImageUnavailable("Không nhận được phản hồi hợp lệ từ Colab ảnh.") from exc


class ImageConnection:
    def __init__(self):
        self.lock = threading.RLock()
        self.url = ""
        self.token = SecretStr("")
        self.health: dict = {}
        self.state = "not_configured"

    def public(self) -> dict:
        with self.lock:
            return {"url": self.url, "configured": bool(self.token.get_secret_value()),
                    "state": self.state, "health": dict(self.health)}

    def snapshot(self):
        with self.lock:
            if not self.token.get_secret_value():
                raise ImageUnavailable("Bật Colab ảnh và lưu URL/token ở Kết nối.", "not_configured")
            return self.url, self.token, dict(self.health)

    def configure(self, url: str, token: SecretStr) -> dict:
        if not token.get_secret_value() and not url:
            with self.lock:
                self.url, self.token, self.health, self.state = "", SecretStr(""), {}, "not_configured"
            return self.public()
        value = token.get_secret_value()
        if len(url) > 300:
            raise ImageUnavailable("URL Colab ảnh không hợp lệ.", "invalid_url")
        if not 32 <= len(value) <= 512 or not value.isascii() or any(c.isspace() for c in value):
            raise ImageUnavailable("Token phiên Colab ảnh không hợp lệ.", "unauthorized")
        health = self.check_health(url, token)
        with self.lock:
            self.url, self.token, self.health, self.state = url.strip().rstrip("/"), token, health, "ready"
        return self.public()

    @staticmethod
    def check_health(url: str, token: SecretStr) -> dict:
        data = request(url, token, "GET", "/v1/health")
        revision = data.get("model_revision")
        try:
            worker_id = str(uuid.UUID(data.get("worker_id", "")))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ImageUnavailable("Worker ảnh thiếu định danh phiên bền vững.", "incompatible") from exc
        if (data.get("api_version") != "1" or not isinstance(data.get("capabilities"), list)
                or "image" not in data["capabilities"]
                or not any(capability in data["capabilities"] for capability in ("reference_image", "virtual_try_on"))
                or data.get("persistent_jobs") is not True or not isinstance(revision, str)
                or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", revision)):
            raise ImageUnavailable("Worker ảnh không tương thích API v1.", "incompatible")
        if data.get("status") != "ready":
            raise ImageUnavailable("Colab ảnh đang nạp model; kiểm tra lại sau.", "warming_up")
        return {"api_version": "1", "capabilities": [capability for capability in ("image", "reference_image", "text_to_image", "virtual_try_on")
                if capability in data["capabilities"]],
                "persistent_jobs": True, "worker_id": worker_id, "model_revision": revision, "status": "ready"}

    def check(self) -> dict:
        url, token, _ = self.snapshot()
        try:
            health = self.check_health(url, token)
        except ImageUnavailable as exc:
            with self.lock:
                self.state = exc.state
            raise
        with self.lock:
            if self.url == url and self.token == token:
                self.health, self.state = health, "ready"
        return self.public()


connection = ImageConnection()


def reference_png(raw: bytes) -> bytes:
    if len(raw) > MAX_IMAGE:
        raise ImageUnavailable("Ảnh tham chiếu vượt 10 MiB.", "invalid_input")
    try:
        with Image.open(io.BytesIO(raw)) as source:
            if min(source.size) < 32 or max(source.size) > 8192 or source.width * source.height > 40_000_000:
                raise ValueError("Image dimensions")
            source.load()
            image = ImageOps.exif_transpose(source)
            if "A" in image.getbands() or "transparency" in image.info:
                rgba = image.convert("RGBA")
                image = Image.alpha_composite(Image.new("RGBA", rgba.size, "white"), rgba)
            image = image.convert("RGB")
            if max(image.size) > 2048:
                image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
            if min(image.size) < 32:
                raise ValueError("Reference is too narrow after normalization")
            image.info.clear()
            result = io.BytesIO()
            image.save(result, "PNG")
            content = result.getvalue()
        if len(content) > 5 * 1024**2:
            raise ValueError("Reference PNG exceeds limit")
        return content
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ImageUnavailable("Ảnh tham chiếu phải hợp lệ, cạnh 32–8192px, tối đa 40 megapixel; PNG chuẩn hóa dưới 5 MiB và cạnh ngắn từ 32px.", "invalid_input") from exc


def verify_result(result: dict, width: int, height: int) -> bytes:
    try:
        encoded = result["data"]
        if (result["mime"] != "image/png" or not isinstance(encoded, str)
                or len(encoded) > (MAX_IMAGE + 2) // 3 * 4
                or type(result["width"]) is not int or type(result["height"]) is not int
                or (result["width"], result["height"]) != (width, height)):
            raise ValueError("Invalid artifact descriptor")
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > MAX_IMAGE or hashlib.sha256(raw).hexdigest() != result["sha256"]:
            raise ValueError("Invalid artifact checksum")
        with Image.open(io.BytesIO(raw)) as image:
            if image.format != "PNG" or image.size != (width, height) or getattr(image, "n_frames", 1) != 1:
                raise ValueError("Invalid PNG")
            image.load()
        return raw
    except (KeyError, TypeError, ValueError, OSError, Image.DecompressionBombError) as exc:
        raise ImageUnavailable("Kết quả ảnh không khớp PNG, kích thước hoặc checksum. Kiểm tra worker.", "invalid_result") from exc
