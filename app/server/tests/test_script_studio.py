"""Offline regression tests: isolated SQLite, fake provider, no inference or user DB."""

import importlib
import json
import uuid

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlmodel import Session, SQLModel, create_engine, select

from server.api.routes import scripts
from server.db.models.project import Project
from server.db.models.scene import Scene
from server.db.models.script_approval import ScriptApproval
from server.db.models.script_revision import ScriptRevision
from server.text.approval import CHECKLIST
from server.text.openrouter import OpenRouter, TextProviderError, free_structured_model
from server.text.quality import inspect_script
from server.text.schemas import Brief, Review, Script, strict_schema
from server.text.workflow import assert_project_approved, build_prompt


def brief_data(**kwargs):
    return {"title": "The clock", "idea": "A clock returns a stolen hour.", "series_bible": "Mara wears a blue coat.", "target_seconds": 32, **kwargs}


def script_data(**kwargs):
    return {"title": "The clock", "continuity_notes": "Mara keeps her blue coat.", "scenes": [
        {"visual_prompt": f"Close-up of Mara in a blue coat turning clock number {n} inside the dim shop, cold light.",
         "narration": f"The clock held a secret from night {n}.", "duration": 8, "location_hint": "indoor",
         "story_beat": ["hook", "setup", "reveal", "payoff"][n], "purpose": f"Discovery {n} changes Mara's next decision."}
        for n in range(4)], **kwargs}


def rid():
    return str(uuid.uuid4())


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'scripts.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    app = FastAPI()
    app.include_router(scripts.router)
    def session():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[scripts.get_session] = session
    def forbidden(*args, **kwargs):
        raise AssertionError("Tests must explicitly stub inference")
    monkeypatch.setattr(scripts.provider, "generate_structured", forbidden)
    with TestClient(app, headers={"X-AIFlow-Client": "1"}) as browser:
        browser.test_engine = engine
        yield browser
    engine.dispose()


def create_script(client, content=None):
    root = client.post("/api/scripts/brief", json={"request_id": rid(), "content": brief_data()})
    assert root.status_code == 201, root.text
    response = client.post("/api/scripts/import", json={"request_id": rid(), "parent_id": root.json()["id"], "content": content or script_data()})
    assert response.status_code == 201, response.text
    return root.json(), response.json()


def approve(client, revision_id, **kwargs):
    return client.post(f"/api/scripts/{revision_id}/approve", json={"checklist": sorted(CHECKLIST), "acknowledge_warnings": True, **kwargs})


def test_legacy_formats_remain_readable():
    data = script_data()
    for scene in data["scenes"]:
        scene.pop("story_beat")
        scene.pop("purpose")
    assert Script.model_validate(data).scenes[0].story_beat == "unspecified"
    assert Brief.model_validate(brief_data()).narration_wpm == 135
    assert Review.model_validate({"summary": "Legacy", "issues": [], "recommendation": "approve"}).findings == []


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 30])
def test_invalid_durations(value):
    data = script_data()
    data["scenes"][0]["duration"] = value
    with pytest.raises(ValidationError):
        Script.model_validate(data)


def test_strict_remote_schema_requires_defaulted_fields():
    schema = strict_schema(Script)
    scene = schema["$defs"]["ScriptScene"]
    assert set(scene["required"]) == set(scene["properties"])
    assert "default" not in scene["properties"]["story_beat"]
    assert scene["additionalProperties"] is False


def test_silence_is_intentional_and_valid():
    data = script_data()
    data["scenes"][1]["narration"] = ""
    report = inspect_script(Script.model_validate(data), Brief.model_validate(brief_data()))
    assert report["ready"]
    assert report["scenes"][1]["estimated_speech_seconds"] == 0


def test_quality_rejects_overfilled_and_wrong_length():
    data = script_data()
    data["scenes"][0]["narration"] = "word " * 50
    report = inspect_script(Script.model_validate(data), Brief.model_validate(brief_data(target_seconds=240)))
    assert not report["ready"]
    assert {i["code"] for i in report["issues"]} >= {"target_duration", "speech_overflow"}


