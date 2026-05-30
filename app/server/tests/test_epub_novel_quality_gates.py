"""Tests for Task 6.3 — EPUB quality checkpoints.

Covers:
    - EpubSkillRestrictionError: message, attributes
    - validate_epub_skill / check_epub_skill: allowed/rejected skills
    - EpubGateResult: dataclass fields and defaults
    - run_character_gate: returns EG1 result, logs characters
    - run_plot_gate: returns EG2 result, logs scene info
    - run_style_gate: returns EG3 result, logs style info
    - DB gate creation: EG1/EG2/EG3 records created when session provided
    - Adapter skill restriction: AdapterError raised for wrong skill
    - Adapter end-to-end: gates run during adapt() with kdrama-romance skill
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


# ─── EPUB fixture helpers ─────────────────────────────────────────────────────


def _make_epub(
    title: str = "Test Book",
    author: str = "Test Author",
    chapters: list[tuple[str, str, str]] | None = None,
) -> Path:
    """Create a minimal EPUB file and return its path."""
    from ebooklib import epub

    if chapters is None:
        chapters = [
            ("chap1.xhtml", "Chapter One", "<h1>Chapter One</h1><p>Hello world.</p>"),
        ]

    book = epub.EpubBook()
    book.set_title(title)
    book.add_author(author)

    epub_items = []
    toc_links = []
    for file_name, chap_title, body in chapters:
        item = epub.EpubHtml(title=chap_title, file_name=file_name, lang="en")
        item.content = f"<html><body>{body}</body></html>"
        book.add_item(item)
        epub_items.append(item)
        toc_links.append(epub.Link(file_name, chap_title, file_name.replace(".", "_")))

    book.toc = tuple(toc_links)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav"] + epub_items

    tmp = tempfile.NamedTemporaryFile(suffix=".epub", delete=False)
    tmp.close()
    epub.write_epub(tmp.name, book)
    return Path(tmp.name)


# ─── DB fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture()
def engine():
    """In-memory SQLite engine with all tables created."""
    from server.db import models  # noqa: F401 — registers all table classes

    from sqlmodel import SQLModel, create_engine

    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture()
def session(engine):
    """Fresh session for each test."""
    from sqlmodel import Session

    with Session(engine) as s:
        yield s


@pytest.fixture()
def project(session):
    """A minimal Project row for FK references."""
    from server.db.models.project import Project

    p = Project(
        short_id="p_epub_test",
        title="EPUB Test Project",
        adapter="epub_novel",
        skill="kdrama-romance",
    )
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


# ═════════════════════════════════════════════════════════════════════════════
# EpubSkillRestrictionError
# ═════════════════════════════════════════════════════════════════════════════


class TestEpubSkillRestrictionError:
    def test_message_contains_requested_skill(self):
        from server.pipeline.gates.epub_checkpoints import EpubSkillRestrictionError

        err = EpubSkillRestrictionError("ecommerce-fashion")
        assert "ecommerce-fashion" in str(err)

    def test_message_contains_allowed_skill(self):
        from server.pipeline.gates.epub_checkpoints import (
            EPUB_ALLOWED_SKILL,
            EpubSkillRestrictionError,
        )

        err = EpubSkillRestrictionError("other-skill")
        assert EPUB_ALLOWED_SKILL in str(err)

    def test_attributes_set_correctly(self):
        from server.pipeline.gates.epub_checkpoints import (
            EPUB_ALLOWED_SKILL,
            EpubSkillRestrictionError,
        )

        err = EpubSkillRestrictionError("wrong-skill")
        assert err.requested_skill == "wrong-skill"
        assert err.allowed_skill == EPUB_ALLOWED_SKILL

    def test_is_exception(self):
        from server.pipeline.gates.epub_checkpoints import EpubSkillRestrictionError

        err = EpubSkillRestrictionError("x")
        assert isinstance(err, Exception)


# ═════════════════════════════════════════════════════════════════════════════
# validate_epub_skill / check_epub_skill
# ═════════════════════════════════════════════════════════════════════════════


class TestValidateEpubSkill:
    def test_kdrama_romance_passes(self):
        from server.pipeline.gates.epub_checkpoints import validate_epub_skill

        # Should not raise
        validate_epub_skill("kdrama-romance")

    def test_none_raises(self):
        from server.pipeline.gates.epub_checkpoints import (
            EpubSkillRestrictionError,
            validate_epub_skill,
        )

        with pytest.raises(EpubSkillRestrictionError):
            validate_epub_skill(None)

    def test_wrong_skill_raises(self):
        from server.pipeline.gates.epub_checkpoints import (
            EpubSkillRestrictionError,
            validate_epub_skill,
        )

        with pytest.raises(EpubSkillRestrictionError):
            validate_epub_skill("ecommerce-fashion")

    def test_empty_string_raises(self):
        from server.pipeline.gates.epub_checkpoints import (
            EpubSkillRestrictionError,
            validate_epub_skill,
        )

        with pytest.raises(EpubSkillRestrictionError):
            validate_epub_skill("")


class TestCheckEpubSkill:
    def test_kdrama_romance_passes(self):
        from server.content.adapters.epub_novel.quality_gates import check_epub_skill

        check_epub_skill("kdrama-romance")  # no exception

    def test_wrong_skill_raises(self):
        from server.content.adapters.epub_novel.quality_gates import check_epub_skill
        from server.pipeline.gates.epub_checkpoints import EpubSkillRestrictionError

        with pytest.raises(EpubSkillRestrictionError):
            check_epub_skill("narrative-script")

    def test_none_raises(self):
        from server.content.adapters.epub_novel.quality_gates import check_epub_skill
        from server.pipeline.gates.epub_checkpoints import EpubSkillRestrictionError

        with pytest.raises(EpubSkillRestrictionError):
            check_epub_skill(None)


# ═════════════════════════════════════════════════════════════════════════════
# EpubGateResult dataclass
# ═════════════════════════════════════════════════════════════════════════════


class TestEpubGateResult:
    def test_fields_set_correctly(self):
        from server.content.adapters.epub_novel.quality_gates import EpubGateResult

        r = EpubGateResult(gate_id="EG1", status="checking", message="test", payload={"x": 1})
        assert r.gate_id == "EG1"
        assert r.status == "checking"
        assert r.message == "test"
        assert r.payload == {"x": 1}

    def test_defaults(self):
        from server.content.adapters.epub_novel.quality_gates import EpubGateResult

        r = EpubGateResult(gate_id="EG2", status="passed")
        assert r.message == ""
        assert r.payload is None

    def test_all_gate_ids_accepted(self):
        from server.content.adapters.epub_novel.quality_gates import EpubGateResult

        for gid in ("EG1", "EG2", "EG3"):
            r = EpubGateResult(gate_id=gid, status="checking")
            assert r.gate_id == gid


# ═════════════════════════════════════════════════════════════════════════════
# run_character_gate (EG1)
# ═════════════════════════════════════════════════════════════════════════════


class TestRunCharacterGate:
    @pytest.mark.asyncio
    async def test_returns_eg1_result(self):
        from server.content.adapters.epub_novel.quality_gates import run_character_gate
        from server.content.character_dedup import CharacterRef

        chars = [CharacterRef(name="Ji-ho"), CharacterRef(name="Seo-jun")]
        result = await run_character_gate(chars)
        assert result.gate_id == "EG1"

    @pytest.mark.asyncio
    async def test_status_is_checking(self):
        from server.content.adapters.epub_novel.quality_gates import run_character_gate
        from server.content.character_dedup import CharacterRef

        result = await run_character_gate([CharacterRef(name="Ji-ho")])
        assert result.status == "checking"

    @pytest.mark.asyncio
    async def test_payload_contains_character_names(self):
        from server.content.adapters.epub_novel.quality_gates import run_character_gate
        from server.content.character_dedup import CharacterRef

        chars = [CharacterRef(name="Ji-ho"), CharacterRef(name="Seo-jun")]
        result = await run_character_gate(chars)
        assert "Ji-ho" in result.payload["characters"]
        assert "Seo-jun" in result.payload["characters"]

    @pytest.mark.asyncio
    async def test_empty_characters_list(self):
        from server.content.adapters.epub_novel.quality_gates import run_character_gate

        result = await run_character_gate([])
        assert result.gate_id == "EG1"
        assert result.payload["characters"] == []

    @pytest.mark.asyncio
    async def test_message_contains_count(self):
        from server.content.adapters.epub_novel.quality_gates import run_character_gate
        from server.content.character_dedup import CharacterRef

        chars = [CharacterRef(name="A"), CharacterRef(name="B"), CharacterRef(name="C")]
        result = await run_character_gate(chars)
        assert "3" in result.message


# ═════════════════════════════════════════════════════════════════════════════
# run_plot_gate (EG2)
# ═════════════════════════════════════════════════════════════════════════════


class TestRunPlotGate:
    def _make_scene_list(self, n_scenes: int = 3):
        from server.content.base import SceneList, SceneSpec

        scenes = [
            SceneSpec(order=i, prompt=f"Scene {i}", duration=8.0)
            for i in range(n_scenes)
        ]
        return SceneList(project_id="test_proj", scenes=scenes)

    @pytest.mark.asyncio
    async def test_returns_eg2_result(self):
        from server.content.adapters.epub_novel.quality_gates import run_plot_gate

        result = await run_plot_gate(self._make_scene_list())
        assert result.gate_id == "EG2"

    @pytest.mark.asyncio
    async def test_status_is_checking(self):
        from server.content.adapters.epub_novel.quality_gates import run_plot_gate

        result = await run_plot_gate(self._make_scene_list())
        assert result.status == "checking"

    @pytest.mark.asyncio
    async def test_payload_contains_scene_count(self):
        from server.content.adapters.epub_novel.quality_gates import run_plot_gate

        result = await run_plot_gate(self._make_scene_list(5))
        assert result.payload["scene_count"] == 5

    @pytest.mark.asyncio
    async def test_payload_contains_total_duration(self):
        from server.content.adapters.epub_novel.quality_gates import run_plot_gate

        result = await run_plot_gate(self._make_scene_list(3))
        assert result.payload["total_duration_sec"] == pytest.approx(24.0)

    @pytest.mark.asyncio
    async def test_message_contains_scene_count(self):
        from server.content.adapters.epub_novel.quality_gates import run_plot_gate

        result = await run_plot_gate(self._make_scene_list(4))
        assert "4" in result.message


# ═════════════════════════════════════════════════════════════════════════════
# run_style_gate (EG3)
# ═════════════════════════════════════════════════════════════════════════════


class TestRunStyleGate:
    @pytest.mark.asyncio
    async def test_returns_eg3_result(self):
        from server.content.adapters.epub_novel.quality_gates import run_style_gate

        result = await run_style_gate({"skill_name": "kdrama-romance"})
        assert result.gate_id == "EG3"

    @pytest.mark.asyncio
    async def test_status_is_checking(self):
        from server.content.adapters.epub_novel.quality_gates import run_style_gate

        result = await run_style_gate({"skill_name": "kdrama-romance"})
        assert result.status == "checking"

    @pytest.mark.asyncio
    async def test_payload_is_style_info(self):
        from server.content.adapters.epub_novel.quality_gates import run_style_gate

        style = {"skill_name": "kdrama-romance", "tier": "direct"}
        result = await run_style_gate(style)
        assert result.payload == style

    @pytest.mark.asyncio
    async def test_message_contains_skill_name(self):
        from server.content.adapters.epub_novel.quality_gates import run_style_gate

        result = await run_style_gate({"skill_name": "kdrama-romance"})
        assert "kdrama-romance" in result.message


# ═════════════════════════════════════════════════════════════════════════════
# DB gate creation (EG1/EG2/EG3 records)
# ═════════════════════════════════════════════════════════════════════════════


class TestEpubGateDbRecords:
    def test_create_character_gate_record(self, session, project):
        from server.pipeline.gates.epub_checkpoints import (
            check_epub_gate_status,
            create_epub_character_gate,
        )

        create_epub_character_gate(session, project_id=project.id)
        assert check_epub_gate_status(session, "EG1", project.id) == "checking"

    def test_create_plot_gate_record(self, session, project):
        from server.pipeline.gates.epub_checkpoints import (
            check_epub_gate_status,
            create_epub_plot_gate,
        )

        create_epub_plot_gate(session, project_id=project.id)
        assert check_epub_gate_status(session, "EG2", project.id) == "checking"

    def test_create_style_gate_record(self, session, project):
        from server.pipeline.gates.epub_checkpoints import (
            check_epub_gate_status,
            create_epub_style_gate,
        )

        create_epub_style_gate(session, project_id=project.id)
        assert check_epub_gate_status(session, "EG3", project.id) == "checking"

    def test_approve_character_gate(self, session, project):
        from server.pipeline.gates.epub_checkpoints import (
            approve_epub_gate,
            check_epub_gate_status,
            create_epub_character_gate,
        )

        create_epub_character_gate(session, project_id=project.id)
        approve_epub_gate(session, "EG1", project.id)
        assert check_epub_gate_status(session, "EG1", project.id) == "passed"

    def test_override_plot_gate(self, session, project):
        from server.pipeline.gates.epub_checkpoints import (
            check_epub_gate_status,
            create_epub_plot_gate,
            override_epub_gate,
        )

        create_epub_plot_gate(session, project_id=project.id)
        override_epub_gate(session, "EG2", project.id)
        assert check_epub_gate_status(session, "EG2", project.id) == "overridden"

    def test_gate_not_found_returns_not_found(self, session, project):
        from server.pipeline.gates.epub_checkpoints import check_epub_gate_status

        assert check_epub_gate_status(session, "EG3", project.id) == "not_found"

    def test_approve_nonexistent_gate_raises(self, session, project):
        from server.pipeline.gates.epub_checkpoints import approve_epub_gate

        with pytest.raises(ValueError):
            approve_epub_gate(session, "EG1", project.id)

    def test_override_nonexistent_gate_raises(self, session, project):
        from server.pipeline.gates.epub_checkpoints import override_epub_gate

        with pytest.raises(ValueError):
            override_epub_gate(session, "EG2", project.id)

    def test_gate_has_sla_deadline(self, session, project):
        from datetime import datetime, timezone

        from server.pipeline.gates.epub_checkpoints import create_epub_character_gate

        gate = create_epub_character_gate(session, project_id=project.id, timeout_hours=12)
        assert gate.expired_at is not None
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        assert gate.expired_at > now

    @pytest.mark.asyncio
    async def test_run_character_gate_creates_db_record(self, session, project):
        """run_character_gate with session+project_id creates EG1 record."""
        from server.content.adapters.epub_novel.quality_gates import run_character_gate
        from server.content.character_dedup import CharacterRef
        from server.pipeline.gates.epub_checkpoints import check_epub_gate_status

        chars = [CharacterRef(name="Ji-ho")]
        await run_character_gate(chars, project_id=project.id, session=session)
        assert check_epub_gate_status(session, "EG1", project.id) == "checking"


# ═════════════════════════════════════════════════════════════════════════════
# Adapter skill restriction
# ═════════════════════════════════════════════════════════════════════════════


class TestAdapterSkillRestriction:
    def _adapter(self):
        from server.content.adapters.epub_novel.adapter import EpubNovelAdapter

        return EpubNovelAdapter()

    def _input(self, epub_path: Path, skill_name: str | None = "kdrama-romance", options: dict | None = None):
        from server.content.base import AdapterInput

        return AdapterInput(
            source_type="epub_novel",
            raw_content=str(epub_path),
            skill_name=skill_name,
            options=options or {},
        )

    @pytest.mark.asyncio
    async def test_wrong_skill_raises_adapter_error(self):
        from server.content.base import AdapterError

        epub_path = _make_epub()
        try:
            adapter = self._adapter()
            with pytest.raises(AdapterError) as exc_info:
                await adapter.adapt(self._input(epub_path, skill_name="ecommerce-fashion"))
            assert exc_info.value.code == "ADAPTER_SKILL_RESTRICTED"
        finally:
            epub_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_none_skill_raises_adapter_error(self):
        from server.content.base import AdapterError

        epub_path = _make_epub()
        try:
            adapter = self._adapter()
            with pytest.raises(AdapterError) as exc_info:
                await adapter.adapt(self._input(epub_path, skill_name=None))
            assert exc_info.value.code == "ADAPTER_SKILL_RESTRICTED"
        finally:
            epub_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_kdrama_romance_skill_succeeds(self):
        from server.content.base import SceneList

        epub_path = _make_epub()
        try:
            adapter = self._adapter()
            result = await adapter.adapt(self._input(epub_path, skill_name="kdrama-romance"))
            assert isinstance(result, SceneList)
        finally:
            epub_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_error_details_contain_requested_skill(self):
        from server.content.base import AdapterError

        epub_path = _make_epub()
        try:
            adapter = self._adapter()
            with pytest.raises(AdapterError) as exc_info:
                await adapter.adapt(self._input(epub_path, skill_name="narrative-script"))
            assert exc_info.value.details["requested_skill"] == "narrative-script"
        finally:
            epub_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_error_details_contain_allowed_skill(self):
        from server.content.base import AdapterError

        epub_path = _make_epub()
        try:
            adapter = self._adapter()
            with pytest.raises(AdapterError) as exc_info:
                await adapter.adapt(self._input(epub_path, skill_name="wrong"))
            assert exc_info.value.details["allowed_skill"] == "kdrama-romance"
        finally:
            epub_path.unlink(missing_ok=True)


# ═════════════════════════════════════════════════════════════════════════════
# Adapter end-to-end: gates run during adapt()
# ═════════════════════════════════════════════════════════════════════════════


class TestAdapterGateIntegration:
    def _adapter(self):
        from server.content.adapters.epub_novel.adapter import EpubNovelAdapter

        return EpubNovelAdapter()

    def _input(self, epub_path: Path, options: dict | None = None):
        from server.content.base import AdapterInput

        return AdapterInput(
            source_type="epub_novel",
            raw_content=str(epub_path),
            skill_name="kdrama-romance",
            options=options or {},
        )

    @pytest.mark.asyncio
    async def test_tier1_adapt_returns_scene_list(self):
        from server.content.base import SceneList

        epub_path = _make_epub(chapters=[
            ("c1.xhtml", "Ch1", "<h1>Ch1</h1><p>Content for chapter one.</p>"),
        ])
        try:
            adapter = self._adapter()
            result = await adapter.adapt(self._input(epub_path, {"tier": "direct"}))
            assert isinstance(result, SceneList)
        finally:
            epub_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_tier3_adapt_returns_scene_list(self):
        from server.content.base import SceneList

        chapters = [
            (f"c{i}.xhtml", f"Ch{i}", f"<h1>Ch{i}</h1><p>Content {i}.</p>")
            for i in range(4)
        ]
        epub_path = _make_epub(chapters=chapters)
        try:
            adapter = self._adapter()
            result = await adapter.adapt(
                self._input(epub_path, {"chapter_start": 0, "chapter_end": 2})
            )
            assert isinstance(result, SceneList)
        finally:
            epub_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_tier2_adapt_returns_episode_list(self):
        from server.content.adapters.epub_novel.tiers import EpisodeList

        chapters = [
            (f"c{i}.xhtml", f"Ch{i}", f"<h1>Ch{i}</h1><p>Content {i}.</p>")
            for i in range(3)
        ]
        epub_path = _make_epub(chapters=chapters)
        try:
            adapter = self._adapter()
            result = await adapter.adapt(
                self._input(epub_path, {"tier": "episode", "episode_max_words": 5})
            )
            assert isinstance(result, EpisodeList)
        finally:
            epub_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_skill_restriction_checked_before_parse(self):
        """Skill restriction should be checked even if EPUB is valid."""
        from server.content.base import AdapterError, AdapterInput

        epub_path = _make_epub()
        try:
            adapter = self._adapter()
            inp = AdapterInput(
                source_type="epub_novel",
                raw_content=str(epub_path),
                skill_name="blog-article",  # wrong skill
            )
            with pytest.raises(AdapterError) as exc_info:
                await adapter.adapt(inp)
            assert exc_info.value.code == "ADAPTER_SKILL_RESTRICTED"
        finally:
            epub_path.unlink(missing_ok=True)
