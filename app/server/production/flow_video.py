"""One explicit Veo Lite submission; persisted handles resume polling without replay."""

import asyncio
import json
import re
import traceback
from pathlib import Path

from fastapi import HTTPException
from loguru import logger
from sqlalchemy import update
from sqlmodel import Session

from server.db.models.production import ProductionMedia
from server.db.models.project import Project
from server.db.models.scene import Scene
from server.db.models.studio import StudioOperation
from server.flow.downloader import download_video
from server.flow.sdk import extract_video_operations, get_flow_sdk
from server.production.media import contained, probe, sha256
from server.text.workflow import assert_project_approved

ACTIVE_VIDEOS: set[str] = set()
POLL_INTERVAL = 5
MAX_POLLS = 120


def failure_guidance(code, submission_uncertain=False):
    """Safe, actionable page-state guidance without replaying a possibly sent request."""
    if code == "FLOW_UI_BUSY" and not submission_uncertain:
        return "Bridge đang thao tác tạo một clip khác trong Flow. Chờ thao tác hiện tại hoàn tất rồi thử lại. AIFlow chưa gửi yêu cầu tạo video này."
    if code == "FLOW_UI_REFERENCES_PRESENT" and not submission_uncertain:
        return "Ô tạo Flow còn ảnh/video tham chiếu. Kiểm tra và bỏ tham chiếu khỏi ô tạo trong tab dự án đã chọn, rồi kiểm tra Bridge. AIFlow chưa gửi yêu cầu tạo video."
    if code == "FLOW_UI_DRAFT_PRESENT" and not submission_uncertain:
        return "Ô tạo Flow đang có bản nháp khác; Bridge giữ nguyên và chưa ghi đè. Lưu bản nháp nếu cần, rồi xóa nội dung ô tạo và kiểm tra Bridge. AIFlow chưa gửi yêu cầu tạo video."
    if code == "FLOW_HUMAN_VERIFICATION_REQUIRED":
        if submission_uncertain:
            return "Flow yêu cầu xác minh sau thao tác tạo. Hoàn tất xác minh trong tab dự án đã chọn và kiểm tra lượt vừa gửi; không bấm Tạo lại. Tiếp tục nhận clip nếu có mã tác vụ, hoặc khép lại lượt sau khi đã kiểm tra kết quả."
        return "Flow yêu cầu bạn xác minh trong tab dự án đã chọn. Hoàn tất xác minh rồi kiểm tra Bridge. AIFlow chưa gửi yêu cầu tạo video."
    if code == "FLOW_UI_GENERATION_REQUIRED" and not submission_uncertain:
        return "Google Flow chưa cho phép Bridge tạo ở trạng thái này. Kiểm tra yêu cầu trong tab dự án đã chọn, cập nhật extension nếu cần rồi kiểm tra Bridge. AIFlow chưa gửi yêu cầu tạo video."
    if code == "FLOW_UI_COMPOSER_REQUIRED" and not submission_uncertain:
        return "Bridge chưa tìm thấy ô tạo video trong giao diện Flow. Kiểm tra tab đang mở đúng dự án và ô tạo đang hiển thị, rồi kiểm tra Bridge. AIFlow chưa gửi yêu cầu tạo video."
    if code in {"FLOW_UI_SETTINGS_REQUIRED", "FLOW_UI_LITE_MODEL_REQUIRED", "FLOW_UI_EIGHT_SECONDS_REQUIRED"} and not submission_uncertain:
        return "Bridge chưa chọn được cấu hình Veo 3.1 Lite / 8 giây trong Flow. Kiểm tra các tùy chọn tạo video trong tab dự án rồi kiểm tra Bridge. AIFlow chưa gửi yêu cầu tạo video."
    if code == "FLOW_UI_SILENT_VIDEO_SETTING_REQUIRED" and not submission_uncertain:
        return "Bridge chưa xác nhận được tùy chọn trả video không có âm thanh trong Flow. Kiểm tra Cài đặt lưới ô và cập nhật extension; AIFlow chưa gửi yêu cầu tạo video."
    if isinstance(code, str) and code.startswith("FLOW_UI_REFERENCE_") and not submission_uncertain:
        return "Bridge chưa xác nhận được ảnh tham chiếu đã chọn trong Flow. Kiểm tra ô tạo và cửa sổ chọn ảnh; không dùng ảnh được chọn mặc định. AIFlow chưa gửi yêu cầu tạo video."
    return None


