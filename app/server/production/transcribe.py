"""Remote-only STT, explicit selection, checksummed cache and stale-session protection."""
import hashlib
import json
import math
import time
from pathlib import Path

import httpx

from server.audio.remote import AudioUnavailable, connection, digest, request
from server.production.media import sha256


def transcribe(path: Path, language: str, root: Path, checkpoint) -> list[dict]:
    url, token, generation, health = connection.snapshot()
    revision = health.get("stt_revision")
    if "stt" not in health.get("capabilities", []) or not revision:
        raise ValueError("Bật STT trong Colab, kiểm tra và lưu lại kết nối trước khi xuất phụ đề STT.")
    payload = {"type": "stt", "audio_sha256": sha256(path), "language": language, "model_revision": revision}
    key = digest(payload)
    cache = root / "audio" / "transcripts" / f"{key}.json"
    def current():
        checkpoint()
        if connection.snapshot()[2] != generation:
            raise ValueError("Phiên Colab đã thay đổi. Xuất lượt mới với kết nối hiện tại.")
    if cache.exists():
        saved = json.loads(cache.read_text(encoding="utf-8"))
        content = saved["content"]
        if digest(content) == saved["checksum"]:
            current()
            return validate_segments(content)
        raise ValueError("Cache STT không khớp checksum; cần xóa file cache lỗi rồi thử lại.")
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("Mỗi file STT tối đa 32 MiB.")
    current()
    with path.open("rb") as stream:
        job = request(url, token, "POST", "/v1/stt/jobs?retry=true", data={"language": language, "model_revision": revision},
                      files={"file": ("narration.wav", stream, "audio/wav")}, headers={"Idempotency-Key": key})
    try:
        deadline = time.monotonic() + 600
        while job["status"] in ("queued", "running"):
            current()
            if time.monotonic() > deadline:
                raise ValueError("STT quá thời gian chờ. Kiểm tra Colab trước khi thử lại.")
            time.sleep(1)
            job = request(url, token, "GET", f"/v1/jobs/{key}")
        current()
        if job["status"] != "succeeded":
            raise ValueError("Colab chưa hoàn tất STT; kiểm tra runtime rồi xuất lượt mới.")
        with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:
            with client.stream("GET", url + f"/v1/jobs/{key}/result", headers={"Authorization": f"Bearer {token}"}) as response:
                if response.status_code != 200:
                    raise ValueError("Không tải được kết quả STT.")
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 2 * 1024 * 1024:
                        raise ValueError("Kết quả STT vượt giới hạn.")
        if hashlib.sha256(raw).hexdigest() != job.get("checksum"):
            raise ValueError("Checksum STT không khớp.")
        content = json.loads(raw)
        segments = validate_segments(content)
        current()
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"content": content, "checksum": digest(content)}, ensure_ascii=False), encoding="utf-8")
        return segments
    except (InterruptedError, AudioUnavailable, ValueError):
        try:
            request(url, token, "POST", f"/v1/jobs/{key}/cancel")
        except AudioUnavailable:
            pass
        raise


def validate_segments(content: dict) -> list[dict]:
    segments = content.get("segments", [])
    if not segments:
        raise ValueError("STT không nhận được lời nói. Chọn phụ đề theo cảnh hoặc kiểm tra file audio.")
    end = 0.0
    for segment in segments:
        start, stop = float(segment["start"]), float(segment["end"])
        if not all(math.isfinite(x) for x in (start, stop)) or start < end - .01 or stop <= start or not str(segment["text"]).strip():
            raise ValueError("Mốc thời gian STT không hợp lệ.")
        end = stop
    return segments
