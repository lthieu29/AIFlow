"""Tests for EventBus and PipelineOrchestrator (Task 2.4).

Unit tests cover:
    - EventBus subscribe / publish / unsubscribe
    - EventBus error isolation (bad callback doesn't break others)
    - PipelineOrchestrator G1 validation path
    - PipelineOrchestrator event publishing for scene lifecycle
    - G3 retry logic bounded at MAX_RETRIES=2
    - Scene chain: last_frame_path propagated between scenes
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.pipeline.event_bus import (
    EVENT_GATE_STATUS_CHANGED,
    EVENT_PIPELINE_COMPLETED,
    EVENT_PIPELINE_FAILED,
    EVENT_SCENE_COMPLETED,
    EVENT_SCENE_FAILED,
    EVENT_SCENE_STARTED,
    EventBus,
)
from server.pipeline.gates.g3_scene_quality import MAX_RETRIES


# ── EventBus tests ────────────────────────────────────────────────────────────


class TestEventBus:
    def test_subscribe_and_publish(self):
        bus = EventBus()
        received: list[dict] = []
        bus.subscribe("scene_started", received.append)
        bus.publish("scene_started", {"scene_order": 0})
        assert received == [{"scene_order": 0}]

    def test_multiple_subscribers(self):
        bus = EventBus()
        log1: list[dict] = []
        log2: list[dict] = []
        bus.subscribe("scene_started", log1.append)
        bus.subscribe("scene_started", log2.append)
        bus.publish("scene_started", {"x": 1})
        assert log1 == [{"x": 1}]
        assert log2 == [{"x": 1}]

    def test_unsubscribe(self):
        bus = EventBus()
        received: list[dict] = []
        bus.subscribe("scene_completed", received.append)
        bus.unsubscribe("scene_completed", received.append)
        bus.publish("scene_completed", {"scene_order": 1})
        assert received == []

    def test_unsubscribe_not_registered_is_noop(self):
        bus = EventBus()
        # Should not raise
        bus.unsubscribe("scene_started", lambda d: None)

    def test_bad_callback_does_not_break_others(self):
        bus = EventBus()
        good_log: list[dict] = []

        def bad_callback(data: dict) -> None:
            raise RuntimeError("boom")

        bus.subscribe("scene_started", bad_callback)
        bus.subscribe("scene_started", good_log.append)
        bus.publish("scene_started", {"scene_order": 0})
        # good_log should still receive the event
        assert good_log == [{"scene_order": 0}]

    def test_subscriber_count(self):
        bus = EventBus()
        assert bus.subscriber_count("scene_started") == 0
        bus.subscribe("scene_started", lambda d: None)
        bus.subscribe("scene_started", lambda d: None)
        assert bus.subscriber_count("scene_started") == 2

    def test_publish_unknown_event_does_not_raise(self):
        bus = EventBus()
        # Should log a warning but not raise
        bus.publish("unknown_event_xyz", {"data": 1})

    def test_different_event_types_isolated(self):
        bus = EventBus()
        started: list[dict] = []
        completed: list[dict] = []
        bus.subscribe("scene_started", started.append)
        bus.subscribe("scene_completed", completed.append)
        bus.publish("scene_started", {"order": 0})
        bus.publish("scene_completed", {"order": 0})
        assert len(started) == 1
        assert len(completed) == 1
        assert started[0]["order"] == 0
        assert completed[0]["order"] == 0


# ── Orchestrator tests ────────────────────────────────────────────────────────


def _make_scene(order: int, prompt: str = "test prompt") -> MagicMock:
    """Create a mock Scene with the given order and prompt."""
    scene = MagicMock()
    scene.order = order
    scene.visual_prompt = prompt
    scene.location_hint = "unspecified"
    scene.id = order + 100
    scene.last_frame_path = None
    return scene


def _make_settings() -> MagicMock:
    settings = MagicMock()
    settings.data_dir = Path("/tmp/aiflow_test")
    return settings


def _make_sdk() -> MagicMock:
    sdk = MagicMock()
    sdk.gen_video = AsyncMock(return_value="operations/test-op-123")
    sdk.check_async = AsyncMock(return_value={
        "data": {
            "operations": [{
                "status": "MEDIA_GENERATION_STATUS_SUCCESSFUL",
                "operation": {
                    "name": "operations/test-op-123",
                    "done": True,
                    "metadata": {
                        "video": {
                            "fifeUrl": "https://example.com/video.mp4",
                        }
                    }
                }
            }]
        }
    })
    return sdk


class TestPipelineOrchestratorG1:
    """G1 validation gate tests."""

    @pytest.mark.asyncio
    async def test_g1_fails_on_empty_scene_list(self):
        from server.pipeline.orchestrator import PipelineOrchestrator

        bus = EventBus()
        events: list[dict] = []
        bus.subscribe(EVENT_PIPELINE_FAILED, events.append)

        orch = PipelineOrchestrator(
            settings=_make_settings(),
            flow_sdk=_make_sdk(),
            event_bus=bus,
        )

        with pytest.raises(RuntimeError, match="G1 validation failed"):
            await orch.run(
                project_id=1,
                scenes=[],
                style_json='{"art_style": "cinematic"}',
                assets=[],
            )

        assert len(events) == 1
        assert events[0]["project_id"] == 1

    @pytest.mark.asyncio
    async def test_g1_gate_status_published_on_pass(self):
        """G1 gate_status_changed event is published when G1 passes."""
        from server.pipeline.orchestrator import PipelineOrchestrator

        bus = EventBus()
        gate_events: list[dict] = []
        bus.subscribe(EVENT_GATE_STATUS_CHANGED, gate_events.append)

        orch = PipelineOrchestrator(
            settings=_make_settings(),
            flow_sdk=_make_sdk(),
            event_bus=bus,
        )

        scenes = [_make_scene(0)]

        # Patch _wait_for_g2 and _run_scene to avoid real I/O
        with (
            patch.object(orch, "_wait_for_g2", new=AsyncMock()),
            patch.object(orch, "_run_scene", new=AsyncMock(return_value=True)),
        ):
            result = await orch.run(
                project_id=1,
                scenes=scenes,
                style_json='{"art_style": "cinematic"}',
                assets=[],
            )

        assert result is True
        g1_events = [e for e in gate_events if e.get("gate_id") == "G1"]
        assert len(g1_events) == 1
        assert g1_events[0]["status"] == "passed"


class TestPipelineOrchestratorEvents:
    """Event publishing tests for scene lifecycle."""

    @pytest.mark.asyncio
    async def test_pipeline_completed_event_published(self):
        from server.pipeline.orchestrator import PipelineOrchestrator

        bus = EventBus()
        completed_events: list[dict] = []
        bus.subscribe(EVENT_PIPELINE_COMPLETED, completed_events.append)

        orch = PipelineOrchestrator(
            settings=_make_settings(),
            flow_sdk=_make_sdk(),
            event_bus=bus,
        )

        scenes = [_make_scene(0), _make_scene(1)]

        with (
            patch.object(orch, "_wait_for_g2", new=AsyncMock()),
            patch.object(orch, "_run_scene", new=AsyncMock(return_value=True)),
        ):
            result = await orch.run(
                project_id=5,
                scenes=scenes,
                style_json='{"art_style": "cinematic"}',
                assets=[],
            )

        assert result is True
        assert len(completed_events) == 1
        assert completed_events[0]["project_id"] == 5
        assert completed_events[0]["total_scenes"] == 2
        assert completed_events[0]["all_passed"] is True

    @pytest.mark.asyncio
    async def test_pipeline_completed_with_partial_failure(self):
        """all_passed=False when at least one scene fails."""
        from server.pipeline.orchestrator import PipelineOrchestrator

        bus = EventBus()
        completed_events: list[dict] = []
        bus.subscribe(EVENT_PIPELINE_COMPLETED, completed_events.append)

        orch = PipelineOrchestrator(
            settings=_make_settings(),
            flow_sdk=_make_sdk(),
            event_bus=bus,
        )

        scenes = [_make_scene(0), _make_scene(1)]

        # First scene passes, second fails
        run_scene_results = [True, False]
        call_count = 0

        async def mock_run_scene(**kwargs):
            nonlocal call_count
            result = run_scene_results[call_count]
            call_count += 1
            return result

        with (
            patch.object(orch, "_wait_for_g2", new=AsyncMock()),
            patch.object(orch, "_run_scene", new=mock_run_scene),
        ):
            result = await orch.run(
                project_id=5,
                scenes=scenes,
                style_json='{"art_style": "cinematic"}',
                assets=[],
            )

        assert result is False
        assert completed_events[0]["all_passed"] is False


class TestG3RetryLogic:
    """G3 retry bounded at MAX_RETRIES=2."""

    def test_max_retries_constant(self):
        assert MAX_RETRIES == 2

    @pytest.mark.asyncio
    async def test_scene_retried_on_gen_error(self):
        """Scene is retried up to MAX_RETRIES times on generation error."""
        from server.pipeline.orchestrator import PipelineOrchestrator

        bus = EventBus()
        started_events: list[dict] = []
        failed_events: list[dict] = []
        bus.subscribe(EVENT_SCENE_STARTED, started_events.append)
        bus.subscribe(EVENT_SCENE_FAILED, failed_events.append)

        orch = PipelineOrchestrator(
            settings=_make_settings(),
            flow_sdk=_make_sdk(),
            event_bus=bus,
        )

        scene = _make_scene(0)

        # _generate_scene always raises
        with patch.object(
            orch,
            "_generate_scene",
            new=AsyncMock(side_effect=RuntimeError("gen failed")),
        ):
            result = await orch._run_scene(
                scene=scene,
                project_id=1,
                style_lock=MagicMock(inject=lambda p: p),
                asset_lock=MagicMock(inject=lambda p: p),
                scene_chain=MagicMock(get_last_frame=lambda o: None),
                all_scenes=[scene],
            )

        assert result is False
        # Should have attempted MAX_RETRIES times
        assert len(started_events) == MAX_RETRIES
        assert len(failed_events) == 1
        assert failed_events[0]["retry_count"] == MAX_RETRIES

    @pytest.mark.asyncio
    async def test_scene_succeeds_on_second_attempt(self):
        """Scene succeeds on retry after first attempt fails."""
        from server.pipeline.orchestrator import PipelineOrchestrator

        bus = EventBus()
        completed_events: list[dict] = []
        bus.subscribe(EVENT_SCENE_COMPLETED, completed_events.append)

        orch = PipelineOrchestrator(
            settings=_make_settings(),
            flow_sdk=_make_sdk(),
            event_bus=bus,
        )

        scene = _make_scene(0)

        # Create a fake video file for G3 to pass
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            # Write > 100KB to pass G3
            f.write(b"x" * (101 * 1024))
            video_path = Path(f.name)

        call_count = 0

        async def mock_generate(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("first attempt failed")
            return video_path

        with (
            patch.object(orch, "_generate_scene", new=mock_generate),
            patch("server.pipeline.orchestrator._extract_last_frame", return_value=None),
        ):
            result = await orch._run_scene(
                scene=scene,
                project_id=1,
                style_lock=MagicMock(inject=lambda p: p),
                asset_lock=MagicMock(inject=lambda p: p),
                scene_chain=MagicMock(get_last_frame=lambda o: None),
                all_scenes=[scene],
            )

        video_path.unlink(missing_ok=True)
        assert result is True
        assert len(completed_events) == 1


class TestSceneChainState:
    """_SceneChainState tracks last frames correctly."""

    def test_get_last_frame_returns_none_for_negative_order(self):
        from server.pipeline.orchestrator import _SceneChainState

        state = _SceneChainState()
        assert state.get_last_frame(-1) is None

    def test_set_and_get_last_frame(self, tmp_path):
        from server.pipeline.orchestrator import _SceneChainState

        state = _SceneChainState()
        frame = tmp_path / "frame.png"
        frame.write_bytes(b"fake png")
        state.set_last_frame(0, frame)
        assert state.get_last_frame(0) == frame

    def test_get_last_frame_returns_none_if_file_missing(self, tmp_path):
        from server.pipeline.orchestrator import _SceneChainState

        state = _SceneChainState()
        missing = tmp_path / "nonexistent.png"
        state.set_last_frame(0, missing)
        assert state.get_last_frame(0) is None