def test_quality_reports_duplicates_and_exact_scene_numbers():
    data = script_data()
    data["scenes"][2]["narration"] = data["scenes"][0]["narration"]
    report = inspect_script(Script.model_validate(data), Brief.model_validate(brief_data()))
    assert report["ready"]
    assert any(i["code"] == "repeated_narration" and i["scene"] == 3 for i in report["issues"])
    assert report["scenes"][-1]["start"] == 24


def test_full_manual_approval_and_project_roundtrip(client):
    _, draft = create_script(client)
    path = f"/api/scripts/{draft['id']}"
    assert client.get(path).json()["quality"]["ready"]
    assert client.post(path + "/project", json={}).status_code == 409
    assert approve(client, draft["id"]).status_code == 200
    detail = client.get(path).json()
    assert detail["editorially_approved"]
    first = client.post(path + "/project", json={"aspect": "16:9"})
    assert first.status_code == 200, first.text
    second = client.post(path + "/project", json={"aspect": "9:16"})
    assert first.json() == second.json()
    with Session(client.test_engine) as db:
        assert len(db.exec(select(Project)).all()) == 1
        assert len(db.exec(select(Scene)).all()) == 4
        assert db.get(ScriptApproval, draft["id"]).content_hash
        assert_project_approved(db, first.json()["id"])
        scene = db.exec(select(Scene)).first()
        scene.prompt = "Changed after approval"
        db.add(scene)
        db.commit()
        with pytest.raises(HTTPException, match="409"):
            assert_project_approved(db, first.json()["id"])


def test_checklist_and_warnings_are_required(client):
    data = script_data()
    data["scenes"][0]["purpose"] = ""
    _, draft = create_script(client, data)
    assert approve(client, draft["id"], checklist=[]).status_code == 422
    assert approve(client, draft["id"], acknowledge_warnings=False).status_code == 422
    assert approve(client, draft["id"]).status_code == 200


def test_errors_cannot_be_approved(client):
    data = script_data()
    data["scenes"][0]["narration"] = "too many words " * 30
    _, draft = create_script(client, data)
    assert approve(client, draft["id"]).status_code == 409


def test_invalid_review_validation_returns_422_not_500(client):
    _, draft = create_script(client)
    response = client.post("/api/scripts/import", json={"request_id": rid(), "parent_id": draft["id"], "stage": "review",
        "content": {"summary": "Incomplete review", "issues": [], "recommendation": "approve", "findings": [
            {"criterion": "hook", "verdict": "pass", "scene_numbers": [1], "evidence": "A clock appears.", "suggested_fix": ""}]}})
    assert response.status_code == 422


def test_tampered_checkpoint_invalidates_approval(client):
    _, draft = create_script(client)
    assert approve(client, draft["id"]).status_code == 200
    with Session(client.test_engine) as db:
        row = db.get(ScriptRevision, draft["id"])
        row.content_json = json.dumps(script_data(title="Tampered"))
        db.add(row)
        db.commit()
    assert not client.get(f"/api/scripts/{draft['id']}").json()["editorially_approved"]
    assert client.post(f"/api/scripts/{draft['id']}/project", json={}).status_code == 409


def test_late_result_cannot_overwrite_abandoned_checkpoint(client, monkeypatch):
    root, _ = create_script(client)
    def late(*args):
        with Session(client.test_engine) as db:
            row = db.exec(select(ScriptRevision).where(ScriptRevision.status == "running")).one()
            row.status = "failed"
            row.error = "Abandoned"
            db.add(row)
            db.commit()
        return {"title": "Too late", "beats": ["A", "B", "C"], "continuity_notes": ""}, "x:free", None
    monkeypatch.setattr(scripts.provider, "generate_structured", late)
    result = client.post("/api/scripts/step", json={"request_id": rid(), "parent_id": root["id"], "stage": "outline", "model": "x:free"})
    assert result.json()["status"] == "failed" and result.json()["error"] == "Abandoned"


