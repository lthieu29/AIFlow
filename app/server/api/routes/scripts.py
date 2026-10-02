"""Explicit script steps, immutable results and human approval before project creation."""

import json
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from server.api.routes.audio import local_client
from server.api.routes.projects import get_session
from server.db.models.project import Project
from server.db.models.scene import Scene
from server.db.models.script_revision import ScriptRevision
from server.db.models.script_approval import ScriptApproval
from server.text.approval import CHECKLIST, content_hash, require_approval
from server.text.openrouter import TextProviderError, provider
from server.text.providers import PROVIDERS, gemini
from server.text import codex_tmux
from server.text.schemas import Brief, SCHEMAS, Script
from server.text.workflow import ancestry, build_prompt, get_revision, quality_report

router = APIRouter(prefix="/api/scripts", tags=["scripts"], dependencies=[Depends(local_client)])


class ConnectionInput(BaseModel):
    key: SecretStr = Field(max_length=512)
    provider: Literal["openrouter", "gemini"] = "openrouter"
    billing_confirmed: bool = False


class BriefInput(BaseModel):
    request_id: uuid.UUID
    content: Brief
    series_id: int | None = None
    series_version: int | None = None


class StepInput(BaseModel):
    request_id: uuid.UUID
    parent_id: int
    stage: Literal["outline", "script", "review", "revise"]
    model: str = Field(min_length=1, max_length=200)
    provider: Literal["openrouter", "gemini", "codex_cli"] = "openrouter"


class ImportInput(BaseModel):
    request_id: uuid.UUID
    parent_id: int
    stage: Literal["manual", "outline", "script", "review", "revise"] = "manual"
    content: dict


class ProjectInput(BaseModel):
    aspect: Literal["16:9", "9:16", "1:1"] = "16:9"


class ApprovalInput(BaseModel):
    checklist: list[str] = Field(max_length=6)
    acknowledge_warnings: bool = False
    notes: str = Field(default="", max_length=3000)


def public(row: ScriptRevision, include_content: bool = True) -> dict:
    return {"id": row.id, "parent_id": row.parent_id, "title": row.title, "stage": row.stage,
            "status": row.status, "content": json.loads(row.content_json) if include_content else {}, "provider": row.provider,
            "model": row.model, "usage": json.loads(row.usage_json), "error": row.error,
            "approved": row.approved, "project_id": row.project_id, "created_at": row.created_at.isoformat()}


def persist(session: Session, row: ScriptRevision) -> ScriptRevision:
    identity = (row.parent_id, row.stage, row.content_json)
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.exec(select(ScriptRevision).where(ScriptRevision.request_id == row.request_id)).first()
        if existing is None:
            raise
        if (existing.parent_id, existing.stage, existing.content_json) != identity:
            raise HTTPException(409, "Request ID đã dùng cho nội dung khác; tải lại kết quả trước khi gửi mới.")
        return existing
    session.refresh(row)
    return row


@router.get("/connection")
def connection_status():
    codex = codex_tmux.public()
    return {"configured": bool(provider.key), "free_only": True,
            "codex_enabled": codex["ready"] and codex["confirmed"],
            "codex_reason": codex["message"], "codex": codex,
            "gemini_enabled": bool(gemini.key) and gemini.billing_confirmed}


class CodexConnectionInput(BaseModel):
    distro: str = Field(default="Ubuntu", pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}$")
    confirmed: bool = False
    timeout_seconds: int = Field(default=1200, ge=120, le=3600)


@router.put("/codex/connection")
def configure_codex(body: CodexConnectionInput):
    return codex_tmux.configure(body.distro, body.confirmed, body.timeout_seconds)


@router.post("/{revision_id}/codex/sync")
def sync_codex(revision_id: int, session: Session = Depends(get_session)):
    return public(codex_tmux.sync(session, get_revision(session, revision_id)))


@router.post("/{revision_id}/codex/cancel")
def cancel_codex(revision_id: int, session: Session = Depends(get_session)):
    return public(codex_tmux.sync(session, get_revision(session, revision_id), cancel=True))


@router.put("/connection")
def save_connection(body: ConnectionInput):
    selected = PROVIDERS[body.provider]
    selected.key = body.key.get_secret_value().strip()
    if body.provider == "gemini":
        gemini.billing_confirmed = body.billing_confirmed
    return connection_status()


@router.get("/models")
def models():
    try:
        return provider.models()
    except TextProviderError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("")
def list_revisions(session: Session = Depends(get_session)):
    rows = session.exec(select(ScriptRevision).order_by(ScriptRevision.id.desc()).limit(300)).all()
    return [public(row, include_content=False) for row in rows]


