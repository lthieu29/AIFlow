from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlmodel import SQLModel, create_engine

from server.pipeline.orchestrator import PipelineOrchestrator


@pytest.mark.parametrize("status", ["expired", "failed", "not_found", "passed", "overridden"])
async def test_g2_only_explicit_approval_proceeds(tmp_path, monkeypatch, status):
    from server.db import session as database
    from server.pipeline.gates import g2_asset_approval as gate
    engine = create_engine(f"sqlite:///{tmp_path / 'gate.db'}")
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(database, "get_engine", lambda _: engine)
    monkeypatch.setattr(gate, "create_g2_gate", lambda *a, **k: SimpleNamespace(id=1))
    monkeypatch.setattr(gate, "check_g2_status", lambda *a, **k: status)
    monkeypatch.setattr("server.pipeline.orchestrator.asyncio.sleep", AsyncMock())
    orch = PipelineOrchestrator(settings=MagicMock(), flow_sdk=MagicMock(), event_bus=MagicMock())
    if status in ("passed", "overridden"):
        await orch._wait_for_g2(1)
    else:
        with pytest.raises(RuntimeError, match="G2"):
            await orch._wait_for_g2(1)
    engine.dispose()


async def test_g2_database_error_stops(monkeypatch):
    from server.db import session as database
    def broken(_):
        raise RuntimeError("DB unavailable")
    monkeypatch.setattr(database, "get_engine", broken)
    orch = PipelineOrchestrator(settings=MagicMock(), flow_sdk=MagicMock(), event_bus=MagicMock())
    with pytest.raises(RuntimeError, match="G2"):
        await orch._wait_for_g2(1)


async def test_initial_reference_and_aspect_forwarded(tmp_path):
    from server.db.models.asset import Asset
    from server.db.models.scene import Scene
    from server.config import Settings
    from server.tests.test_production import image_bytes
    reference = tmp_path / "reference.png"
    reference.write_bytes(image_bytes())
    sdk = MagicMock(gen_video=AsyncMock(return_value="operation"))
    orch = PipelineOrchestrator(settings=Settings(data_dir=tmp_path), flow_sdk=sdk, event_bus=MagicMock())
    orch._aspect = "16:9"
    orch._poll_until_done = AsyncMock(return_value=tmp_path / "result.mp4")
    scene = Scene(project_id=1, order=0, prompt="A green room", narration="", duration=6)
    lock = SimpleNamespace(inject=lambda text: text)
    await orch._generate_scene(scene=scene, project_id=1, style_lock=lock, asset_lock=lock,
        assets=[Asset(project_id=1, name="First frame", type="location", file_path=str(reference))],
        scene_chain=SimpleNamespace(get_last_frame=lambda _: None), all_scenes=[scene])
    arguments = sdk.gen_video.call_args.kwargs
    assert arguments["start_image"] == reference
    assert arguments["aspect"] == "16:9"
    assert arguments["duration"] == 6
    assert "A green room" in arguments["prompt"]


def test_visual_prompt_precedes_narration():
    from server.db.models.scene import Scene
    from server.pipeline.orchestrator import _get_scene_prompt
    scene = Scene(project_id=1, order=0, prompt="A close-up of a red clock", narration="She had one hour left.")
    assert _get_scene_prompt(scene) == "A close-up of a red clock"
