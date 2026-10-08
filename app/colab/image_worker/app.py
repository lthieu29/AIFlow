"""Small authenticated job API; model execution is confined to one GPU thread."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import secrets
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_REFERENCE_BYTES = 5 * 1024 * 1024
MAX_RESULT_BYTES = 10 * 1024 * 1024
MAX_BODY_BYTES = 22 * 1024 * 1024


def digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


class Reference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    mime: Literal["image/png", "image/jpeg"]
    data: str = Field(min_length=1, max_length=((MAX_REFERENCE_BYTES + 2) // 3) * 4)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_image(self):
        decode_reference(self)
        return self


def decode_reference(reference: Reference) -> Image.Image:
    try:
        raw = base64.b64decode(reference.data, validate=True)
        if len(raw) > MAX_REFERENCE_BYTES or hashlib.sha256(raw).hexdigest() != reference.sha256:
            raise ValueError("Reference size or sha256 mismatch")
        with Image.open(io.BytesIO(raw)) as image:
            expected = {"image/png": "PNG", "image/jpeg": "JPEG"}[reference.mime]
            if image.format != expected or getattr(image, "n_frames", 1) != 1:
                raise ValueError("Reference MIME or frame count mismatch")
            width, height = image.size
            if min(width, height) < 32 or max(width, height) > 4096 or width * height > 16_000_000:
                raise ValueError("Reference dimensions are outside limits")
            image.load()
            oriented = ImageOps.exif_transpose(image)
            if "A" in oriented.getbands() or "transparency" in oriented.info:
                rgba = oriented.convert("RGBA")
                background = Image.new("RGBA", rgba.size, "white")
                return Image.alpha_composite(background, rgba).convert("RGB")
            return oriented.convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Reference is not a valid supported image") from exc


class ImageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: uuid.UUID
    generation_mode: Literal["reference", "text"] = "reference"
    subject_type: Literal["human", "pet"]
    prompt: str = Field(min_length=1, max_length=2000)
    negative_prompt: str = Field(default="", max_length=1500)
    width: int = Field(default=1024, ge=256, le=1536, strict=True)
    height: int = Field(default=1024, ge=256, le=1536, strict=True)
    seed: int = Field(default=0, ge=0, le=4294967295, strict=True)
    steps: int = Field(default=30, ge=10, le=50, strict=True)
    guidance_scale: float = Field(default=4.5, ge=1.0, le=12.0, allow_inf_nan=False)
    reference_strength: float = Field(default=0.45, ge=0.0, le=1.0, allow_inf_nan=False)
    references: list[Reference] = Field(min_length=0, max_length=3)

    @model_validator(mode="after")
    def validate_shape(self):
        if self.generation_mode == "text":
            if self.subject_type != "human" or self.references:
                raise ValueError("Text mode requires a human subject and no reference images")
        elif not self.references:
            raise ValueError("Reference mode requires 1 to 3 reference images")
        if not self.prompt.strip():
            raise ValueError("Prompt must not be blank")
        if self.width % 64 or self.height % 64 or self.width * self.height > 1_500_000:
            raise ValueError("Output dimensions must be multiples of 64 and at most 1.5M pixels")
        return self


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".partial")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, separators=(",", ":"))
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def create_app(*, token: str, root: Path, engine, max_pending: int = 3, request_model=ImageRequest) -> FastAPI:
    if len(token.encode()) < 32 or not token.isascii() or any(char.isspace() for char in token):
        raise ValueError("Session token must contain at least 32 ASCII bytes without whitespace")
    if max_pending < 1 or max_pending > 16:
        raise ValueError("max_pending must be 1..16")
    root = Path(root).resolve()
    jobs_dir = root / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    identity_file = root / "worker.json"
    if not identity_file.exists():
        atomic_json(identity_file, {"worker_id": str(uuid.uuid4())})
    worker_id = str(uuid.UUID(json.loads(identity_file.read_text(encoding="utf-8"))["worker_id"]))
    lock = threading.RLock()
    pending: set[str] = set()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="image-gpu")
    for path in jobs_dir.glob("*.json"):
        job = json.loads(path.read_text(encoding="utf-8"))
        if job["status"] in ("queued", "running"):
            job.update(status="failed", error={"code": "interrupted", "message": "Runtime restarted; submit a new request ID to retry"}, updated_at=time.time())
            atomic_json(path, job)

    def authorize(authorization: str = Header(default="")):
        if not secrets.compare_digest(authorization.encode(), f"Bearer {token}".encode()):
            raise HTTPException(401, "Invalid session token")

    app = FastAPI(title="AIFlow Image Worker", docs_url=None, redoc_url=None, openapi_url=None,
                  dependencies=[Depends(authorize)])
    app.state.executor = executor

    # Bound the body before JSON/Pydantic allocate decoded images. No access logs or request echoes.
    @app.middleware("http")
    async def bound_body(request, call_next):
        if not secrets.compare_digest(request.headers.get("authorization", "").encode(), f"Bearer {token}".encode()):
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Invalid session token"}, status_code=401)
        if request.method == "POST":
            length = request.headers.get("content-length")
            if length is not None and (not length.isdecimal() or int(length) > MAX_BODY_BYTES):
                from fastapi.responses import JSONResponse
                return JSONResponse({"detail": "Request body exceeds limit"}, status_code=413)
            size = 0
            chunks = []
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_BODY_BYTES:
                    from fastapi.responses import JSONResponse
                    return JSONResponse({"detail": "Request body exceeds limit"}, status_code=413)
                chunks.append(chunk)
            request._body = b"".join(chunks)
        return await call_next(request)

    # FastAPI's default validation errors echo input (including base64); suppress those values.
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request, error):
        return JSONResponse({"detail": [{"loc": list(item["loc"]), "type": item["type"], "msg": item["msg"]}
                                       for item in error.errors()]}, status_code=422)

    def job_path(job_id: str) -> Path:
        try:
            canonical = str(uuid.UUID(job_id))
        except ValueError:
            raise HTTPException(404, "Unknown job") from None
        if canonical != job_id:
            raise HTTPException(404, "Unknown job")
        return jobs_dir / f"{canonical}.json"

    def read_job(job_id: str) -> dict:
        path = job_path(job_id)
        if not path.is_file():
            raise HTTPException(404, "Unknown job")
        return json.loads(path.read_text(encoding="utf-8"))

    def process(request: ImageRequest, job_id: str):
        try:
            with lock:
                job = read_job(job_id)
                job.update(status="running", updated_at=time.time())
                atomic_json(job_path(job_id), job)
            output, metadata = engine.generate(request)
            if output.size != (request.width, request.height):
                raise ValueError("Engine returned incorrect dimensions")
            buffer = io.BytesIO()
            output.convert("RGB").save(buffer, format="PNG")
            raw = buffer.getvalue()
            if len(raw) > MAX_RESULT_BYTES:
                raise ValueError("Result exceeds size limit")
            result_path = jobs_dir / f"{job_id}.png"
            temporary = result_path.with_suffix(".partial")
            with temporary.open("wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(result_path)
            with lock:
                job.update(status="succeeded", updated_at=time.time(), result={"mime": "image/png",
                           "sha256": hashlib.sha256(raw).hexdigest(), "width": request.width,
                           "height": request.height, "metadata": metadata})
                atomic_json(job_path(job_id), job)
        except Exception as error:
            # Exception text may contain remote URLs or token values; retain only a fixed diagnostic.
            error_class = type(error).__name__
            code = ("prompt_too_long" if error_class == "PromptTooLongError" else
                    "gpu_out_of_memory" if error_class == "OutOfMemoryError" else
                    "pipeline_incompatible" if isinstance(error, (TypeError, AttributeError)) else "generation_failed")
            message = ("Prompt or negative prompt exceeds the SDXL token limit; shorten it before a new request"
                       if code == "prompt_too_long" else "Image generation failed")
            print(f"Image generation failed: class={error_class}, stage=generate", file=sys.stderr)
            with lock:
                job = read_job(job_id)
                job.update(status="failed", error={"code": code, "message": message}, updated_at=time.time())
                atomic_json(job_path(job_id), job)
        finally:
            with lock:
                pending.discard(job_id)

    @app.get("/v1/health")
    def health():
        ready = bool(engine.ready)
        return {"api_version": "1", "capabilities": getattr(engine, "capabilities", ["image", "reference_image", "text_to_image"]), "persistent_jobs": True,
                "ready": ready, "status": "ready" if ready else "loading", "worker_id": worker_id,
                "model_revision": engine.model_revision, "max_pending": max_pending}

    def submit(request: ImageRequest):
        if not engine.ready:
            raise HTTPException(503, "Image model is not ready")
        job_id = str(request.request_id)
        input_sha256 = digest(request.model_dump(mode="json"))
        with lock:
            path = job_path(job_id)
            if path.exists():
                job = read_job(job_id)
                if not secrets.compare_digest(job["input_sha256"], input_sha256):
                    raise HTTPException(409, "Request ID already has different immutable input")
                return job
            if len(pending) >= max_pending:
                raise HTTPException(429, "Worker queue is full")
            job = {"job_id": job_id, "request_id": job_id, "status": "queued", "input_sha256": input_sha256,
                   "worker_id": worker_id, "created_at": time.time(), "updated_at": time.time()}
            atomic_json(path, job)
            pending.add(job_id)
            try:
                executor.submit(process, request, job_id)
            except RuntimeError:
                pending.discard(job_id)
                job.update(status="failed", error={"code": "worker_stopped", "message": "Worker is stopping"})
                atomic_json(path, job)
                raise HTTPException(503, "Worker is stopping") from None
            return job

    # The dedicated VTON entrypoint supplies its own strict schema; legacy inputs/digests stay unchanged.
    submit.__annotations__["request"] = request_model
    app.post("/v1/images/jobs", status_code=202)(submit)

    @app.get("/v1/images/jobs/{job_id}")
    def get_job(job_id: str):
        with lock:
            job = read_job(job_id)
            if job["status"] == "succeeded":
                raw = (jobs_dir / f"{job_id}.png").read_bytes()
                if len(raw) > MAX_RESULT_BYTES or hashlib.sha256(raw).hexdigest() != job["result"]["sha256"]:
                    raise HTTPException(500, "Stored image failed integrity verification")
                job["result"]["data"] = base64.b64encode(raw).decode("ascii")
            return job

    return app