@router.get("/{revision_id}")
def revision_detail(revision_id: int, session: Session = Depends(get_session)):
    row = get_revision(session, revision_id)
    result = public(row)
    chain = ancestry(session, row)
    brief = next((item for item in chain if item.stage == "brief"), None)
    result["brief"] = json.loads(brief.content_json) if brief else None
    result["can_revise"] = not any(item.stage == "revise" for item in chain)
    if row.status == "succeeded" and row.stage in ("script", "manual", "revise"):
        result["quality"] = quality_report(session, row)
        approval = session.get(ScriptApproval, row.id)
        result["editorially_approved"] = bool(approval and approval.content_hash == content_hash(row) and row.approved)
        result["approval"] = {"notes": approval.notes, "created_at": approval.created_at.isoformat()} if approval else None
        review = session.exec(select(ScriptRevision).where(ScriptRevision.parent_id == row.id,
            ScriptRevision.stage == "review", ScriptRevision.status == "succeeded").order_by(ScriptRevision.id.desc())).first()
        result["latest_review"] = public(review) if review else None
    return result


@router.post("/brief", status_code=201)
def create_brief(body: BriefInput, session: Session = Depends(get_session)):
    if body.series_id is not None:
        from server.studio.series import create_episode
        return public(create_episode(session, body))
    return public(persist(session, ScriptRevision(request_id=str(body.request_id), title=body.content.title,
                                                  stage="brief", content_json=body.content.model_dump_json())))


@router.get("/{revision_id}/prompt/{stage}")
def export_prompt(revision_id: int, stage: Literal["outline", "script", "review", "revise"],
                  session: Session = Depends(get_session)):
    return {"prompt": build_prompt(session, get_revision(session, revision_id), stage)}


@router.post("/import", status_code=201)
def import_script(body: ImportInput, session: Session = Depends(get_session)):
    parent = get_revision(session, body.parent_id)
    if parent.status != "succeeded":
        raise HTTPException(409, "Chọn một checkpoint đã hoàn tất để lưu bản sửa.")
    if body.stage != "manual":
        build_prompt(session, parent, body.stage)
    from pydantic import ValidationError
    try:
        content = SCHEMAS[body.stage].model_validate(body.content)
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_input=False, include_url=False, include_context=False)) from exc
    if body.stage == "review" and any(
        number < 1 or number > len(Script.model_validate_json(parent.content_json).scenes)
        for finding in content.findings for number in finding.scene_numbers
    ):
        raise HTTPException(422, "Nhận xét tham chiếu cảnh không tồn tại trong kịch bản cha.")
    return public(persist(session, ScriptRevision(request_id=str(body.request_id), parent_id=parent.id,
                  title=getattr(content, "title", parent.title), stage=body.stage,
                  content_json=content.model_dump_json())))


@router.post("/step")
def run_step(body: StepInput, session: Session = Depends(get_session)):
    request_id = str(body.request_id)
    existing = session.exec(select(ScriptRevision).where(ScriptRevision.request_id == request_id)).first()
    if existing:
        if (existing.parent_id != body.parent_id or existing.stage != body.stage
                or existing.provider != body.provider
                or (json.loads(existing.usage_json) or {}).get("requested_model", existing.model) != body.model):
            raise HTTPException(409, "Request ID đã dùng cho bước khác.")
        return public(existing)
    parent = get_revision(session, body.parent_id)
    prompt = build_prompt(session, parent, body.stage)
    if body.provider == "codex_cli":
        return public(codex_tmux.begin(session, body, parent, prompt))
    row = persist(session, ScriptRevision(request_id=request_id, parent_id=parent.id, title=parent.title,
                  stage=body.stage, status="pending", provider=body.provider, model=body.model))
    # Claim once across concurrent HTTP requests. Never replay a running request after restart.
    claimed = session.execute(update(ScriptRevision).where(ScriptRevision.id == row.id,
        ScriptRevision.status == "pending").values(status="running"))
    session.commit()
    session.refresh(row)
    if claimed.rowcount != 1:
        return public(row)
    try:
        content, actual_model, usage = PROVIDERS[body.provider].generate_structured(prompt, SCHEMAS[body.stage], body.model)
        if body.stage == "review":
            findings = content.get("findings", [])
            scene_count = len(Script.model_validate_json(parent.content_json).scenes)
            if len(findings) != 7 or any(n < 1 or n > scene_count for item in findings for n in item["scene_numbers"]):
                raise TextProviderError("Nhận xét thiếu rubric hoặc tham chiếu cảnh không tồn tại. Chưa coi là review hoàn tất.")
        result = {"content_json": json.dumps(content, ensure_ascii=False),
                  "title": content.get("title", parent.title), "model": actual_model,
                  "usage_json": json.dumps({**(usage or {}), "requested_model": body.model}), "status": "succeeded"}
    except TextProviderError as exc:
        result = {"status": "failed", "error": str(exc)}
    except Exception:
        result = {"status": "failed", "error": "Không xử lý được kết quả nhà cung cấp. Bản trước được giữ; không tự retry."}
    session.execute(update(ScriptRevision).where(ScriptRevision.id == row.id,
        ScriptRevision.status == "running").values(**result))
    session.commit()
    session.refresh(row)
    return public(row)


