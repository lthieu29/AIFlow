"""Tests for Quality Gates G1, G2, G3 (Task 2.3).

Tests cover:
    - GateResult dataclass
    - G1: validate_scene_list
    - G2: create_g2_gate, check_g2_status, approve_g2, override_g2
    - G3: check_scene_quality, get_scene_retry_count, should_retry_scene
    - check_expired_gates (G2.8 SLA)
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pytest
from sqlmodel import Session, SQLModel, create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def engine():
    """In-memory SQLite engine with all tables created."""
    from server.db import models  # noqa: F401 — registers all table classes

    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture()
def session(engine):
    """Fresh session for each test."""
    with Session(engine) as s:
        yield s


@pytest.fixture()
def project(session):
    """A minimal Project row for FK references."""
    from server.db.models.project import Project

    p = Project(
        short_id="p_test",
        title="Test Project",
        adapter="storyboard",
        skill="ecommerce-fashion",
    )
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


@pytest.fixture()
def scene(session, project):
    """A minimal Scene row for FK references."""
    from server.db.models.scene import Scene

    s = Scene(project_id=project.id, order=0)
    session.add(s)
    session.commit()
    session.refresh(s)
    return s


@pytest.fixture()
def settings():
    """Minimal settings stub — only gate_user_timeout_hours is needed."""
    from unittest.mock import MagicMock
    s = MagicMock()
    s.gate_user_timeout_hours = 24
    return s


# ─────────────────────────────────────────────────────────────────────────────
# Fake Scene for G1 tests (no DB needed)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class FakeScene:
    order: int
    visual_prompt: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# GateResult dataclass
# ─────────────────────────────────────────────────────────────────────────────

class TestGateResult:
    def test_passed_defaults(self):
        from server.pipeline.quality_gate import GateResult
        r = GateResult(gate_id="G1", status="passed")
        assert r.gate_id == "G1"
        assert r.status == "passed"
        assert r.message == ""
        assert r.retry_count == 0

    def test_failed_with_message(self):
        from server.pipeline.quality_gate import GateResult
        r = GateResult(gate_id="G3", status="failed", message="File missing", retry_count=1)
        assert r.status == "failed"
        assert r.message == "File missing"
        assert r.retry_count == 1

    def test_all_statuses_accepted(self):
        from server.pipeline.quality_gate import GateResult
        for status in ("passed", "failed", "expired", "overridden"):
            r = GateResult(gate_id="G2", status=status)
            assert r.status == status


# ─────────────────────────────────────────────────────────────────────────────
# G1 — validate_scene_list
# ─────────────────────────────────────────────────────────────────────────────

class TestG1ValidateSceneList:
    def test_empty_list_fails(self):
        from server.pipeline.gates.g1_scene_list import validate_scene_list
        result = validate_scene_list([])
        assert result.gate_id == "G1"
        assert result.status == "failed"
        assert "empty" in result.message.lower()

    def test_single_valid_scene_passes(self):
        from server.pipeline.gates.g1_scene_list import validate_scene_list
        scenes = [FakeScene(order=0, visual_prompt="A woman walks.")]
        result = validate_scene_list(scenes)
        assert result.status == "passed"
        assert result.gate_id == "G1"

    def test_multiple_valid_scenes_pass(self):
        from server.pipeline.gates.g1_scene_list import validate_scene_list
        scenes = [
            FakeScene(order=0, visual_prompt="Scene A"),
            FakeScene(order=1, visual_prompt="Scene B"),
            FakeScene(order=2, visual_prompt="Scene C"),
        ]
        result = validate_scene_list(scenes)
        assert result.status == "passed"

    def test_empty_prompt_fails(self):
        from server.pipeline.gates.g1_scene_list import validate_scene_list
        scenes = [
            FakeScene(order=0, visual_prompt="Valid prompt"),
            FakeScene(order=1, visual_prompt=""),  # empty
        ]
        result = validate_scene_list(scenes)
        assert result.status == "failed"
        assert "empty" in result.message.lower() or "prompt" in result.message.lower()

    def test_whitespace_only_prompt_fails(self):
        from server.pipeline.gates.g1_scene_list import validate_scene_list
        scenes = [FakeScene(order=0, visual_prompt="   ")]
        result = validate_scene_list(scenes)
        assert result.status == "failed"

    def test_non_sequential_orders_fail(self):
        from server.pipeline.gates.g1_scene_list import validate_scene_list
        scenes = [
            FakeScene(order=0, visual_prompt="A"),
            FakeScene(order=2, visual_prompt="B"),  # gap: missing order=1
        ]
        result = validate_scene_list(scenes)
        assert result.status == "failed"
        assert "sequential" in result.message.lower()

    def test_orders_not_starting_at_zero_fail(self):
        from server.pipeline.gates.g1_scene_list import validate_scene_list
        scenes = [
            FakeScene(order=1, visual_prompt="A"),
            FakeScene(order=2, visual_prompt="B"),
        ]
        result = validate_scene_list(scenes)
        assert result.status == "failed"

    def test_duplicate_orders_fail(self):
        from server.pipeline.gates.g1_scene_list import validate_scene_list
        scenes = [
            FakeScene(order=0, visual_prompt="A"),
            FakeScene(order=0, visual_prompt="B"),  # duplicate
        ]
        result = validate_scene_list(scenes)
        assert result.status == "failed"
        assert "duplicate" in result.message.lower()

    def test_scene_without_prompt_field_passes(self):
        """Scenes with no prompt-like attribute should not be blocked."""
        from server.pipeline.gates.g1_scene_list import validate_scene_list

        @dataclass
        class NoPromptScene:
            order: int

        scenes = [NoPromptScene(order=0), NoPromptScene(order=1)]
        result = validate_scene_list(scenes)
        assert result.status == "passed"

    def test_out_of_order_but_valid_set_passes(self):
        """Orders [1, 0, 2] should pass — we sort before checking."""
        from server.pipeline.gates.g1_scene_list import validate_scene_list
        scenes = [
            FakeScene(order=1, visual_prompt="B"),
            FakeScene(order=0, visual_prompt="A"),
            FakeScene(order=2, visual_prompt="C"),
        ]
        result = validate_scene_list(scenes)
        assert result.status == "passed"


# ─────────────────────────────────────────────────────────────────────────────
# G2 — asset approval gate
# ─────────────────────────────────────────────────────────────────────────────

class TestG2AssetApproval:
    def test_create_g2_gate_returns_record(self, session, project):
        from server.pipeline.gates.g2_asset_approval import create_g2_gate
        gate = create_g2_gate(session, project.id)
        assert gate.id is not None
        assert gate.gate_id == "G2"
        assert gate.project_id == project.id
        assert gate.status == "checking"
        assert gate.expired_at is not None

    def test_create_g2_gate_sets_sla_deadline(self, session, project):
        from server.pipeline.gates.g2_asset_approval import create_g2_gate
        gate = create_g2_gate(session, project.id, timeout_hours=12)
        # expired_at should be ~12h from now (allow 5s tolerance)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        expected = now + timedelta(hours=12)
        diff = abs((gate.expired_at - expected).total_seconds())
        assert diff < 5

    def test_check_g2_status_returns_checking(self, session, project):
        from server.pipeline.gates.g2_asset_approval import (
            check_g2_status,
            create_g2_gate,
        )
        create_g2_gate(session, project.id)
        assert check_g2_status(session, project.id) == "checking"

    def test_check_g2_status_not_found(self, session, project):
        from server.pipeline.gates.g2_asset_approval import check_g2_status
        assert check_g2_status(session, project.id) == "not_found"

    def test_approve_g2_marks_passed(self, session, project):
        from server.pipeline.gates.g2_asset_approval import (
            approve_g2,
            check_g2_status,
            create_g2_gate,
        )
        create_g2_gate(session, project.id)
        approve_g2(session, project.id)
        assert check_g2_status(session, project.id) == "passed"

    def test_override_g2_marks_overridden(self, session, project):
        from server.pipeline.gates.g2_asset_approval import (
            check_g2_status,
            create_g2_gate,
            override_g2,
        )
        create_g2_gate(session, project.id)
        override_g2(session, project.id)
        assert check_g2_status(session, project.id) == "overridden"

    def test_approve_g2_raises_if_no_gate(self, session, project):
        from server.pipeline.gates.g2_asset_approval import approve_g2
        with pytest.raises(ValueError, match="No G2 gate found"):
            approve_g2(session, project.id)

    def test_override_g2_raises_if_no_gate(self, session, project):
        from server.pipeline.gates.g2_asset_approval import override_g2
        with pytest.raises(ValueError, match="No G2 gate found"):
            override_g2(session, project.id)

    def test_check_g2_status_returns_latest_gate(self, session, project):
        """When multiple G2 gates exist, the most recent one is returned."""
        from server.pipeline.gates.g2_asset_approval import (
            approve_g2,
            check_g2_status,
            create_g2_gate,
        )
        create_g2_gate(session, project.id)
        approve_g2(session, project.id)
        # Create a second gate (e.g. after a re-run)
        create_g2_gate(session, project.id)
        # Latest gate is "checking", not "passed"
        assert check_g2_status(session, project.id) == "checking"


# ─────────────────────────────────────────────────────────────────────────────
# G3 — per-scene quality check
# ─────────────────────────────────────────────────────────────────────────────

class TestG3SceneQuality:
    def test_passes_when_file_exists_and_large_enough(self, tmp_path):
        from server.pipeline.gates.g3_scene_quality import check_scene_quality
        video = tmp_path / "scene0.mp4"
        video.write_bytes(b"x" * (101 * 1024))  # 101 KB
        result = check_scene_quality(FakeScene(order=0), video)
        assert result.gate_id == "G3"
        assert result.status == "passed"

    def test_fails_when_file_missing(self, tmp_path):
        from server.pipeline.gates.g3_scene_quality import check_scene_quality
        video = tmp_path / "nonexistent.mp4"
        result = check_scene_quality(FakeScene(order=0), video)
        assert result.status == "failed"
        assert "not found" in result.message.lower() or "G3.1" in result.message

    def test_fails_when_file_too_small(self, tmp_path):
        from server.pipeline.gates.g3_scene_quality import check_scene_quality
        video = tmp_path / "tiny.mp4"
        video.write_bytes(b"x" * 50)  # 50 bytes — way below 100 KB
        result = check_scene_quality(FakeScene(order=0), video)
        assert result.status == "failed"
        assert "small" in result.message.lower() or "G3.1" in result.message

    def test_fails_at_exactly_100kb(self, tmp_path):
        """Boundary: exactly 100 KB (102400 bytes) should fail (must be > 100KB)."""
        from server.pipeline.gates.g3_scene_quality import (
            _MIN_VIDEO_SIZE_BYTES,
            check_scene_quality,
        )
        video = tmp_path / "boundary.mp4"
        video.write_bytes(b"x" * _MIN_VIDEO_SIZE_BYTES)
        result = check_scene_quality(FakeScene(order=0), video)
        assert result.status == "failed"

    def test_passes_at_100kb_plus_one(self, tmp_path):
        from server.pipeline.gates.g3_scene_quality import (
            _MIN_VIDEO_SIZE_BYTES,
            check_scene_quality,
        )
        video = tmp_path / "just_over.mp4"
        video.write_bytes(b"x" * (_MIN_VIDEO_SIZE_BYTES + 1))
        result = check_scene_quality(FakeScene(order=0), video)
        assert result.status == "passed"

    def test_max_retries_is_2(self):
        from server.pipeline.gates.g3_scene_quality import MAX_RETRIES
        assert MAX_RETRIES == 2

    def test_get_scene_retry_count_zero_initially(self, session, scene):
        from server.pipeline.gates.g3_scene_quality import get_scene_retry_count
        assert get_scene_retry_count(session, scene.id) == 0

    def test_get_scene_retry_count_counts_failed_gates(self, session, scene, project):
        from server.db.models.quality_gate import QualityGate
        from server.pipeline.gates.g3_scene_quality import get_scene_retry_count

        # Add 2 failed G3 gates for this scene
        for _ in range(2):
            session.add(QualityGate(
                gate_id="G3",
                project_id=project.id,
                scene_id=scene.id,
                status="failed",
            ))
        session.commit()

        assert get_scene_retry_count(session, scene.id) == 2

    def test_get_scene_retry_count_ignores_passed_gates(self, session, scene, project):
        from server.db.models.quality_gate import QualityGate
        from server.pipeline.gates.g3_scene_quality import get_scene_retry_count

        session.add(QualityGate(
            gate_id="G3",
            project_id=project.id,
            scene_id=scene.id,
            status="passed",
        ))
        session.commit()

        assert get_scene_retry_count(session, scene.id) == 0

    def test_should_retry_true_when_zero_retries(self, session, scene):
        from server.pipeline.gates.g3_scene_quality import should_retry_scene
        assert should_retry_scene(session, scene.id) is True

    def test_should_retry_true_when_one_retry(self, session, scene, project):
        from server.db.models.quality_gate import QualityGate
        from server.pipeline.gates.g3_scene_quality import should_retry_scene

        session.add(QualityGate(
            gate_id="G3",
            project_id=project.id,
            scene_id=scene.id,
            status="failed",
        ))
        session.commit()

        assert should_retry_scene(session, scene.id) is True

    def test_should_retry_false_when_max_retries_reached(self, session, scene, project):
        from server.db.models.quality_gate import QualityGate
        from server.pipeline.gates.g3_scene_quality import MAX_RETRIES, should_retry_scene

        for _ in range(MAX_RETRIES):
            session.add(QualityGate(
                gate_id="G3",
                project_id=project.id,
                scene_id=scene.id,
                status="failed",
            ))
        session.commit()

        assert should_retry_scene(session, scene.id) is False


# ─────────────────────────────────────────────────────────────────────────────
# check_expired_gates — G2.8 SLA
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckExpiredGates:
    def test_expires_overdue_checking_gate(self, session, project, settings):
        from server.db.models.quality_gate import QualityGate
        from server.pipeline.quality_gate import check_expired_gates

        # Create a gate that expired 1 hour ago
        past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
        gate = QualityGate(
            gate_id="G2",
            project_id=project.id,
            status="checking",
            expired_at=past,
        )
        session.add(gate)
        session.commit()
        session.refresh(gate)

        count = check_expired_gates(session, settings)
        assert count == 1

        session.refresh(gate)
        assert gate.status == "expired"

    def test_does_not_expire_future_gate(self, session, project, settings):
        from server.db.models.quality_gate import QualityGate
        from server.pipeline.quality_gate import check_expired_gates

        future = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=23)
        gate = QualityGate(
            gate_id="G2",
            project_id=project.id,
            status="checking",
            expired_at=future,
        )
        session.add(gate)
        session.commit()

        count = check_expired_gates(session, settings)
        assert count == 0

        session.refresh(gate)
        assert gate.status == "checking"

    def test_does_not_expire_already_passed_gate(self, session, project, settings):
        from server.db.models.quality_gate import QualityGate
        from server.pipeline.quality_gate import check_expired_gates

        past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
        gate = QualityGate(
            gate_id="G2",
            project_id=project.id,
            status="passed",
            expired_at=past,
        )
        session.add(gate)
        session.commit()

        count = check_expired_gates(session, settings)
        assert count == 0

        session.refresh(gate)
        assert gate.status == "passed"

    def test_does_not_expire_gate_without_deadline(self, session, project, settings):
        from server.db.models.quality_gate import QualityGate
        from server.pipeline.quality_gate import check_expired_gates

        gate = QualityGate(
            gate_id="G2",
            project_id=project.id,
            status="checking",
            expired_at=None,  # no deadline
        )
        session.add(gate)
        session.commit()

        count = check_expired_gates(session, settings)
        assert count == 0

    def test_expires_multiple_overdue_gates(self, session, project, settings):
        from server.db.models.quality_gate import QualityGate
        from server.pipeline.quality_gate import check_expired_gates

        past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=2)
        for _ in range(3):
            session.add(QualityGate(
                gate_id="G2",
                project_id=project.id,
                status="checking",
                expired_at=past,
            ))
        session.commit()

        count = check_expired_gates(session, settings)
        assert count == 3

    def test_returns_zero_when_no_gates(self, session, settings):
        from server.pipeline.quality_gate import check_expired_gates
        count = check_expired_gates(session, settings)
        assert count == 0
