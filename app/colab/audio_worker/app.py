"""Personal Colab audio worker. Run only in the remote runtime, never in AIFlow local."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

ROOT = Path(os.environ.get("AIFLOW_WORKER_STORAGE", "/content/drive/MyDrive/AIFlow/audio-worker"))
TOKEN = os.environ.get("AIFLOW_WORKER_TOKEN", "")
RUNTIME_ID = uuid.uuid4().hex
VOICES = ("af_heart", "af_bella", "am_adam", "am_michael")
ENGINE = "kokoro"
LANGUAGES = ["en"]
VOICE_METADATA: list[dict] = []
REVISION = ""
PIPELINE = None
VOICE_FILES: dict[str, str] = {}
LOCK = threading.RLock()
EXECUTOR = ThreadPoolExecutor(max_workers=1)
ACTIVE: set[str] = set()
STT_MODEL = None
STT_REVISION = ""
CONTROL_BUSY = False


class TTSInput(BaseModel):
    text: str = Field(min_length=1, max_length=1500)
    voice_id: str
    language: Literal["en", "vi"] = "en"
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    model_revision: str
    output_format: Literal["wav"] = "wav"


def digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def load_model() -> None:
    """Pin the first downloaded model revision on Drive and reuse it on later sessions."""
    global PIPELINE, REVISION, VOICE_FILES
    import torch
    from huggingface_hub import HfApi, hf_hub_download
    from kokoro import KModel, KPipeline

    if not torch.cuda.is_available():
        raise RuntimeError("Select a GPU runtime in Colab. CPU fallback is disabled.")
    ROOT.mkdir(parents=True, exist_ok=True)
    pin = ROOT / "kokoro-revision.txt"
    REVISION = pin.read_text().strip() if pin.exists() else HfApi().model_info("hexgrad/Kokoro-82M").sha
    pin.write_text(REVISION)

    def download(name: str) -> str:
        return hf_hub_download("hexgrad/Kokoro-82M", name, revision=REVISION, cache_dir=str(ROOT / "model-cache"))

    model = KModel(config=download("config.json"), model=download("kokoro-v1_0.pth")).to("cuda").eval()
    PIPELINE = KPipeline(lang_code="a", model=model)
    VOICE_FILES = {voice: download(f"voices/{voice}.pt") for voice in VOICES}


def authorize(authorization: str = Header(default="")) -> None:
    if len(TOKEN) < 32 or not secrets.compare_digest(authorization, f"Bearer {TOKEN}"):
        raise HTTPException(401, "Invalid session token")


app = FastAPI(title="AIFlow Audio Worker", docs_url=None, redoc_url=None, openapi_url=None,
              dependencies=[Depends(authorize)])


def manifest_path(job_id: str) -> Path:
    if len(job_id) != 64 or any(c not in "0123456789abcdef" for c in job_id):
        raise HTTPException(404, "Unknown job")
    return ROOT / "jobs" / f"{job_id}.json"


def read_job(job_id: str) -> dict:
    path = manifest_path(job_id)
    if not path.is_file():
        raise HTTPException(404, "Unknown job")
    return json.loads(path.read_text(encoding="utf-8"))


def save_job(job: dict) -> None:
    path = manifest_path(job["job_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def process(job_id: str) -> None:
    try:
        with LOCK:
            job = read_job(job_id)
            if job["status"] == "cancelled":
                return
            job.update(status="running", runtime_id=RUNTIME_ID, updated_at=time.time())
            save_job(job)
        import numpy as np
        import soundfile as sf

        request = job["input"]
        chunks = []
        for result in PIPELINE(request["text"], voice=VOICE_FILES[request["voice_id"]], speed=request["speed"]):
            with LOCK:
                if read_job(job_id)["status"] == "cancel_requested":
                    job.update(status="cancelled", updated_at=time.time())
                    save_job(job)
                    return
            audio = result.audio if hasattr(result, "audio") else result[2]
            if audio is not None:
                chunks.append(audio.cpu().numpy() if hasattr(audio, "cpu") else audio)
        if not chunks:
            raise RuntimeError("Model returned no audio")
        audio = np.concatenate(chunks)
        result_path = ROOT / "jobs" / f"{job_id}.wav"
        temp = result_path.with_suffix(".part")
        sf.write(str(temp), audio, 24000, format="WAV", subtype="PCM_16")
        checksum = hashlib.sha256(temp.read_bytes()).hexdigest()
        with LOCK:
            if read_job(job_id)["status"] == "cancel_requested":
                temp.unlink(missing_ok=True)
                job.update(status="cancelled", updated_at=time.time())
            else:
                temp.replace(result_path)
                job.update(status="succeeded", checksum=checksum, duration_sec=len(audio) / 24000,
                           size_bytes=result_path.stat().st_size, updated_at=time.time())
            save_job(job)
    except Exception:
        with LOCK:
            job = read_job(job_id)
            job.update(status="failed", error="Audio generation failed; inspect the Colab runtime.", updated_at=time.time())
            save_job(job)
    finally:
        with LOCK:
            ACTIVE.discard(job_id)


@app.get("/v1/health")
def health() -> dict:
    with LOCK:
        return {"api_version": "1", "runtime_id": RUNTIME_ID,
                "status": "ready" if PIPELINE is not None else "warming_up",
                "capabilities": ["tts"] + (["stt"] if STT_MODEL is not None else []),
                "stt_revision": STT_REVISION, "engine": ENGINE, "model_revision": REVISION,
                "languages": LANGUAGES, "max_text_chars": 1500, "max_concurrency": 1,
                "queue_depth": len(ACTIVE), "persistent_jobs": True}


@app.get("/v1/voices")
def voices() -> list[dict]:
    if VOICE_METADATA:
        return VOICE_METADATA
    return [{"id": v, "name": v.replace("_", " "), "language": "en", "backend": "remote",
             "gender": "female" if v.startswith("af") else "male", "description": "Kokoro English",
             "is_custom": False, "demo_audio_path": None} for v in VOICES]


@app.post("/v1/tts/jobs", status_code=202)
def submit(body: TTSInput, idempotency_key: str = Header(alias="Idempotency-Key"), retry: bool = False) -> dict:
    if PIPELINE is None:
        raise HTTPException(503, "Model is warming up")
    if body.language not in LANGUAGES:
        raise HTTPException(422, "Language is not available on this worker")
    if body.voice_id not in VOICES or body.model_revision != REVISION:
        raise HTTPException(422, "Voice or model revision is not available")
    payload = body.model_dump()
    job_id = digest(payload)
    if idempotency_key != job_id:
        raise HTTPException(409, "Idempotency key must match the canonical payload hash")
    with LOCK:
        if CONTROL_BUSY or PIPELINE is None or body.model_revision != REVISION:
            raise HTTPException(409, "Worker is training or changing voice; reconnect after it finishes")
        path = manifest_path(job_id)
        job = read_job(job_id) if path.exists() else {
            "job_id": job_id, "input": payload, "status": "queued", "created_at": time.time(),
        }
        if job["input"] != payload:
            raise HTTPException(409, "Payload differs from the persisted job")
        if job_id in ACTIVE:
            return {k: v for k, v in job.items() if k != "input"}
        if job["status"] in ("failed", "cancelled") and not retry:
            return {k: v for k, v in job.items() if k != "input"}
        if job["status"] == "succeeded" and (ROOT / "jobs" / f"{job_id}.wav").is_file():
            return {k: v for k, v in job.items() if k != "input"}
        if len(ACTIVE) >= 16:
            raise HTTPException(429, "Worker queue is full", headers={"Retry-After": "10"})
        job.update(status="queued", runtime_id=RUNTIME_ID, updated_at=time.time())
        job.pop("error", None)
        save_job(job)
        ACTIVE.add(job_id)
        EXECUTOR.submit(process, job_id)
        return {k: v for k, v in job.items() if k != "input"}


@app.get("/v1/jobs/{job_id}")
def status(job_id: str) -> dict:
    with LOCK:
        job = read_job(job_id)
        if job["status"] in ("queued", "running", "cancel_requested") and job_id not in ACTIVE:
            job["status"] = "interrupted"
        return {k: v for k, v in job.items() if k != "input"}


@app.get("/v1/jobs/{job_id}/result")
def result(job_id: str) -> FileResponse:
    job = read_job(job_id)
    is_stt = job.get("type") == "stt"
    path = ROOT / "jobs" / f"{job_id}{'.transcript.json' if is_stt else '.wav'}"
    if job["status"] != "succeeded" or not path.is_file():
        raise HTTPException(409, "Result is not ready")
    return FileResponse(path, media_type="application/json" if is_stt else "audio/wav", headers={"X-Checksum-SHA256": job["checksum"]})


@app.post("/v1/jobs/{job_id}/cancel")
def cancel(job_id: str) -> dict:
    with LOCK:
        job = read_job(job_id)
        if job["status"] not in ("succeeded", "failed", "cancelled"):
            job["status"] = "cancel_requested" if job["status"] == "running" and job_id in ACTIVE else "cancelled"
            save_job(job)
        return {"job_id": job_id, "status": job["status"]}


def run_batch(manifest: dict, output_zip: Path) -> None:
    """Use the same contract in an interactive notebook without exposing an HTTP API."""
    import zipfile

    if PIPELINE is None or CONTROL_BUSY:
        raise RuntimeError("Load the selected voice before batch; no automatic model fallback")
    results = []
    for item in manifest["segments"]:
        body = TTSInput(**item["input"])
        job = submit(body, item["key"], retry=True)
        while job["status"] in ("queued", "running"):
            time.sleep(1)
            job = status(job["job_id"])
        if job["status"] != "succeeded":
            raise RuntimeError(f"Batch segment failed: {job['job_id']}")
        results.append(job)
    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps({"api_version": "1", "results": results}))
        for job in results:
            archive.write(ROOT / "jobs" / f"{job['job_id']}.wav", f"{job['job_id']}.wav")


def load_stt_model() -> None:
    """Explicit notebook action. Small multilingual model, remote GPU only."""
    global STT_MODEL, STT_REVISION
    import torch
    from faster_whisper import WhisperModel
    from huggingface_hub import HfApi, snapshot_download

    if not torch.cuda.is_available():
        raise RuntimeError("STT requires a Colab GPU runtime.")
    with LOCK:
        if ACTIVE:
            raise RuntimeError("Wait for current audio jobs before loading STT.")
        ROOT.mkdir(parents=True, exist_ok=True)
        pin = ROOT / "whisper-small-revision.txt"
        revision = pin.read_text().strip() if pin.exists() else HfApi().model_info("Systran/faster-whisper-small").sha
        model_path = snapshot_download("Systran/faster-whisper-small", revision=revision, cache_dir=str(ROOT / "model-cache"))
        model = WhisperModel(model_path, device="cuda", compute_type="int8_float16")
        pin.write_text(revision)
        STT_MODEL, STT_REVISION = model, revision


def process_stt(job_id: str) -> None:
    try:
        with LOCK:
            job = read_job(job_id)
            if job["status"] == "cancelled":
                return
            job.update(status="running", runtime_id=RUNTIME_ID, updated_at=time.time())
            save_job(job)
        segments, info = STT_MODEL.transcribe(str(ROOT / "jobs" / f"{job_id}.input.wav"),
            language=job["input"]["language"], beam_size=5, vad_filter=True, word_timestamps=True)
        result_segments = []
        for segment in segments:
            with LOCK:
                if read_job(job_id)["status"] == "cancel_requested":
                    job.update(status="cancelled", updated_at=time.time())
                    save_job(job)
                    return
            result_segments.append({"start": segment.start, "end": segment.end, "text": segment.text,
                "words": [{"start": w.start, "end": w.end, "word": w.word} for w in (segment.words or [])]})
        data = json.dumps({"language": info.language, "segments": result_segments}, ensure_ascii=False).encode()
        with LOCK:
            if read_job(job_id)["status"] == "cancel_requested":
                job.update(status="cancelled", updated_at=time.time())
            else:
                path = ROOT / "jobs" / f"{job_id}.transcript.json"
                temp = path.with_suffix(".part")
                temp.write_bytes(data)
                temp.replace(path)
                job.update(status="succeeded", checksum=hashlib.sha256(data).hexdigest(), size_bytes=len(data), updated_at=time.time())
            save_job(job)
    except Exception:
        with LOCK:
            job = read_job(job_id)
            job.update(status="failed", error="Transcription failed; inspect the Colab runtime.", updated_at=time.time())
            save_job(job)
    finally:
        with LOCK:
            ACTIVE.discard(job_id)


@app.post("/v1/stt/jobs", status_code=202)
async def submit_stt(file: UploadFile = File(...), language: Literal["en", "vi"] = Form(...),
                     model_revision: str = Form(...), idempotency_key: str = Header(alias="Idempotency-Key"), retry: bool = False):
    import io
    import wave

    if STT_MODEL is None:
        raise HTTPException(503, "Enable STT in the Colab notebook first.")
    if model_revision != STT_REVISION:
        raise HTTPException(409, "STT revision changed; reconnect the worker.")
    raw = await file.read(32 * 1024 * 1024 + 1)
    if len(raw) > 32 * 1024 * 1024:
        raise HTTPException(413, "WAV limit: 32 MiB")
    try:
        with wave.open(io.BytesIO(raw), "rb") as audio:
            if audio.getsampwidth() != 2 or audio.getnchannels() not in (1, 2) or not 0 < audio.getnframes() / audio.getframerate() <= 360:
                raise ValueError("Unsupported WAV")
    except (ValueError, EOFError, wave.Error) as exc:
        raise HTTPException(422, "Use PCM16 WAV, mono/stereo, at most 360 seconds.") from exc
    payload = {"type": "stt", "audio_sha256": hashlib.sha256(raw).hexdigest(), "language": language, "model_revision": model_revision}
    job_id = digest(payload)
    if job_id != idempotency_key:
        raise HTTPException(409, "Idempotency key mismatch")
    with LOCK:
        if CONTROL_BUSY or STT_MODEL is None or model_revision != STT_REVISION:
            raise HTTPException(409, "Worker is training or changing models")
        path = manifest_path(job_id)
        job = read_job(job_id) if path.exists() else {"job_id": job_id, "type": "stt", "input": payload, "created_at": time.time(), "status": "queued"}
        if job_id in ACTIVE or job["status"] == "succeeded" or (job["status"] in ("failed", "cancelled") and not retry):
            return {k: v for k, v in job.items() if k != "input"}
        if len(ACTIVE) >= 16:
            raise HTTPException(429, "Worker queue is full")
        path.parent.mkdir(parents=True, exist_ok=True)
        (ROOT / "jobs" / f"{job_id}.input.wav").write_bytes(raw)
        job.update(status="queued", runtime_id=RUNTIME_ID, updated_at=time.time())
        job.pop("error", None)
        save_job(job)
        ACTIVE.add(job_id)
        EXECUTOR.submit(process_stt, job_id)
        return {k: v for k, v in job.items() if k != "input"}
