"""Local authenticated bridge to the user's Colab training worker."""
import hashlib
import io
import json
import re
import threading
import uuid
import wave
import zipfile
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, SecretStr

from server.api.routes.audio import local_client
from server.api.routes.voice_training import EXTENSIONS, SelectionInput, selected_bundle
from server.audio.remote import AudioUnavailable, validate_url
from server.audio.youtube_source import canonical_youtube_url

router = APIRouter(prefix="/api/training-control", dependencies=[Depends(local_client)])
CONNECTION = {"url": "", "token": ""}
LOCK = threading.RLock()

class Connect(BaseModel):
    url: str
    token: SecretStr

def remote(path, method="GET", body=None, *, endpoint=None, token=None, binary=False, upload=None, upload_fields=None):
    with LOCK:
        endpoint = endpoint or CONNECTION["url"]
        token = token or CONNECTION["token"]
    if not endpoint or not token:
        raise HTTPException(409, "Bật Colab training và nhập URL/token.")
    try:
        with httpx.Client(timeout=60 if upload is not None else 30, trust_env=False, follow_redirects=False) as client:
            kwargs = {"files": {"file": ("source.wav", upload, "application/octet-stream")}, "data": upload_fields or {}} if upload is not None else {"json": body}
            with client.stream(method, endpoint + "/v1/training/" + path,
                               headers={"Authorization": f"Bearer {token}"}, **kwargs) as response:
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > 32 * 1024**2:
                        raise HTTPException(413, "Phản hồi Colab quá lớn.")
                if response.status_code >= 400:
                    try:
                        detail = json.loads(data).get("detail")
                    except (ValueError, AttributeError):
                        detail = None
                    raise HTTPException(response.status_code, detail if isinstance(detail, str) else "Colab từ chối yêu cầu. Kiểm tra kết nối/trạng thái.")
                if binary:
                    return Response(bytes(data), media_type="audio/wav", headers={"Cache-Control": "no-store"})
                return json.loads(data)
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, "Mất kết nối Colab. Dữ liệu/checkpoint giữ trên Drive; kết nối lại để xem trạng thái.") from exc

@router.put("/connection")
def connect(body: Connect):
    token = body.token.get_secret_value()
    if not 32 <= len(token) <= 512 or any(c.isspace() for c in token):
        raise HTTPException(422, "Token phiên không hợp lệ.")
    try:
        url = validate_url(body.url)
    except AudioUnavailable as exc:
        raise HTTPException(422, exc.message) from exc
    health = remote("health", endpoint=url, token=token)
    if health.get("training_version") != "2":
        raise HTTPException(422, "Cần notebook điều khiển huấn luyện phiên bản 2.")
    with LOCK:
        CONNECTION.update(url=url, token=token)
    return health

@router.get("/connection")
def state():
    with LOCK:
        return {"configured": bool(CONNECTION["token"]), "url": CONNECTION["url"]}

@router.delete("/connection")
def disconnect():
    with LOCK:
        CONNECTION.update(url="", token="")
    return {"disconnected": True}

@router.post("/selections")
def send_selection(body: SelectionInput):
    bundle = selected_bundle(body)
    with zipfile.ZipFile(io.BytesIO(bundle.body)) as archive:
        selection = json.loads(archive.read("selection.json"))
    return remote("selections", "POST", selection)

