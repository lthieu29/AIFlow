import hashlib
import json

from fastapi import HTTPException
from sqlmodel import Session

from server.db.models.script_approval import ScriptApproval
from server.db.models.script_revision import ScriptRevision
from server.text.schemas import Script

CHECKLIST = {"hook_and_promise", "causal_story_and_payoff", "continuity", "read_aloud", "visual_feasibility", "originality"}


def content_hash(row: ScriptRevision) -> str:
    data = Script.model_validate_json(row.content_json).model_dump()
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def require_approval(session: Session, row: ScriptRevision) -> None:
    approval = session.get(ScriptApproval, row.id)
    if not row.approved or approval is None or approval.content_hash != content_hash(row):
        raise HTTPException(409, "Cần duyệt checklist biên tập của phiên bản này trước khi sản xuất.")
