"""Durable script checkpoints backed by one WSL CAO/tmux task per request."""
import json
import os
from pathlib import Path
import re
import subprocess
import threading
from fastapi import HTTPException
from sqlalchemy import update
from sqlmodel import Session, select
from server.db.models.script_revision import ScriptRevision
from server.text.schemas import SCHEMAS, Script

LOCK = threading.RLock()
CONFIG = {"distro": "Ubuntu", "confirmed": False, "ready": False, "timeout_seconds": 1200,
          "message": "Cấu hình CAO/tmux trong Kết nối trước khi tạo kịch bản."}
ACTIVE = ("pending", "running", "waiting_user", "interrupted")


def public():
    with LOCK:
        return dict(CONFIG)


def call(action, distro, body=None):
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}", distro) or distro.startswith("docker-"):
        raise HTTPException(422, "Chọn distro Ubuntu/WSL dùng riêng, không dùng docker-desktop.")
    script = Path(__file__).resolve().parents[2] / "codex_tmux/bridge.py"
    if os.name == "nt":
        linux_path = "/mnt/" + script.drive[0].lower() + script.as_posix()[2:]
        command = ["wsl.exe", "--distribution", distro, "--exec", "python3", linux_path, action]
    else:
        command = ["python3", str(script), action]
    try:
        result = subprocess.run(command, input=json.dumps(body or {}, ensure_ascii=False), capture_output=True,
                                encoding="utf-8", errors="replace", timeout=55,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        data = json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        raise HTTPException(503, "Chưa liên lạc được WSL/CAO. Kiểm tra distro, chạy setup và bật CAO; không tự gửi lại prompt.") from exc
    if result.returncode or data.get("error"):
        raise HTTPException(503, data.get("error", "Bridge WSL chưa sẵn sàng."))
    return data


def configure(distro, confirmed, timeout_seconds):
    with LOCK:
        CONFIG.update(ready=False, confirmed=False, message="Chưa kiểm tra xong kết nối CAO/tmux.")
    if not confirmed:
        with LOCK:
            CONFIG.update(distro=distro, confirmed=False, ready=False, timeout_seconds=timeout_seconds,
                          message="Chưa xác nhận điều kiện sử dụng subscription/credits.")
        return public()
    checked = call("check", distro)
    with LOCK:
        CONFIG.update(distro=distro, confirmed=True, ready=bool(checked.get("ready")), timeout_seconds=timeout_seconds,
                      message="Đã kiểm tra ChatGPT login và CAO. tmux không thay đổi cơ chế credits.")
    return public()


def begin(session: Session, body, parent, prompt):
    with LOCK:
        if not CONFIG["ready"] or not CONFIG["confirmed"]:
            raise HTTPException(409, CONFIG["message"])
        unfinished = session.exec(select(ScriptRevision).where(ScriptRevision.provider == "codex_cli",
                                 ScriptRevision.status.in_(ACTIVE))).first()
        if unfinished:
            raise HTTPException(409, f"Đồng bộ/dừng tác vụ Codex #{unfinished.id} trước khi tạo lượt mới.")
        usage = {"requested_model": body.model, "transport": "cao-tmux", "distro": CONFIG["distro"],
                 "session_name": "cao-aiflow-" + str(body.request_id), "timeout_seconds": CONFIG["timeout_seconds"]}
        row = ScriptRevision(request_id=str(body.request_id), parent_id=parent.id, title=parent.title,
                             stage=body.stage, status="running", provider="codex_cli", model=body.model,
                             usage_json=json.dumps(usage))
        session.add(row); session.commit(); session.refresh(row)
        try:
            record = call("start", usage["distro"], {"request_id": row.request_id, "prompt": prompt,
                          "schema": SCHEMAS[body.stage].model_json_schema(), "model": body.model,
                          "timeout_seconds": usage["timeout_seconds"]})
            apply_record(session, row, record)
        except HTTPException as exc:
            # A lost response can still have launched Codex. Keep task recoverable and block replay.
            row.status = "interrupted"
            row.error = str(exc.detail)
            session.add(row); session.commit(); session.refresh(row)
        return row


def apply_record(session, row, record):
    state = record["status"]
    usage = json.loads(row.usage_json) or {}
    usage.update({key: record[key] for key in ("session_name", "terminal_id", "deadline", "attach_command") if key in record})
    result = {"usage_json": json.dumps(usage), "status": "running" if state == "starting" else state,
              "error": record.get("message", "")}
    if state == "succeeded":
        try:
            content = SCHEMAS[row.stage].model_validate(record["content"])
            if row.stage == "review":
                parent = session.get(ScriptRevision, row.parent_id)
                count = len(Script.model_validate_json(parent.content_json).scenes)
                if len(content.findings) != 7 or any(n < 1 or n > count for f in content.findings for n in f.scene_numbers):
                    raise ValueError("Review không khớp cảnh/rubric.")
            result.update(content_json=content.model_dump_json(), title=getattr(content, "title", row.title), error="")
        except (ValueError, KeyError, TypeError):
            result.update(status="failed", error="Kết quả Codex không đúng schema/rubric. Giữ file trên WSL để sửa hoặc nhập tay; không tự gọi lại.")
    session.execute(update(ScriptRevision).where(ScriptRevision.id == row.id, ScriptRevision.status.in_(ACTIVE)).values(**result))
    session.commit(); session.refresh(row)


def sync(session, row, cancel=False):
    if row.provider != "codex_cli":
        raise HTTPException(422, "Đây không phải tác vụ Codex/tmux.")
    if row.status not in ACTIVE:
        return row
    with LOCK:
        usage = json.loads(row.usage_json) or {}
        if usage.get("transport") != "cao-tmux":
            raise HTTPException(409, "Tác vụ cũ không có receipt tmux; dùng đánh dấu gián đoạn cũ.")
        record = call("cancel" if cancel else "poll", usage["distro"], {"request_id": row.request_id})
        if cancel and record["status"] == "interrupted":
            # No WSL receipt means no start call crossed the bridge's durable boundary.
            record = {"status": "cancelled", "message": "Đã đóng tác vụ chưa có receipt WSL."}
        apply_record(session, row, record)
    return row
