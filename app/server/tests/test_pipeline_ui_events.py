"""The worker pipeline reaches typed, project-scoped legacy WS and SSE feeds."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import WebSocketDisconnect
from sqlmodel import Session, SQLModel, create_engine, select

from server.api.routes import projects, ws
from server.config import Settings
from server.db.models import Job, JobLog, Project, Scene
from server.pipeline import event_bus
from server.pipeline.event_bus import EventBus
from server.pipeline.event_bus_bridge import EventBusJobLogBridge


@pytest.fixture
def environment(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'events.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    settings = Settings(data_dir=tmp_path)
    monkeypatch.setattr(projects, "get_settings", lambda: settings)
    monkeypatch.setattr(projects, "get_engine", lambda _: engine)
    monkeypatch.setattr("server.db.session.get_engine", lambda _: engine)
    bus = EventBus()
    monkeypatch.setattr(event_bus, "_shared_bus", bus)
    with Session(engine) as session:
        project = Project(short_id="wsfixture", title="WS fixture", status="ready")
        other = Project(short_id="otherfixture", title="Other fixture", status="ready")
        session.add_all([project, other])
        session.flush()
        job, other_job = Job(project_id=project.id, type="generate"), Job(project_id=other.id, type="generate")
        session.add_all([job, other_job, Scene(project_id=project.id, order=0, prompt="Fixture")])
        session.commit()
        yield engine, settings, bus, project.id, job.id, other.id, other_job.id
    engine.dispose()


class Socket:
    def __init__(self, bus):
        self.app = SimpleNamespace(state=SimpleNamespace(event_bus=bus))
        self.sent = asyncio.Queue()
        self.received = asyncio.Queue()
        self.closed = None

    async def accept(self):
        pass

    async def close(self, code):
        self.closed = code

    async def send_text(self, value):
        await self.sent.put(json.loads(value))

    async def receive_text(self):
        value = await self.received.get()
        if value is None:
            raise WebSocketDisconnect()
        return value


@pytest.mark.parametrize("identifier", ["short", "numeric"])
async def test_worker_orchestration_reaches_project_ws_and_only_own_job_log(environment, monkeypatch, identifier):
    engine, settings, bus, project_id, job_id, other_id, other_job_id = environment
    socket = Socket(bus)
    subscription = "wsfixture" if identifier == "short" else str(project_id)
    loop = asyncio.get_running_loop()
    previous_debug = loop.get_debug()
    loop.set_debug(True)
    route = asyncio.create_task(ws.ws_project_events(socket, subscription))
    other_bridge = EventBusJobLogBridge(bus, engine, other_job_id, project_id=other_id)

    async def run(self, **kwargs):
        self._bus.publish("scene_started", {"project_id": kwargs["project_id"], "scene_order": 0})
        raise RuntimeError("fixture stops before provider generation")

    monkeypatch.setattr("server.pipeline.orchestrator.PipelineOrchestrator.run", run)
    monkeypatch.setattr(projects, "_resolve_style_json", lambda _: "{}")
    try:
        assert (await asyncio.wait_for(socket.sent.get(), 2))["type"] == "connected"
        with pytest.raises(RuntimeError, match="fixture stops"):
            await asyncio.to_thread(lambda: asyncio.run(projects._orchestrate(project_id, job_id, settings)))
        message = await asyncio.wait_for(socket.sent.get(), 2)
        assert message["type"] == "scene_started"
        assert message["project_id"] == subscription
        assert message["data"]["project_id"] == project_id
        with Session(engine) as session:
            logs = session.exec(select(JobLog).where(JobLog.job_id == job_id)).all()
            other_logs = session.exec(select(JobLog).where(JobLog.job_id == other_job_id)).all()
            assert len(logs) == 1 and logs[0].message.startswith("[EVT:scene_started]")
            assert not other_logs
        await asyncio.to_thread(bus.publish, "scene_completed", {"project_id": other_id})
        await asyncio.to_thread(bus.publish, "pipeline_completed", {"project_id": project_id})
        assert (await asyncio.wait_for(socket.sent.get(), 2))["type"] == "pipeline_completed"
    finally:
        await socket.received.put(None)
        await asyncio.wait_for(route, 2)
        other_bridge.close()
        loop.set_debug(previous_debug)
    assert bus.subscriber_count("scene_started") == 0


async def test_unknown_project_ws_is_rejected_before_subscription(environment):
    _, _, bus, *_ = environment
    socket = Socket(bus)
    await ws.ws_project_events(socket, "unknown")
    assert socket.closed == 1008
    assert bus.subscriber_count("scene_started") == 0
    assert socket.sent.empty()
