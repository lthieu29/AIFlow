"""Real HTTP stream regression for the supported server launcher's shutdown budget."""

import asyncio
import json
import queue
import runpy
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from sqlmodel import Session, SQLModel, create_engine

from scripts import dev_server
from server import config, logging_setup, main
from server.api.routes import jobs
from server.db import models  # noqa: F401
from server.db.models.job import Job


def test_supported_launcher_bounds_graceful_shutdown(monkeypatch):
    settings = SimpleNamespace(host="127.0.0.1", port=8101, debug=True, log_level="INFO")
    monkeypatch.setattr(config, "load_settings", lambda: settings)
    monkeypatch.setattr(logging_setup, "setup_logging", Mock())
    launch = Mock()
    monkeypatch.setattr(uvicorn, "run", launch)

    runpy.run_path(main.__file__, run_name="__main__")

    assert launch.call_args.kwargs["timeout_graceful_shutdown"] == 10
    assert launch.call_args.kwargs["reload"] is True


def test_dev_launcher_defaults_and_explicit_cli_options(monkeypatch):
    launch = Mock()
    monkeypatch.setattr(dev_server, "uvicorn_main", launch)
    dev_server.main([])
    assert launch.call_args.kwargs["args"] == [
        "server.main:app", "--port", "8101", "--timeout-graceful-shutdown", "10",
    ]
    args = ["custom:app", "--host", "127.0.0.1", "--port=8102", "--timeout-graceful-shutdown", "1"]
    dev_server.main(args)
    assert launch.call_args.kwargs["args"] == args


@pytest.mark.skipif(sys.platform != "win32", reason="Windows console stream restoration")
def test_console_wrapper_restores_stdout_after_launcher_failure(monkeypatch):
    kernel = Mock()
    kernel.CreateFileW.return_value = 123
    monkeypatch.setattr(dev_server.ctypes, "WinDLL", lambda *args, **kwargs: kernel)
    original = sys.stdout
    with pytest.raises(RuntimeError, match="launcher failed"):
        with dev_server.redirected_reload_console(True):
            assert sys.stdout.encoding == original.encoding
            assert sys.stdout.isatty() == original.isatty()
            sys.stdout.flush()
            raise RuntimeError("launcher failed")
    assert sys.stdout is original
    kernel.WriteConsoleW.assert_called_once()
    kernel.CloseHandle.assert_called_once_with(123)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows redirected console reload regression")
def test_windows_hidden_reload_with_redirected_output_and_open_stream(tmp_path):
    source = tmp_path / "probe.py"
    source.write_text('''import asyncio
import os
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
app = FastAPI()
@app.get("/health")
async def health():
    return {"pid": os.getpid()}
@app.get("/stream")
async def stream():
    async def chunks():
        while True:
            yield b"x" * 65536
            await asyncio.sleep(0.01)
    return StreamingResponse(chunks())
''', encoding="utf-8")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    launcher = Path(dev_server.__file__).resolve()
    process = subprocess.Popen(
        [sys.executable, str(launcher), "probe:app", "--host", "127.0.0.1", "--port", str(port),
         "--reload", "--reload-dir", str(tmp_path), "--timeout-graceful-shutdown", "1"],
        cwd=tmp_path, startupinfo=startup, creationflags=subprocess.CREATE_NEW_CONSOLE,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    messages = queue.Queue()

    def read_output():
        for line in process.stdout:
            messages.put(line)

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()

    def wait_for_startup():
        deadline = time.monotonic() + 15
        observed = []
        while time.monotonic() < deadline:
            try:
                line = messages.get(timeout=max(0.01, deadline - time.monotonic()))
            except queue.Empty:
                pytest.fail("Reload did not finish within 15s: " + "".join(observed))
            observed.append(line)
            if "Application startup complete" in line:
                return observed
        pytest.fail("Reload did not finish within 15s: " + "".join(observed))

    stream = None
    try:
        wait_for_startup()
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as response:
            old_pid = json.load(response)["pid"]
        stream = urllib.request.urlopen(f"http://127.0.0.1:{port}/stream", timeout=3)
        stream.read(1)
        touched_at = time.monotonic()
        source.touch()
        logs = "".join(wait_for_startup())
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as response:
            new_pid = json.load(response)["pid"]
        assert old_pid != new_pid
        assert time.monotonic() - touched_at < 15
        assert "timeout graceful shutdown exceeded" in logs
        assert "Application shutdown complete" in logs
    finally:
        if stream is not None:
            stream.close()
        # Only the tree created by this test is terminated, including the reload worker.
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, check=False)
        process.wait(timeout=5)
        reader.join(timeout=5)
        process.stdout.close()


@pytest.mark.parametrize("finish_job", [False, True])
async def test_shutdown_reaches_lifespan_with_open_job_stream(tmp_path, monkeypatch, finish_job):
    engine = create_engine(f"sqlite:///{tmp_path / 'jobs.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        job = Job(project_id=1, type="test", status="running")
        session.add(job)
        session.commit()
        job_id = job.id

    monkeypatch.setattr(jobs, "get_engine", lambda settings: engine)
    monkeypatch.setattr(jobs, "_POLL_INTERVAL", 0.01)
    stopped = asyncio.Event()
    ready = asyncio.Event()

    @asynccontextmanager
    async def lifespan(app):
        yield
        stopped.set()

    app = FastAPI(lifespan=lifespan)
    app.include_router(jobs.router)
    app.dependency_overrides[jobs.get_settings] = lambda: SimpleNamespace()

    class ReadyServer(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets=sockets)
            ready.set()

    server = ReadyServer(uvicorn.Config(
        app, host="127.0.0.1", lifespan="on", log_config=None,
        timeout_graceful_shutdown=0.2,
    ))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            await asyncio.wait_for(ready.wait(), timeout=3)
            async with httpx.AsyncClient() as client:
                async with client.stream("GET", f"http://127.0.0.1:{port}/api/jobs/{job_id}/stream") as response:
                    assert response.status_code == 200
                    lines = response.aiter_lines()
                    assert await anext(lines) == ": keep-alive"
                    server.should_exit = True
                    if finish_job:
                        with Session(engine) as session:
                            job = session.get(Job, job_id)
                            job.status = "success"
                            session.add(job)
                            session.commit()
                    await asyncio.wait_for(asyncio.shield(serving), timeout=3)
                    assert stopped.is_set()
                    assert not server.server_state.tasks
                    if finish_job:
                        remaining = [line async for line in lines]
                        assert "event: job.done" in remaining
        finally:
            server.should_exit = True
            server.force_exit = True
            if not serving.done():
                await asyncio.wait_for(serving, timeout=3)
            engine.dispose()
