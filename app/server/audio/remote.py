"""Remote audio transport and verified local cache. No model libraries are imported here."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
import threading
import time
import wave
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from server.audio.tts import TTSError, TTSResult


class AudioUnavailable(TTSError):
    def __init__(self, message: str, state: str = "unreachable"):
        super().__init__(message, backend="remote")
        self.state = state


def digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def validate_url(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
        host = parsed.hostname or ""
        port = parsed.port
    except ValueError as exc:
        raise AudioUnavailable("URL Colab không hợp lệ.", "invalid_url") from exc
    if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ("", "/") or port not in (None, 443)
            or not re.fullmatch(r"[a-z0-9-]+\.trycloudflare\.com", host)):
        raise AudioUnavailable("Nhập URL HTTPS gốc của Quick Tunnel (*.trycloudflare.com).", "invalid_url")
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise AudioUnavailable("Không phân giải được tên miền Colab.") from exc
    if not addresses or any(not ipaddress.ip_address(entry[4][0]).is_global for entry in addresses):
        raise AudioUnavailable("Địa chỉ worker phải là địa chỉ Internet công khai.", "invalid_url")
    return f"https://{host}"


class AudioConnection:
    """A token lives only in this process; persisted metadata never contains credentials."""

    def __init__(self):
        self.lock = threading.RLock()
        self.url = ""
        self.token = ""
        self.health: dict = {}
        self.voices: list[dict] = []
        self.generation = 0
        self.state = "not_configured"

    def snapshot(self) -> tuple[str, str, int, dict]:
        with self.lock:
            if not self.token:
                raise AudioUnavailable("Bật Colab và nhập URL cùng token để tiếp tục.", "not_configured")
            return self.url, self.token, self.generation, dict(self.health)

    def check(self, url: str, token: str) -> dict:
        url = validate_url(url)
        if len(token) < 32 or len(token) > 512 or any(c.isspace() for c in token):
            raise AudioUnavailable("Token phiên không hợp lệ.", "unauthorized")
        health = request(url, token, "GET", "/v1/health")
        voices = request(url, token, "GET", "/v1/voices")
        if (health.get("api_version") != "1" or "tts" not in health.get("capabilities", [])
                or not health.get("persistent_jobs") or not isinstance(voices, list)):
            raise AudioUnavailable("Worker không tương thích API v1 hoặc thiếu checkpoint bền vững.", "incompatible")
        if health.get("status") != "ready" or not health.get("model_revision"):
            raise AudioUnavailable("Colab đang nạp model; hãy kiểm tra lại sau.", "warming_up")
        return {"url": url, "health": health, "voices": voices,
                "fingerprint": digest({"url": url, "token": token})}

    def save(self, checked: dict, token: str, data_dir: Path) -> None:
        with self.lock:
            self.url, self.token = checked["url"], token
            self.health, self.voices = checked["health"], checked["voices"]
            self.generation += 1
            self.state = "ready"
            path = data_dir / "audio-connection.json"
            path.write_text(json.dumps({"url": self.url, "health": self.health, "voices": self.voices}), encoding="utf-8")

    def disconnect(self) -> None:
        with self.lock:
            self.token = ""
            self.generation += 1
            self.state = "not_configured"

    def public(self, data_dir: Path) -> dict:
        with self.lock:
            stored = {}
            path = data_dir / "audio-connection.json"
            if path.is_file():
                stored = json.loads(path.read_text(encoding="utf-8"))
            return {"url": self.url or stored.get("url", ""), "configured": bool(self.token),
                    "state": self.state, "generation": self.generation,
                    "health": self.health or stored.get("health", {}),
                    "voices": self.voices or stored.get("voices", [])}


connection = AudioConnection()


def request(url: str, token: str, method: str, path: str, **kwargs):
    try:
        with httpx.Client(timeout=httpx.Timeout(15, connect=5), follow_redirects=False, trust_env=False) as client:
            response = client.request(method, url + path, headers={"Authorization": f"Bearer {token}",
                                      **kwargs.pop("headers", {})}, **kwargs)
        if response.status_code in (401, 403):
            raise AudioUnavailable("Token Colab đã sai hoặc hết phiên.", "unauthorized")
        if response.status_code == 429:
            raise AudioUnavailable("Worker đang đầy; thử tiếp tục sau.", "busy")
        if response.status_code >= 500:
            raise AudioUnavailable("Colab hoặc tunnel chưa sẵn sàng.")
        if response.status_code not in (200, 202):
            raise AudioUnavailable(f"Worker từ chối yêu cầu (HTTP {response.status_code}).", "incompatible")
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise AudioUnavailable("Không kết nối được API Colab hoặc phản hồi không hợp lệ.") from exc


def split_text(text: str, limit: int = 1200) -> list[str]:
    parts: list[str] = []
    current = ""
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text.strip()):
        for word in sentence.split():
            if len(word) > limit:
                raise TTSError("Một từ dài hơn giới hạn đoạn âm thanh.", "remote")
            candidate = f"{current} {word}".strip()
            if len(candidate) > limit:
                parts.append(current)
                current = word
            else:
                current = candidate
        if current and len(current) >= limit // 2:
            parts.append(current)
            current = ""
    if current:
        parts.append(current)
    if not parts:
        raise TTSError("Vui lòng nhập nội dung cần đọc.", "remote")
    return parts


def make_segments(text: str, voice: str, language: str, speed: float, revision: str) -> list[dict]:
    return [{"input": payload, "key": digest(payload)} for payload in (
        {"text": part, "voice_id": voice, "language": language, "speed": float(speed),
         "model_revision": revision, "output_format": "wav"} for part in split_text(text))]


def cache_path(data_dir: Path, key: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{64}", key):
        raise TTSError("Invalid audio cache key", "remote")
    return data_dir / "audio" / "cache" / f"{key}.wav"


def cached(data_dir: Path, key: str) -> bool:
    path = cache_path(data_dir, key)
    meta = path.with_suffix(".json")
    if not path.is_file() or not meta.is_file():
        return False
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest() == json.loads(meta.read_text())["checksum"]
    except (OSError, ValueError, KeyError):
        return False


def _read_complete_pcm(audio) -> bytes:
    pcm = audio.readframes(audio.getnframes())
    if len(pcm) != audio.getnframes() * audio.getnchannels() * audio.getsampwidth():
        raise TTSError("WAV thiếu dữ liệu PCM; cần tạo hoặc tải lại đoạn audio.", "remote")
    return pcm


def store_audio(data_dir: Path, key: str, content: bytes, checksum: str) -> None:
    if len(content) > 32 * 1024 * 1024 or hashlib.sha256(content).hexdigest() != checksum:
        raise AudioUnavailable("File audio tải về không khớp checksum.")
    path = cache_path(data_dir, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{key}.{threading.get_ident()}.part")
    temp.write_bytes(content)
    try:
        with wave.open(str(temp), "rb") as audio:
            if audio.getnframes() <= 0 or audio.getsampwidth() != 2:
                raise TTSError("Worker trả về WAV không hợp lệ.", "remote")
            _read_complete_pcm(audio)
        temp.replace(path)
        path.with_suffix(".json").write_text(json.dumps({"checksum": checksum}))
    finally:
        temp.unlink(missing_ok=True)


def download(url: str, token: str, data_dir: Path, key: str, checksum: str) -> None:
    try:
        with httpx.Client(timeout=httpx.Timeout(60, connect=5), follow_redirects=False, trust_env=False) as client:
            with client.stream("GET", f"{url}/v1/jobs/{key}/result", headers={"Authorization": f"Bearer {token}"}) as response:
                if response.status_code != 200:
                    raise AudioUnavailable("Kết quả chưa tải được; hãy tiếp tục để tải lại.")
                content = bytearray()
                for block in response.iter_bytes():
                    content.extend(block)
                    if len(content) > 32 * 1024 * 1024:
                        raise TTSError("Audio vượt giới hạn tải về.", "remote")
        store_audio(data_dir, key, bytes(content), checksum)
    except httpx.HTTPError as exc:
        raise AudioUnavailable("Mất kết nối khi tải audio.") from exc


def combine(data_dir: Path, segments: list[dict], destination: Path) -> float:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".part")
    frames = 0
    rate = 24000
    try:
        with wave.open(str(temporary), "wb") as output:
            expected = None
            for segment in segments:
                if not cached(data_dir, segment["key"]):
                    raise AudioUnavailable("Một đoạn cache bị thiếu hoặc hỏng.")
                with wave.open(str(cache_path(data_dir, segment["key"])), "rb") as source:
                    params = (source.getnchannels(), source.getsampwidth(), source.getframerate())
                    if expected is None:
                        expected = params
                        output.setnchannels(params[0])
                        output.setsampwidth(params[1])
                        output.setframerate(params[2])
                        rate = params[2]
                    elif expected != params:
                        raise TTSError("Các đoạn audio khác định dạng; cần tạo lại với cùng model.", "remote")
                    output.writeframes(_read_complete_pcm(source))
                    frames += source.getnframes()
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return frames / rate


class RemoteProvider:
    def __init__(self, settings):
        self.settings = settings

    def backend_name(self) -> str:
        return "remote"

    def is_available(self) -> bool:
        return True  # Cache may satisfy the request even when Colab is offline.

    def synthesize(self, text: str, voice: str, output_path: Path, speed: float = 1.0) -> TTSResult:
        metadata = connection.public(self.settings.data_dir)
        revision = metadata["health"].get("model_revision")
        if not revision:
            raise AudioUnavailable("Chưa có cấu hình model. Mở Kết nối Colab trước.", "not_configured")
        descriptor = next((item for item in metadata["voices"] if item["id"] == voice), None)
        if descriptor is None:
            raise AudioUnavailable("Giọng không có trong worker đã lưu. Kiểm tra và lưu lại kết nối.", "incompatible")
        segments = make_segments(text, voice, descriptor["language"], speed, revision)
        for segment in segments:
            if cached(self.settings.data_dir, segment["key"]):
                continue
            url, token, generation, _ = connection.snapshot()
            deadline = time.monotonic() + 600
            job = request(url, token, "POST", "/v1/tts/jobs", json=segment["input"], headers={"Idempotency-Key": segment["key"]})
            while job["status"] in ("queued", "running"):
                if time.monotonic() > deadline or connection.generation != generation:
                    raise AudioUnavailable("Phiên đã đổi hoặc hết thời gian chờ. Tiếp tục để nhận lại kết quả.")
                time.sleep(3)
                job = request(url, token, "GET", f"/v1/jobs/{segment['key']}")
            if job["status"] != "succeeded":
                raise TTSError("Tạo giọng đọc chưa hoàn thành; kiểm tra worker.", "remote")
            download(url, token, self.settings.data_dir, segment["key"], job["checksum"])
        output_path = output_path.with_suffix(".wav")
        duration = combine(self.settings.data_dir, segments, output_path)
        return TTSResult(True, output_path, duration, "remote")
