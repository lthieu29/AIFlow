"""Local authenticated bridge to the user's Colab training worker."""
import io
import json
import re
import threading
import zipfile
from pathlib import Path
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, SecretStr
from server.api.routes.audio import local_client
from server.api.routes.voice_training import SelectionInput, selected_bundle
from server.audio.remote import validate_url, AudioUnavailable

router = APIRouter(prefix="/api/training-control", dependencies=[Depends(local_client)])
CONNECTION = {"url": "", "token": ""}
LOCK = threading.RLock()

class Connect(BaseModel):
    url: str
    token: SecretStr

def remote(path, method="GET", body=None, *, endpoint=None, token=None, binary=False):
    with LOCK:
        endpoint = endpoint or CONNECTION["url"]
        token = token or CONNECTION["token"]
    if not endpoint or not token:
        raise HTTPException(409, "Bật Colab training và nhập URL/token.")
    try:
        with httpx.Client(timeout=30, trust_env=False, follow_redirects=False) as client:
            with client.stream(method, endpoint + "/v1/training/" + path,
                               headers={"Authorization": f"Bearer {token}"}, json=body) as response:
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
        archive.write(base / "audio_worker/app.py", "audio_worker.py")
    return Response(buffer.getvalue(), media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="aiflow-training-worker.zip"'})

@router.api_route("/remote/{path:path}", methods=["GET", "POST", "PUT"])
async def proxy(path: str, request: Request):
    job = r"[a-f0-9]{32}"
    allowed = {"GET": rf"(?:health|jobs|jobs/{job}|jobs/{job}/review|jobs/{job}/clips/[a-zA-Z0-9_.-]+|jobs/{job}/runs/{job}/sample)",
               "POST": rf"jobs/{job}/(?:actions|cancel|approve-dataset|runs/{job}/approve)",
               "PUT": rf"jobs/{job}/review"}
    if not re.fullmatch(allowed[request.method], path):
        raise HTTPException(404, "Không có thao tác này.")
    body = None
    if request.method != "GET":
        raw = await request.body()
        if len(raw) > 64000:
            raise HTTPException(413, "Dữ liệu quá lớn.")
        body = json.loads(raw) if raw else {}
    from starlette.concurrency import run_in_threadpool
    return await run_in_threadpool(remote, path, request.method, body, binary="/clips/" in path or path.endswith("/sample"))
