"""Vietnamese timing counts written syllables, while English keeps its word limit."""

import pytest
from pydantic import ValidationError
from sqlmodel import Session

from server.api.routes.scripts import ManualInput
from server.db.models.script_revision import ScriptRevision
from server.tests.test_script_studio import brief_data, rid, script_data
from server.tests.test_script_studio import client as client
from server.text.schemas import Brief
from server.text.workflow import build_prompt


@pytest.mark.parametrize("language,pace", [("en", 99), ("en", 181), ("vi", 99), ("vi", 301)])
def test_invalid_language_planning_pace_rejected(language, pace):
    with pytest.raises(ValidationError):
        Brief.model_validate(brief_data(language=language, narration_wpm=pace))
    with pytest.raises(ValidationError):
        ManualInput.model_validate({"request_id": rid(), "content": script_data(),
                                    "language": language, "narration_wpm": pace})


@pytest.mark.parametrize("language,pace", [("en", 100), ("en", 180), ("vi", 100), ("vi", 300)])
def test_language_planning_pace_boundaries(language, pace):
    assert Brief.model_validate(brief_data(language=language, narration_wpm=pace)).narration_wpm == pace


def test_english_default_is_preserved():
    assert Brief.model_validate(brief_data()).narration_wpm == 135


def test_vietnamese_240_manual_roundtrip_has_realistic_scene_estimate(client):
    content = script_data()
    content["scenes"] = content["scenes"][:1]
    content["scenes"][0]["narration"] = (
        "Hôm nay, thử đặt điện thoại xuống và chọn một việc nhỏ. "
        "Học thêm, nghỉ ngơi cho đủ, hoặc hoàn thành điều mình cứ trì hoãn."
    )
    response = client.post("/api/scripts/manual", json={"request_id": rid(), "content": content,
                           "language": "vi", "narration_wpm": 240})
    assert response.status_code == 201, response.text
    detail = client.get(f"/api/scripts/{response.json()['id']}").json()
    assert detail["brief"]["narration_wpm"] == 240
    report = detail["quality"]
    assert report["narration_unit"] == "syllables"
    assert report["words"] == 26
    assert report["scenes"][0]["estimated_speech_seconds"] == 6.8
    assert report["ready"]
    assert not any(issue["code"] in {"speech_tight", "speech_overflow"} for issue in report["issues"])


@pytest.mark.parametrize("language,pace", [("en", 240), ("vi", 301)])
def test_api_invalid_planning_pace_returns_validation_error(client, language, pace):
    assert client.post("/api/scripts/manual", json={"request_id": rid(), "content": script_data(),
                       "language": language, "narration_wpm": pace}).status_code == 422


def test_vietnamese_prompt_explains_syllable_budget(client):
    response = client.post("/api/scripts/brief", json={"request_id": rid(), "content":
                           brief_data(language="vi", narration_wpm=240)})
    assert response.status_code == 201, response.text
    with Session(client.test_engine) as session:
        prompt = build_prompt(session, session.get(ScriptRevision, response.json()["id"]), "outline")
    assert "240 Vietnamese space-delimited syllables/minute" in prompt
    assert "about 30 spoken Vietnamese space-delimited syllables" in prompt