def test_old_boolean_approval_requires_editorial_record(client):
    _, draft = create_script(client)
    with Session(client.test_engine) as db:
        row = db.get(ScriptRevision, draft["id"])
        row.approved = True
        db.add(row)
        db.commit()
    assert not client.get(f"/api/scripts/{draft['id']}").json()["editorially_approved"]
    assert client.post(f"/api/scripts/{draft['id']}/project", json={}).status_code == 409


def test_saved_revision_does_not_inherit_approval(client):
    _, draft = create_script(client)
    approve(client, draft["id"])
    edited = client.post("/api/scripts/import", json={"request_id": rid(), "parent_id": draft["id"], "content": script_data(title="New title")})
    assert edited.status_code == 201
    assert not edited.json()["approved"]
    assert client.get(f"/api/scripts/{draft['id']}").json()["approved"]


def test_import_idempotency_and_collision(client):
    payload = {"request_id": rid(), "content": brief_data()}
    first = client.post("/api/scripts/brief", json=payload)
    assert first.json()["id"] == client.post("/api/scripts/brief", json=payload).json()["id"]
    payload["content"]["title"] = "Different request"
    assert client.post("/api/scripts/brief", json=payload).status_code == 409


def test_generation_idempotent_failure_and_no_replay(client, monkeypatch):
    root, _ = create_script(client)
    calls = []
    def fake(*args):
        calls.append(args)
        raise TextProviderError("Quota exhausted")
    monkeypatch.setattr(scripts.provider, "generate_structured", fake)
    payload = {"request_id": rid(), "parent_id": root["id"], "stage": "outline", "model": "test/free:free"}
    first = client.post("/api/scripts/step", json=payload)
    assert first.json()["status"] == "failed"
    assert client.post("/api/scripts/step", json=payload).json()["id"] == first.json()["id"]
    assert len(calls) == 1


def test_provider_unexpected_exception_is_recorded_without_secret(client, monkeypatch):
    root, _ = create_script(client)
    def fake(*args):
        raise RuntimeError("secret-token-must-not-leak")
    monkeypatch.setattr(scripts.provider, "generate_structured", fake)
    result = client.post("/api/scripts/step", json={"request_id": rid(), "parent_id": root["id"], "stage": "outline", "model": "test/free:free"})
    assert result.json()["status"] == "failed"
    assert "secret-token" not in result.text


def test_complete_ai_workflow_with_stubbed_inference(client, monkeypatch):
    root, _ = create_script(client)
    calls = []
    def fake(prompt, schema, model):
        calls.append(schema.__name__)
        assert "story-editor-2" in prompt and "Output schema" in prompt
        if schema.__name__ == "Outline":
            data = {"title": "The clock", "beats": ["Hook", "Escalation", "Payoff"], "continuity_notes": "Blue coat"}
        elif schema.__name__ == "Review":
            data = {"summary": "Review", "issues": [], "recommendation": "approve", "findings": [
                {"criterion": criterion, "verdict": "uncertain" if criterion == "originality" else "pass",
                 "scene_numbers": [1], "evidence": "Scene 1 establishes the clock.", "suggested_fix": ""}
                for criterion in sorted({"hook", "causality", "continuity", "payoff", "speakability", "visual_feasibility", "originality"})]}
        else:
            data = script_data()
        return schema.model_validate(data).model_dump(), model, {"total_tokens": 100, "cost": 0}
    monkeypatch.setattr(scripts.provider, "generate_structured", fake)
    parent = root
    for stage in ["outline", "script", "review", "revise", "review"]:
        response = client.post("/api/scripts/step", json={"request_id": rid(), "parent_id": parent["id"], "stage": stage, "model": "stub:free"})
        assert response.status_code == 200, response.text
        parent = response.json()
        assert parent["status"] == "succeeded", parent
    assert len(calls) == 5
    blocked = client.post("/api/scripts/step", json={"request_id": rid(), "parent_id": parent["id"], "stage": "revise", "model": "stub:free"})
    assert blocked.status_code == 409 and len(calls) == 5