@router.post("/local-selection")
async def local_selection(
    request_id: uuid.UUID = Form(...), voice_name: str = Form(...), language: str = Form("vi"),
    same_speaker_confirmed: bool = Form(False), files: list[UploadFile] = File(...),
):
    """Transfer explicitly chosen WAVs; no server-side filesystem scan or model execution."""
    from starlette.concurrency import run_in_threadpool
    name = voice_name.strip()
    if not same_speaker_confirmed or not name or len(name) > 80 or re.search(r"[\x00-\x1f\x7f]", name):
        raise HTTPException(422, "Nhập tên giọng và xác nhận dữ liệu của cùng một người nói.")
    if language not in ("vi", "en") or not 1 <= len(files) <= 5000:
        raise HTTPException(422, "Ngôn ngữ hoặc số WAV không hợp lệ (1–5000 file).")
    manifest_files, total, seen = [], 0, set()
    for file in files:
        filename = file.filename or ""
        if Path(filename).name != filename or "\\" in filename or Path(filename).suffix.lower() != ".wav" or filename in seen:
            raise HTTPException(422, "Chỉ chọn WAV có tên riêng, không trùng và không chứa đường dẫn.")
        seen.add(filename)
        checksum, size = hashlib.sha256(), 0
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            total += len(chunk)
            if size > 32 * 1024**2 or total > 512 * 1024**2:
                raise HTTPException(413, "Mỗi WAV tối đa 32 MiB, bộ local tối đa 512 MiB.")
            checksum.update(chunk)
        await file.seek(0)
        try:
            with wave.open(file.file, "rb") as audio:
                if audio.getnframes() <= 0:
                    raise wave.Error("Empty WAV")
        except (wave.Error, EOFError) as exc:
            raise HTTPException(422, "Có file WAV không hợp lệ hoặc không có âm thanh.") from exc
        await file.seek(0)
        manifest_files.append({"id": hashlib.sha256(filename.encode()).hexdigest(), "key": filename,
                               "size": size, "sha256": checksum.hexdigest()})
    selection = {"schema_version": 1, "mode": "finetune", "source_type": "local", "job_id": request_id.hex,
                 "voice_name": name, "language": language, "same_speaker_confirmed": True,
                 "files": sorted(manifest_files, key=lambda item: item["key"])}
    with LOCK:
        endpoint, token = CONNECTION["url"], CONNECTION["token"]
    if not endpoint or not token:
        raise HTTPException(409, "Kết nối Colab training trước khi gửi WAV local.")
    health = await run_in_threadpool(remote, "health", endpoint=endpoint, token=token)
    if not health.get("local_dataset_upload"):
        raise HTTPException(409, "Cập nhật gói worker Colab để nhận dataset local.")
    await run_in_threadpool(remote, "selections", "POST", selection, endpoint=endpoint, token=token)
    for file, item in zip(files, manifest_files):
        result = await run_in_threadpool(remote, f"jobs/{request_id.hex}/sources/{item['id']}", "POST",
                                        endpoint=endpoint, token=token, upload=file.file)
        if not result.get("stored") or result.get("checksum") != item["sha256"]:
            raise HTTPException(502, "Colab chưa xác nhận checksum. Gửi lại cùng lựa chọn để tiếp tục.")
    return {"job_id": request_id.hex, "uploaded_files": len(files), "uploaded_bytes": total}


class LocalMediaFile(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0, le=2 * 1024**3)
    last_modified: int = Field(ge=0)


class YouTubeSelection(BaseModel):
    request_id: uuid.UUID
    voice_name: str = Field(min_length=1, max_length=80)
    language: str = "vi"
    same_speaker_confirmed: bool = False
    url: str = Field(min_length=1, max_length=2000)


@router.post("/youtube")
def begin_youtube(body: YouTubeSelection):
    name = body.voice_name.strip()
    if (not body.same_speaker_confirmed or not name or re.search(r"[\x00-\x1f\x7f]", name)
            or body.language not in ("vi", "en")):
        raise HTTPException(422, "Nhập tên/ngôn ngữ giọng và xác nhận cùng một người nói.")
    try:
        url = canonical_youtube_url(body.url)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    with LOCK:
        endpoint, token = CONNECTION["url"], CONNECTION["token"]
    health = remote("health", endpoint=endpoint, token=token)
    if health.get("youtube_source") != "single-video-v1":
        raise HTTPException(409, "Cập nhật gói worker/notebook Colab để tải audio YouTube.")
    selection = {"schema_version": 1, "mode": "finetune", "source_type": "youtube", "source_url": url,
                 "job_id": body.request_id.hex, "voice_name": name, "language": body.language,
                 "same_speaker_confirmed": True,
                 "files": [{"id": hashlib.sha256(url.encode()).hexdigest(), "key": url, "size": 0}]}
    remote("selections", "POST", selection, endpoint=endpoint, token=token)
    return {"job_id": body.request_id.hex, "source_url": url}


class LocalMediaSelection(BaseModel):
    request_id: uuid.UUID
    voice_name: str = Field(min_length=1, max_length=80)
    language: str = "vi"
    same_speaker_confirmed: bool = False
    files: list[LocalMediaFile] = Field(min_length=1, max_length=5000)


@router.post("/local-media")
def begin_local_media(body: LocalMediaSelection):
    name = body.voice_name.strip()
    if (not body.same_speaker_confirmed or not name or re.search(r"[\x00-\x1f\x7f]", name)
            or body.language not in ("vi", "en")):
        raise HTTPException(422, "Nhập tên/ngôn ngữ giọng và xác nhận cùng một người nói.")
    seen, items = set(), []
    for file in body.files:
        if (Path(file.name).name != file.name or "\\" in file.name or file.name in seen
                or re.search(r"[\x00-\x1f\x7f]", file.name) or Path(file.name).suffix.lower() not in EXTENSIONS):
            raise HTTPException(422, "Tên media phải riêng biệt, không chứa đường dẫn; chỉ dùng định dạng được hỗ trợ.")
        seen.add(file.name)
        items.append({"id": hashlib.sha256(file.name.encode()).hexdigest(), "key": file.name,
                      "size": file.size, "last_modified": file.last_modified})
    if sum(file.size for file in body.files) > 20 * 1024**3:
        raise HTTPException(413, "Lựa chọn tối đa 20 GiB. Chia thành các lượt upload riêng.")
    with LOCK:
        endpoint, token = CONNECTION["url"], CONNECTION["token"]
    health = remote("health", endpoint=endpoint, token=token)
    if health.get("local_media_upload") != "chunks-v1":
        raise HTTPException(409, "Cập nhật gói worker/notebook Colab để upload media theo từng phần.")
    selection = {"schema_version": 1, "mode": "finetune", "source_type": "local", "upload_protocol": "chunks-v1",
                 "job_id": body.request_id.hex, "voice_name": name, "language": body.language,
                 "same_speaker_confirmed": True, "files": sorted(items, key=lambda item: item["key"])}
    remote("selections", "POST", selection, endpoint=endpoint, token=token)
    return {"job_id": body.request_id.hex, "files": items, "chunk_bytes": 8 * 1024**2}