@router.post("/{revision_id}/abandon")
def abandon_step(revision_id: int, session: Session = Depends(get_session)):
    row = get_revision(session, revision_id)
    if row.provider == "codex_cli" and (json.loads(row.usage_json) or {}).get("transport") == "cao-tmux":
        return public(codex_tmux.sync(session, row, cancel=True))
    age = (datetime.now(timezone.utc) - row.created_at.replace(tzinfo=timezone.utc)).total_seconds()
    if age < 180:
        raise HTTPException(409, "Chờ ít nhất 3 phút trước khi đánh dấu tác vụ bị gián đoạn.")
    session.execute(update(ScriptRevision).where(ScriptRevision.id == row.id,
        ScriptRevision.status.in_(["pending", "running"])).values(status="failed",
        error="Tác vụ bị gián đoạn; không tự gọi lại AI. Chọn checkpoint trước để thử lại."))
    session.commit()
    session.refresh(row)
    return public(row)


@router.post("/{revision_id}/approve")
def approve(revision_id: int, body: ApprovalInput, session: Session = Depends(get_session)):
    row = get_revision(session, revision_id)
    if row.stage not in ("script", "revise", "manual") or row.status != "succeeded":
        raise HTTPException(409, "Chỉ duyệt kịch bản hoàn tất.")
    report = quality_report(session, row)
    if not report["ready"]:
        raise HTTPException(409, "Sửa các lỗi thời lượng/lời đọc trong kiểm tra trước sản xuất trước khi duyệt.")
    if set(body.checklist) != CHECKLIST:
        raise HTTPException(422, "Cần xác nhận đủ 6 mục biên tập.")
    warnings = [item for item in report["issues"] if item["severity"] == "warning"]
    if warnings and not body.acknowledge_warnings:
        raise HTTPException(422, "Cần đọc và xác nhận các cảnh báo còn lại.")
    approval = session.get(ScriptApproval, row.id) or ScriptApproval(revision_id=row.id,
        content_hash=content_hash(row), quality_version=report["version"], checklist_json="[]", warnings_json="[]")
    approval.content_hash = content_hash(row)
    approval.quality_version = report["version"]
    approval.checklist_json = json.dumps(sorted(body.checklist))
    approval.warnings_json = json.dumps(warnings, ensure_ascii=False)
    approval.notes = body.notes
    session.add(approval)
    row.approved = True
    session.add(row)
    session.commit()
    return public(row)


@router.post("/{revision_id}/project")
def create_script_project(revision_id: int, body: ProjectInput, session: Session = Depends(get_session)):
    row = get_revision(session, revision_id)
    if not row.approved or row.status != "succeeded":
        raise HTTPException(409, "Duyệt kịch bản trước khi tạo dự án.")
    require_approval(session, row)
    if not quality_report(session, row)["ready"]:
        raise HTTPException(409, "Kịch bản chưa đạt kiểm tra trước sản xuất.")
    # Acquire SQLite's write lock before checking the existing project link.
    session.execute(update(ScriptRevision).where(ScriptRevision.id == row.id).values(approved=True))
    session.refresh(row)
    if row.project_id is not None:
        project = session.get(Project, row.project_id)
        if project is None or project.short_id != row.project_short_id:
            raise HTTPException(409, "Dự án này đã bị xóa; lưu một bản mới để tạo lại.")
        return {"id": project.id, "short_id": project.short_id}
    script = Script.model_validate_json(row.content_json)
    root_brief = Brief.model_validate_json(ancestry(session, row)[0].content_json)
    project = Project(short_id="p_" + uuid.uuid4().hex[:12], title=script.title, aspect=body.aspect,
                      skill="cinematic-thriller", adapter="storyboard_manual", status="ready", language=root_brief.language, kind="video")
    session.add(project)
    session.flush()
    from server.studio.series import apply_episode
    apply_episode(session, row, project)
    for index, item in enumerate(script.scenes):
        session.add(Scene(project_id=project.id, order=index, duration=item.duration,
                          prompt=item.visual_prompt, narration=item.narration, location_hint=item.location_hint))
    row.project_id = project.id
    row.project_short_id = project.short_id
    session.add(row)
    session.commit()
    return {"id": project.id, "short_id": project.short_id}
