"""Checkpoint context and approval comparison for script-created projects."""

import json

from fastapi import HTTPException
from sqlmodel import Session, select

from server.db.models.scene import Scene
from server.db.models.project import Project
from server.db.models.script_revision import ScriptRevision
from server.text.schemas import Brief, SCHEMAS, Script, strict_schema
from server.text.prompts import COMMON, STAGES, PROMPT_VERSION
from server.text.quality import inspect_script


def get_revision(session: Session, revision_id: int) -> ScriptRevision:
    row = session.get(ScriptRevision, revision_id)
    if row is None:
        raise HTTPException(404, "Không tìm thấy phiên bản kịch bản.")
    return row


def ancestry(session: Session, row: ScriptRevision) -> list[ScriptRevision]:
    chain = [row]
    while chain[-1].parent_id is not None:
        if len(chain) >= 100:
            raise HTTPException(422, "Lịch sử quá dài; tạo brief mới và chuyển phần bối cảnh cần thiết.")
        chain.append(get_revision(session, chain[-1].parent_id))
    return list(reversed(chain))


def build_prompt(session: Session, parent: ScriptRevision, stage: str) -> str:
    allowed = {"outline": {"brief"}, "script": {"outline"},
               "review": {"script", "manual", "revise"}, "revise": {"review"}}
    if parent.status != "succeeded" or parent.stage not in allowed.get(stage, set()):
        raise HTTPException(409, "Bước trước chưa hoàn tất hoặc không đúng thứ tự.")
    chain = ancestry(session, parent)
    if stage == "revise" and any(row.stage == "revise" for row in chain):
        raise HTTPException(409, "Đã dùng một vòng AI sửa. Hãy sửa thủ công hoặc duyệt bản hiện tại.")
    # Supply the current manuscript, not every obsolete draft (which can contradict it).
    context = {}
    for item in chain:
        key = "script" if item.stage in ("script", "manual", "revise") else item.stage
        context[key] = json.loads(item.content_json)
    brief = Brief.model_validate(context["brief"])
    if "script" in context:
        context["preflight"] = inspect_script(Script.model_validate(context["script"]), brief)
    if stage != "revise":
        context.pop("review", None)
    unit = "Vietnamese space-delimited syllables" if brief.language == "vi" else "words"
    budget = (f"Target {brief.target_seconds}s; narration planning pace {brief.narration_wpm} {unit}/minute. "
              f"Leave at least 0.35 seconds of breathing room in each spoken shot. "
              f"An 8-second shot has about {int((8 - 0.35) * brief.narration_wpm / 60)} spoken {unit} at this pace. "
              "Do not fill silent beats merely to reach a word count. Timing is an estimate until TTS.\n")
    instructions = COMMON + STAGES[stage]
    if brief.language == "vi":
        instructions = instructions.replace("English", "Vietnamese")
    return (f"Prompt version: {PROMPT_VERSION}\n" + instructions + budget
            + "\nContext:\n" + json.dumps(context, ensure_ascii=False)
            + "\nOutput schema:\n" + json.dumps(strict_schema(SCHEMAS[stage])))


def quality_report(session: Session, row: ScriptRevision) -> dict:
    chain = ancestry(session, row)
    brief_row = next((item for item in chain if item.stage == "brief"), None)
    if brief_row is None:
        raise HTTPException(409, "Phiên bản thiếu brief gốc; tạo brief và nhập lại kịch bản.")
    return inspect_script(Script.model_validate_json(row.content_json), Brief.model_validate_json(brief_row.content_json))


def assert_project_approved(session: Session, project_id: int) -> None:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "Dự án không còn tồn tại.")
    revision = session.exec(select(ScriptRevision).where(
        ScriptRevision.project_short_id == project.short_id)).first()
    if revision is None:
        return  # Existing projects keep their existing workflow.
    from server.text.approval import require_approval
    require_approval(session, revision)
    script = Script.model_validate_json(revision.content_json)
    scenes = session.exec(select(Scene).where(Scene.project_id == project_id).order_by(Scene.order)).all()
    expected = [(item.visual_prompt, item.narration, item.duration, item.location_hint) for item in script.scenes]
    actual = [(item.prompt, item.narration, item.duration, item.location_hint) for item in scenes]
    if not revision.approved or expected != actual:
        raise HTTPException(409, "Cảnh đã khác kịch bản được duyệt. Lưu bản sửa trong Kịch bản, duyệt và tạo dự án mới.")