def test_prompt_uses_latest_draft_only_and_review_is_bounded(client):
    _, draft = create_script(client)
    newer = client.post("/api/scripts/import", json={"request_id": rid(), "parent_id": draft["id"], "content": script_data(title="Latest manuscript")}).json()
    with Session(client.test_engine) as db:
        prompt = build_prompt(db, db.get(ScriptRevision, newer["id"]), "review")
        context = json.loads(prompt.split("\nContext:\n")[1].split("\nOutput schema:\n")[0])
        assert context["script"]["title"] == "Latest manuscript"
        assert list(context).count("script") == 1
        assert "preflight" in context and "story-editor-2" in prompt
    review = {"summary": "Needs work", "issues": ["Tight timing"], "recommendation": "revise"}
    r = client.post("/api/scripts/import", json={"request_id": rid(), "parent_id": newer["id"], "stage": "review", "content": review}).json()
    revised = client.post("/api/scripts/import", json={"request_id": rid(), "parent_id": r["id"], "stage": "revise", "content": script_data()}).json()
    r2 = client.post("/api/scripts/import", json={"request_id": rid(), "parent_id": revised["id"], "stage": "review", "content": review}).json()
    assert client.get(f"/api/scripts/{r2['id']}").json()["can_revise"] is False
    assert client.get(f"/api/scripts/{r2['id']}/prompt/revise").status_code == 409


@pytest.mark.parametrize("bad", [None, {}, {"id": None}, {"id": "paid/model", "pricing": {"prompt": "0", "completion": "0"}},
    {"id": "x:free", "supported_parameters": ["structured_outputs"], "pricing": {"prompt": "0", "completion": "0.01"}},
    {"id": "x:free", "supported_parameters": ["structured_outputs"], "pricing": {"prompt": "0", "completion": "0", "request": "1"}},
    {"id": "x:free", "supported_parameters": ["structured_outputs"], "pricing": {"prompt": "NaN", "completion": "0"}}])
def test_free_filter_fails_closed(bad):
    assert not free_structured_model(bad)


def test_openrouter_request_routing_and_json_validation(monkeypatch):
    provider = OpenRouter()
    provider.key = "test-key"
    monkeypatch.setattr(provider, "models", lambda: [{"id": "x:free"}])
    calls = []
    real_client = httpx.Client
    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        assert body["provider"]["allow_fallbacks"] is False
        assert body["provider"]["require_parameters"] is True
        assert all(value == 0 for value in body["provider"]["max_price"].values())
        return httpx.Response(200, json={"model": "actual/free", "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(script_data())}}]})
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs))
    content, model, usage = provider.generate_structured("prompt", Script, "x:free")
    assert len(content["scenes"]) == 4 and model == "actual/free" and usage is None and len(calls) == 1


@pytest.mark.parametrize("status,payload", [(429, {}), (200, {"choices": [None]}),
    (200, {"choices": [{"finish_reason": "length"}]}), (200, {"choices": []})])
def test_openrouter_failure_never_retries(monkeypatch, status, payload):
    provider = OpenRouter()
    provider.key = "test-key"
    monkeypatch.setattr(provider, "models", lambda: [{"id": "x:free"}])
    real_client = httpx.Client
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, json=payload)
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs))
    with pytest.raises(TextProviderError):
        provider.generate_structured("prompt", Script, "x:free")
    assert len(calls) == 1


def test_additive_migration_idempotent(tmp_path):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    migration = importlib.import_module("server.db.migrations.versions.0005_script_approval")
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()
        assert "scriptapproval" in inspect(connection).get_table_names()
    engine.dispose()