def scene_snapshot(project, scene):
    return {"project_short_id": project.short_id, "scene_id": scene.id, "prompt": scene.prompt,
            "narration": scene.narration, "duration": scene.duration, "aspect": project.aspect}


def reference_path(item, project_id, data_dir):
    if not item or item.project_id != project_id or item.role != "reference" or item.mime != "image/png" or not item.approved:
        raise ValueError("Invalid reference")
    path = contained(data_dir, item.path)
    if not path.is_file() or path.stat().st_size > 5 * 1024**2 or sha256(path) != item.sha256:
        raise ValueError("Changed reference")
    return path


def operation_public(row):
    result = json.loads(row.result_json)
    input_data = json.loads(row.input_json)
    return {"request_id": row.request_id, "scene_id": input_data["scene_id"],
            "allow_silent_video": input_data["snapshot"].get("allow_silent_video", False),
            "reference_mode": input_data["snapshot"].get("reference_mode", "ingredients"),
            "status": "interrupted" if row.status == "running" and row.request_id not in ACTIVE_VIDEOS else row.status,
            "error": row.error, "can_resume": bool(result.get("operation_name")) and not result.get("media_id")}


def reconcile_interrupted(engine):
    with Session(engine) as session:
        session.execute(update(StudioOperation).where(StudioOperation.kind == "flow_video",
            StudioOperation.status == "running").values(status="interrupted",
            error="Server đã dừng. Tiếp tục nhận kết quả nếu có mã Flow; không tự gửi lại yêu cầu tạo video."))
        session.commit()