@router.get("/local-media/{job_id}/sources/{file_id}")
def local_media_status(job_id: str, file_id: str):
    if not re.fullmatch(r"[a-f0-9]{32}", job_id) or not re.fullmatch(r"[a-f0-9]{64}", file_id):
        raise HTTPException(422, "ID lựa chọn/file không hợp lệ.")
    return remote(f"jobs/{job_id}/sources/{file_id}/status")


@router.post("/local-media/{job_id}/sources/{file_id}")
async def local_media_chunk(job_id: str, file_id: str, offset: int = Form(...), file: UploadFile = File(...)):
    if offset < 0 or not re.fullmatch(r"[a-f0-9]{32}", job_id) or not re.fullmatch(r"[a-f0-9]{64}", file_id):
        raise HTTPException(422, "Offset/ID lựa chọn/file không hợp lệ.")
    content = await file.read(8 * 1024**2 + 1)
    if not 0 < len(content) <= 8 * 1024**2:
        raise HTTPException(413, "Mỗi phần upload phải có 1 byte–8 MiB.")
    from starlette.concurrency import run_in_threadpool
    return await run_in_threadpool(remote, f"jobs/{job_id}/sources/{file_id}/chunks", "POST",
                                  upload=io.BytesIO(content), upload_fields={"offset": str(offset), "checksum": hashlib.sha256(content).hexdigest()})

@router.get("/notebook")
def notebook():
    return FileResponse(Path(__file__).resolve().parents[3] / "colab/control_voice_training.ipynb", filename="control_voice_training.ipynb")

@router.post("/use-audio")
def use_audio():
    from server.audio.remote import connection
    from server.config import load_settings
    with LOCK:
        url, token = CONNECTION["url"], CONNECTION["token"]
    try:
        checked = connection.check(url, token)
        connection.save(checked, token, load_settings().data_dir)
        return connection.public(load_settings().data_dir)
    except AudioUnavailable as exc:
        raise HTTPException(409, exc.message) from exc

@router.get("/worker-bundle")
def worker_bundle():
    base = Path(__file__).resolve().parents[3] / "colab"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ("voice_training.py", "train_resumable.py", "training_control.py"):
            archive.write(base / name, name)
        archive.write(base.parent / "server/audio/youtube_source.py", "youtube_source.py")
        archive.write(base / "audio_worker/app.py", "audio_worker.py")
    return Response(buffer.getvalue(), media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="aiflow-training-worker.zip"'})

@router.get("/remote/{path:path}")
@router.post("/remote/{path:path}")
@router.put("/remote/{path:path}")
async def proxy(path: str, request: Request):
    job = r"[a-f0-9]{32}"
    allowed = {"GET": rf"(?:health|jobs|jobs/{job}|jobs/{job}/review|jobs/{job}/clips/[a-zA-Z0-9_.-]+|jobs/{job}/runs/{job}/sample)",
               "POST": rf"jobs/{job}/(?:actions|cancel|approve-dataset|runs/{job}/approve)",
               "PUT": rf"jobs/{job}/review(?:/bulk)?"}
    if not re.fullmatch(allowed[request.method], path):
        raise HTTPException(404, "Không có thao tác này.")
    body = None
    if request.method != "GET":
        raw = await request.body()
        limit = 8 * 1024**2 if path.endswith("/review/bulk") else 64000
        if len(raw) > limit:
            raise HTTPException(413, "Dữ liệu quá lớn.")
        try:
            body = json.loads(raw) if raw else {}
        except ValueError as exc:
            raise HTTPException(422, "Dữ liệu JSON không hợp lệ.") from exc
        if not isinstance(body, dict):
            raise HTTPException(422, "Dữ liệu phải là JSON object.")
    from starlette.concurrency import run_in_threadpool
    return await run_in_threadpool(remote, path, request.method, body, binary="/clips/" in path or path.endswith("/sample"))
