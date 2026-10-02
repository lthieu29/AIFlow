"""R2 inventory only. Media is downloaded in Colab after explicit selection."""

import hashlib
import io
import json
import re
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field, SecretStr

from server.api.routes.audio import local_client

router = APIRouter(prefix="/api/voice-training", tags=["voice-training"], dependencies=[Depends(local_client)])
EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".opus", ".mp4", ".mov", ".mkv", ".webm"}
SCANS: dict[str, dict] = {}
LOCK = threading.Lock()
TTL = 3600


class SourceInput(BaseModel):
    account_id: str = Field(pattern=r"^[a-fA-F0-9]{32}$")
    jurisdiction: Literal["default", "eu", "fedramp"] = "default"
    bucket: str = Field(min_length=3, max_length=63, pattern=r"^[a-z0-9][a-z0-9.-]*[a-z0-9]$")
    prefix: str = Field(default="", max_length=1024)
    access_key_id: SecretStr
    secret_access_key: SecretStr


class SelectionInput(BaseModel):
    scan_id: str
    file_ids: list[str] = Field(min_length=1, max_length=5000)
    voice_name: str = Field(min_length=1, max_length=80)
    language: Literal["vi", "en"] = "vi"
    same_speaker_confirmed: bool = False


@router.post("/scan")
def scan_r2(body: SourceInput):
    try:
        import boto3
        from botocore.config import Config
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError as exc:
        raise HTTPException(503, "Thiếu boto3. Cài lại dependencies của app rồi thử lại.") from exc
    if not body.access_key_id.get_secret_value().strip() or not body.secret_access_key.get_secret_value().strip():
        raise HTTPException(422, "Nhập R2 Access Key ID và Secret Access Key.")
    jurisdiction = "" if body.jurisdiction == "default" else f".{body.jurisdiction}"
    endpoint = f"https://{body.account_id}{jurisdiction}.r2.cloudflarestorage.com"
    client = boto3.client("s3", endpoint_url=endpoint, region_name="auto",
                          aws_access_key_id=body.access_key_id.get_secret_value(),
                          aws_secret_access_key=body.secret_access_key.get_secret_value(),
                          config=Config(signature_version="s3v4", connect_timeout=10, read_timeout=30,
                                        retries={"max_attempts": 2}, s3={"addressing_style": "path"}))
    files = []
    examined = 0
    try:
        for page in client.get_paginator("list_objects_v2").paginate(Bucket=body.bucket, Prefix=body.prefix):
            for item in page.get("Contents", []):
                examined += 1
                if examined > 100000:
                    raise HTTPException(422, "Bucket vượt 100.000 object. Nhập prefix hẹp hơn; chưa trả danh sách dở dang.")
                key = item["Key"]
                if Path(key).suffix.lower() not in EXTENSIONS or item["Size"] == 0:
                    continue
                files.append({"id": hashlib.sha256(key.encode()).hexdigest(), "key": key,
                              "size": item["Size"], "etag": item["ETag"],
                              "modified": item["LastModified"].isoformat(),
                              "group": key.rpartition("/")[0] or "(gốc bucket)"})
                if len(files) > 20000:
                    raise HTTPException(422, "Có hơn 20.000 file media. Nhập prefix hẹp hơn rồi quét lại.")
    except (BotoCoreError, ClientError) as exc:
        # Do not expose SDK diagnostics containing request metadata or credentials.
        raise HTTPException(502, "Không đọc được R2. Kiểm tra account, jurisdiction, bucket và quyền Object Read của token.") from exc
    finally:
        client.close()
    scan_id = uuid.uuid4().hex
    snapshot = {"scan_id": scan_id, "created_at": time.time(), "endpoint": endpoint,
                "bucket": body.bucket, "prefix": body.prefix, "examined": examined,
                "files": sorted(files, key=lambda f: f["key"])}
    with LOCK:
        for key in list(SCANS):
            if time.time() - SCANS[key]["created_at"] > TTL:
                del SCANS[key]
        while len(SCANS) >= 5:
            del SCANS[next(iter(SCANS))]
        SCANS[scan_id] = snapshot
    return {**snapshot, "expires_at": snapshot["created_at"] + TTL, "downloaded_files": 0}


@router.post("/bundle")
def selected_bundle(body: SelectionInput):
    if not body.same_speaker_confirmed:
        raise HTTPException(422, "Xác nhận các file đã chọn chỉ chứa giọng người bạn muốn huấn luyện.")
    name = body.voice_name.strip()
    if not name or re.search(r"[\x00-\x1f\x7f]", name):
        raise HTTPException(422, "Tên giọng không hợp lệ.")
    with LOCK:
        snapshot = SCANS.get(body.scan_id)
    if not snapshot or time.time() - snapshot["created_at"] > TTL:
        raise HTTPException(409, "Danh sách đã hết hạn hoặc server đã khởi động lại. Quét và chọn lại.")
    inventory = {file["id"]: file for file in snapshot["files"]}
    ids = list(dict.fromkeys(body.file_ids))
    if any(file_id not in inventory for file_id in ids):
        raise HTTPException(422, "Có file không nằm trong lần quét này. Quét và chọn lại.")
    selected = [inventory[file_id] for file_id in ids]
    if any(file["size"] > 2 * 1024**3 for file in selected) or sum(f["size"] for f in selected) > 20 * 1024**3:
        raise HTTPException(422, "Mỗi file tối đa 2 GiB, mỗi bộ tối đa 20 GiB. Chọn ít file hơn hoặc chia file trước.")
    manifest = {"schema_version": 1, "mode": "finetune", "job_id": uuid.uuid4().hex,
                "voice_name": name, "language": body.language, "selected_at": time.time(),
                "same_speaker_confirmed": True, "endpoint": snapshot["endpoint"],
                "bucket": snapshot["bucket"], "files": selected}
    colab = Path(__file__).resolve().parents[3] / "colab"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("selection.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for name in ("finetune_r2.ipynb", "voice_training.py", "train_resumable.py", "training_control.py", "control_voice_training.ipynb"):
            archive.write(colab / name, name)
        archive.write(colab / "audio_worker" / "app.py", "audio_worker.py")
    return Response(buffer.getvalue(), media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="aiflow-voice-{manifest["job_id"]}.zip"',
        "Cache-Control": "no-store"})
