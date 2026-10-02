"""WSL-only CAO bridge. JSON stdin/stdout; no shell interpolation or API key transport."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, ProxyHandler

ROOT = Path.home() / ".local/share/aiflow-codex"
HERE = Path(__file__).resolve().parent
BASE = "http://127.0.0.1:9891"
FINAL = {"succeeded", "failed", "cancelled", "timed_out"}


def tmux_env():
    return {**os.environ, "TMUX_TMPDIR": str(ROOT / "tmux")}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def job_dir(identifier):
    if not re.fullmatch(r"[a-f0-9-]{36}", identifier):
        raise ValueError("Mã tác vụ không hợp lệ.")
    return ROOT / "jobs" / identifier


def request(path, method="GET", data=None, params=None):
    token = (ROOT / "token").read_text().strip()
    url = BASE + path + ("?" + urlencode(params) if params else "")
    req = Request(url, method=method, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                  data=json.dumps(data).encode() if data is not None else None)
    with build_opener(ProxyHandler({})).open(req, timeout=12) as response:
        content = response.read(2_000_001)
        if len(content) > 2_000_000:
            raise RuntimeError("Phản hồi CAO quá lớn.")
        return json.loads(content)


def clean_env():
    env = dict(os.environ)
    for name in list(env):
        if name.startswith(("OPENAI_", "AZURE_OPENAI_", "CODEX_")):
            env.pop(name)
    installation = ROOT / "installation.json"
    if installation.exists():
        env["PATH"] = str(Path(read(installation)["codex"]).parent) + ":" + env["PATH"]
    return env


def auth():
    config = read(ROOT / "installation.json")
    result = subprocess.run([config["codex"], "-c", 'forced_login_method="chatgpt"', "login", "status"],
                            env=clean_env(), capture_output=True, text=True, timeout=15)
    output = (result.stdout + result.stderr).lower()
    if result.returncode or "chatgpt" not in output or "api key" in output:
        raise RuntimeError("Đăng nhập Codex bằng ChatGPT trong Ubuntu trước (codex login).")
    return config


def check():
    config = auth()
    request("/sessions")  # Authenticated read, no model request.
    return {"ready": True, "auth": "chatgpt", "transport": "cao-tmux", "codex_version": config["version"]}


def terminal(record):
    if record.get("terminal_id"):
        try:
            return request("/terminals/" + record["terminal_id"])
        except HTTPError as exc:
            if exc.code != 404:
                raise
    try:
        entries = request("/sessions/" + record["session_name"])["terminals"]
        return next((item for item in entries if item.get("provider") == "codex"), None)
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def stop(record, status):
    # Delete only the deterministic session owned by this job; never kill the tmux server.
    if record.get("terminal_id"):
        try:
            output = request("/terminals/" + record["terminal_id"] + "/output")
            (job_dir(record["request_id"]) / "terminal.log").write_text(output["output"], encoding="utf-8")
        except Exception:
            pass  # Cleanup must still work when output capture/CAO is unavailable.
    try:
        request("/sessions/" + record["session_name"], "DELETE")
    except Exception:
        # CAO may be offline while tmux/Codex remains alive. Stop only our owned session.
        listing = subprocess.run(["tmux", "list-sessions", "-F", "#{session_name}"], env=tmux_env(), capture_output=True, text=True, timeout=10)
        if listing.returncode and "no server running" not in listing.stderr and "error connecting" not in listing.stderr:
            raise RuntimeError("Chưa xác nhận được tmux đã dừng. Bật lại CAO rồi bấm Dừng.")
        if record["session_name"] in listing.stdout.splitlines():
            subprocess.run(["tmux", "kill-session", "-t", "=" + record["session_name"]], env=tmux_env(), check=True, timeout=10, capture_output=True)
    record["status"] = status


def poll(identifier, cancel=False):
    folder = job_dir(identifier)
    path = folder / "state.json"
    if not path.exists():
        return {"status": "interrupted", "message": "Chưa có receipt WSL. Không tự gửi lại prompt."}
    record = read(path)
    if record["status"] in FINAL:
        return record
    if cancel:
        stop(record, "cancelled")
    elif time.time() > record["deadline"]:
        stop(record, "timed_out")
        record["message"] = "Đã hết thời gian và dừng phiên Codex; không tự gửi lại."
    else:
        current = terminal(record)
        if current is None:
            # A lost create response is never replayed. Leave a short reconciliation window.
            if time.time() - record["created_at"] < 90:
                return record
            stop(record, "failed")
            record["message"] = "Phiên CAO không còn tồn tại. Prompt chưa được tự gửi lại."
        else:
            record["terminal_id"] = current["id"]
            state = current.get("status", "unknown")
            record["status"] = "waiting_user" if state == "waiting_user_answer" else "running"
            record["message"] = "Mở tmux để xử lý yêu cầu đang chờ." if state == "waiting_user_answer" else ""
            result = folder / "work/result.json"
            if state in ("completed", "idle") and result.exists():
                if result.is_symlink() or result.stat().st_size > 1_000_000:
                    raise RuntimeError("File kết quả không hợp lệ.")
                try:
                    content = read(result)
                    if not isinstance(content, dict) or content.get("request_id") != identifier or not isinstance(content.get("content"), dict):
                        raise ValueError("envelope")
                except (ValueError, TypeError):
                    stop(record, "failed")
                    record["message"] = "File kết quả không đúng JSON/mã tác vụ; giữ file để xem và sửa tay."
                    write(path, record)
                    return record
                # Receipt comes from the launcher, outside the model's writable workspace.
                if not (folder / "chatgpt-launch.json").exists():
                    raise RuntimeError("Thiếu receipt xác thực ChatGPT từ launcher.")
                record["content"] = content["content"]
                stop(record, "succeeded")
            elif state == "error":
                stop(record, "failed")
                record["message"] = "Codex báo lỗi/quota hoặc đã thoát. Xem terminal.log trong thư mục tác vụ."
            elif state == "completed":
                record["status"] = "waiting_user"
                record["message"] = "Codex đã trả lời nhưng chưa có result.json. Mở tmux để xem; hệ thống không tự gửi thêm prompt."
    write(path, record)
    return record


def start(body):
    identifier = body["request_id"]
    folder = job_dir(identifier)
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    state = folder / "state.json"
    if state.exists():
        record = read(state)
        if record["input_hash"] != digest:
            raise RuntimeError("Mã tác vụ đã dùng cho đầu vào khác.")
        return record  # No retry of session creation or initial message.
    check()
    for path in (ROOT / "jobs").glob("*/state.json"):
        if read(path)["status"] not in FINAL:
            raise RuntimeError("Còn tác vụ chưa đóng. Đồng bộ/dừng tác vụ đó trước khi tạo lượt mới.")
    model = body["model"]
    if not re.fullmatch(r"[a-zA-Z0-9._-]{1,100}", model):
        raise ValueError("Tên model không hợp lệ.")
    work = folder / "work"
    work.mkdir(parents=True)
    write(work / "input.json", body)
    record = {"request_id": identifier, "status": "starting", "input_hash": digest,
              "session_name": "cao-aiflow-" + identifier, "terminal_id": "",
              "attach_command": "python3 " + shlex.quote(str(HERE / "bridge.py")) + " attach " + identifier,
              "created_at": time.time(), "deadline": time.time() + body["timeout_seconds"],
              "message": "", "model": model}
    write(state, record)
    params = {"provider": "codex", "agent_profile": "aiflow_script", "session_name": record["session_name"],
              "working_directory": str(work), "idempotency_key": identifier}
    if model != "default":
        params["model"] = model
    prompt = ("Read input.json in the current directory. Complete its prompt using its schema. "
              "Write result.json atomically with exactly {\"request_id\":\"" + identifier +
              "\",\"content\":<the requested JSON object>}. Do not edit input.json. "
              "Do not install tools, modify settings, buy credits, or delegate. Stop if quota is exhausted. "
              "When the file is complete, reply DONE and stop.")
    try:
        value = request("/sessions", "POST", {"initial_message": prompt, "env_vars": {
            "PATH": str(ROOT / "bin") + ":" + os.environ["PATH"], "AIFLOW_CODEX_JOB": identifier}}, params)
        record["terminal_id"] = value["id"]
        record["status"] = "running"
    except Exception:
        record["message"] = "Chưa xác nhận được việc tạo phiên; đang đối chiếu mã phiên, không gửi lại prompt."
    write(state, record)
    with (folder / "watch.log").open("a") as log:
        subprocess.Popen([sys.executable, str(HERE / "bridge.py"), "watch", identifier],
                         stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    return record


def install():
    if os.geteuid() == 0:
        raise RuntimeError("Chạy setup bằng user Ubuntu thông thường, không chạy sudo python.")
    codex = shutil.which("codex")
    tmux = shutil.which("tmux")
    server = ROOT / "venv/bin/cao-server"
    if not codex or not tmux or not server.exists() or str(ROOT / "bin") in codex:
        raise RuntimeError("Cần Codex CLI, tmux và CAO venv trước khi cấu hình bridge.")
    ROOT.mkdir(parents=True, exist_ok=True)
    ROOT.chmod(0o700)
    version = subprocess.check_output([codex, "--version"], text=True, timeout=15).strip()
    write(ROOT / "installation.json", {"codex": codex, "version": version})
    token = ROOT / "token"
    if not token.exists():
        token.write_text(secrets.token_urlsafe(48))
    token.chmod(0o600)
    (ROOT / "bin").mkdir(exist_ok=True)
    launcher = ROOT / "bin/codex"
    # No global Codex config/auth is copied or rewritten.
    launcher.write_text('#!/usr/bin/env python3\nimport runpy, sys\nsys.path.insert(0, ' + repr(str(HERE)) + ')\nrunpy.run_path(' + repr(str(HERE / "launcher.py")) + ', run_name="__main__")\n')
    launcher.chmod(0o700)
    profiles = ROOT / "cao/agent-store"
    profiles.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(HERE / "aiflow_script.md", profiles / "aiflow_script.md")
    return {"installed": True, "codex_version": version}


def serve():
    auth()
    env = clean_env()
    socket_root = ROOT / "tmux"
    socket_root.mkdir(exist_ok=True, mode=0o700)
    env["TMUX_TMPDIR"] = str(socket_root)
    # A private tmux server keeps user shell rc files from replacing the launcher PATH.
    tmux_config = ROOT / "tmux.conf"
    tmux_config.write_text('set -g default-shell /bin/bash\nset -g default-command "/bin/bash --noprofile --norc"\nset -g exit-empty off\n')
    exists = subprocess.run(["tmux", "has-session", "-t", "=aiflow-control"], env=env, capture_output=True, timeout=10)
    if exists.returncode:
        subprocess.run(["tmux", "-f", str(tmux_config), "new-session", "-d", "-s", "aiflow-control", "/bin/sleep infinity"],
                       env=env, check=True, capture_output=True, timeout=10)
    env.update(CAO_HOME_DIR=str(ROOT / "cao"), CAO_API_HOST="127.0.0.1", CAO_API_PORT="9891",
               CAO_AUTH_LOCAL_TOKEN=(ROOT / "token").read_text().strip(), CAO_TERMINAL_BACKEND="tmux",
               CAO_MEMORY_ENABLED="false", CAO_MAX_TERMINALS="1", CAO_AGENT_PLUGINS_ENABLED="false",
               PATH=str(ROOT / "bin") + ":" + env["PATH"])
    os.execve(str(ROOT / "venv/bin/cao-server"), ["cao-server", "--host", "127.0.0.1", "--port", "9891", "--terminal", "tmux"], env)


def main():
    action = sys.argv[1]
    if action == "attach":
        record = read(job_dir(sys.argv[2]) / "state.json")
        os.execvpe("tmux", ["tmux", "attach-session", "-t", "=" + record["session_name"]], tmux_env())
    if action == "install":
        return install()
    if action == "serve":
        return serve()
    if action == "watch":
        while True:
            time.sleep(5)
            try:
                with (ROOT / "bridge.lock").open("a") as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX)
                    record = poll(sys.argv[2])
                if record["status"] in FINAL:
                    return {"finished": True}
            except Exception:
                # Preserve state on outage; never submit another prompt.
                continue
    body = json.loads(sys.stdin.read(2_000_000) or "{}")
    if action == "check":
        return check()
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT / "bridge.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if action == "start":
            return start(body)
        if action in ("poll", "cancel"):
            return poll(body["request_id"], cancel=action == "cancel")
    raise ValueError("Thao tác không hợp lệ.")


if __name__ == "__main__":
    try:
        print(json.dumps(main(), ensure_ascii=False))
    except Exception as exc:
        message = str(exc) if isinstance(exc, (RuntimeError, ValueError)) else "WSL/CAO chưa sẵn sàng. Kiểm tra setup, đăng nhập và cửa sổ CAO."
        print(json.dumps({"error": message}, ensure_ascii=False))
        sys.exit(1)