async def generate(engine, settings, request_id):
    result = {}
    stage = "preflight"
    with Session(engine) as session:
        row = session.get(StudioOperation, request_id)
        if row is None or row.status != "running":
            ACTIVE_VIDEOS.discard(request_id)
            return
        frozen = json.loads(row.input_json)["snapshot"]
        result = json.loads(row.result_json)
        try:
            sdk = get_flow_sdk()
            if not result.get("operation_name"):
                project = session.get(Project, row.project_id)
                scene = session.get(Scene, frozen["scene_id"])
                assert_project_approved(session, row.project_id)
                content = {key: value for key, value in frozen.items() if key not in ("reference", "allow_silent_video", "reference_mode")}
                if not project or not scene or scene_snapshot(project, scene) != content:
                    raise ValueError("Scene changed before submission")
                reference = frozen.get("reference")
                reference_image = None
                if reference:
                    item = session.get(ProductionMedia, reference["id"])
                    reference_image = reference_path(item, row.project_id, settings.data_dir)
                    if item.sha256 != reference["sha256"] or json.loads(item.review_json) != reference["provenance"]:
                        raise ValueError("Reference changed before submission")
                remote_id = await sdk.resolve_project_id()
                await sdk.preflight_text_video(remote_id)
                # Persist uncertainty before the expensive remote call. Never automatically resubmit it.
                result = {"submission_started": True, "remote_project_id": remote_id, "model": "VEO3_LITE"}
                row.result_json = json.dumps(result)
                session.add(row)
                session.commit()
                stage = "submit"
                result["operation_name"] = await sdk.gen_text_video(prompt=frozen["prompt"], model="VEO3_LITE",
                    duration=8, aspect=frozen["aspect"], project_id=remote_id,
                    allow_silent_video=frozen.get("allow_silent_video", False),
                    reference_mode=frozen.get("reference_mode", "ingredients"),
                    **({"reference_image": reference_image} if reference_image else {}))
                row.result_json = json.dumps(result)
                session.add(row)
                session.commit()
            name = result["operation_name"]
            for _ in range(MAX_POLLS):
                stage = "poll"
                response = await sdk.check_async(name)
                status = extract_video_operations(response, requested=[name])[0]
                if status.get("done"):
                    if status.get("error"):
                        row.status = "failed"
                        row.error = "Flow báo tạo video thất bại. Kiểm tra quota và nội dung trong tab Flow trước khi tạo lượt mới."
                        break
                    entries = status.get("media_entries", [])
                    if not entries or not entries[0].get("url"):
                        raise RuntimeError("Completed video has no download URL")
                    path = settings.data_dir / "production" / "inputs" / str(row.project_id) / f"veo-{request_id}.mp4"
                    stage = "download"
                    await download_video(entries[0]["url"], path)
                    stage = "verify"
                    info = probe(path)
                    stream = next((item for item in info["streams"] if item.get("codec_type") == "video"), None)
                    if not stream or info["duration"] <= 0:
                        raise ValueError("No valid video stream")
                    session.expire_all()
                    project = session.get(Project, row.project_id)
                    scene = session.get(Scene, frozen["scene_id"])
                    stale = not project or not scene or scene_snapshot(project, scene) != {key: value for key, value in frozen.items() if key not in ("reference", "allow_silent_video", "reference_mode")}
                    try:
                        assert_project_approved(session, row.project_id)
                    except HTTPException:
                        stale = True
                    media = ProductionMedia(project_id=row.project_id, scene_id=frozen["scene_id"],
                        role="archived" if stale else "visual", path=str(path.resolve()), sha256=sha256(path),
                        mime="video/mp4", width=stream["width"], height=stream["height"], duration=info["duration"],
                        review_json=json.dumps({"provider": "google_flow", "model": "VEO3_LITE", "request_id": request_id,
                                               "allow_silent_video": frozen.get("allow_silent_video", False),
                                               "reference_mode": frozen.get("reference_mode", "ingredients"),
                                               **({"reference": frozen["reference"]} if frozen.get("reference") else {})}))
                    session.add(media)
                    stage = "persist"
                    session.flush()
                    result["media_id"] = media.id
                    row.status = "needs_attention" if stale else "succeeded"
                    row.error = "Cảnh đã đổi; clip được lưu trữ và chưa dùng để xuất." if stale else ""
                    row.result_json = json.dumps(result)
                    break
                await asyncio.sleep(POLL_INTERVAL)
            else:
                raise TimeoutError("Flow polling timed out")
        except asyncio.CancelledError:
            row.status = "interrupted"
            row.error = "Tác vụ bị gián đoạn. Tiếp tục nhận kết quả; không gửi lại yêu cầu tạo video."
            session.add(row)
            session.commit()
            raise
        except Exception as exc:
            diagnostic = {"stage": stage, "type": type(exc).__name__, "frames": [
                f"{Path(frame.filename).name}:{frame.name}:{frame.lineno}" for frame in traceback.extract_tb(exc.__traceback__)]}
            code = getattr(exc, "code", None)
            if isinstance(code, int) or (isinstance(code, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", code)):
                diagnostic["code"] = code
            status_code = getattr(exc, "status_code", None)
            if isinstance(status_code, int):
                diagnostic["status_code"] = status_code
            request_sent = getattr(exc, "request_sent", None)
            if isinstance(request_sent, bool):
                diagnostic["request_sent"] = request_sent
            if getattr(exc, "phase", None) in ("session", "captcha", "fetch", "decode"):
                diagnostic["phase"] = exc.phase
            if isinstance(getattr(exc, "rpc_status_code", None), int):
                diagnostic["rpc_status_code"] = exc.rpc_status_code
            logger.warning("Flow video task {} failed: {}", request_id, json.dumps(diagnostic))
            session.rollback()
            row = session.get(StudioOperation, request_id)
            result["diagnostic"] = diagnostic
            row.result_json = json.dumps(result)
            uncertain = result.get("submission_started") and not (stage == "submit" and request_sent is False)
            row.status = "needs_attention" if uncertain else "failed"
            row.error = failure_guidance(code, bool(uncertain)) or (
                             "Chưa nhận được kết quả Flow. Tiếp tục nhận clip nếu có mã tác vụ; nếu chưa có, kiểm tra tab Flow. Không tự tạo lại."
                             if uncertain else "Chưa gửi yêu cầu. Mở dự án Flow đã đăng nhập và kết nối AIFlow Bridge.")
        finally:
            session.add(row)
            session.commit()
            ACTIVE_VIDEOS.discard(request_id)
