"""Durable image receipts: submit once, then explicitly reconcile that worker job."""
from __future__ import annotations

import base64
import hashlib
import json
import math
import threading
import uuid

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from server.db.models.production import ProductionMedia
from server.db.models.project import Project
from server.db.models.scene import Scene
from server.db.models.studio import StudioOperation
from server.production.media import contained, sha256
from server.image import remote

LOCK = threading.RLock()
DIMENSIONS = {"9:16": (768, 1344), "16:9": (1344, 768), "1:1": (1024, 1024)}
VTON_DIMENSIONS = (576, 864)
VTON_FIELDS = ("person_media_id", "garment_media_id", "garment_category", "garment_photo_type")


def compile_prompt(brief, scene_prompt, user_prompt, subject_type, generation_mode="reference"):
    """Prioritize composition; preserve authored instructions without truncating them."""
    subject = str(brief.get("species") or subject_type).strip()
    subject_prompt = ("Natural fictional human portrait." if generation_mode == "text"
                      else f"Natural {subject} portrait; preserve identity.")
    parts = [user_prompt, scene_prompt, subject_prompt]
    parts.extend(str(brief[key]) for key in ("identity", "style", "requirements") if brief.get(key))
    prompt = "\n".join(dict.fromkeys(part.strip() for part in parts if part.strip()))
    if len(prompt) > 2000:
        raise HTTPException(422, "Rút gọn prompt tạo ảnh, mô tả nhân vật/phong cách và prompt cảnh; tổng đầu vào ảnh tối đa 2000 ký tự.")
    return prompt


def provenance_metadata(value, token):
    """Keep bounded rendering facts, never arbitrary worker fields or credential echoes."""
    if not isinstance(value, dict):
        return {}
    def safe_string(item):
        return (isinstance(item, str) and len(item) <= 300 and not any(c in item for c in "\r\n\\")
                and token.get_secret_value() not in item)
    strings = ("engine", "base_model", "model_revision", "adapter_model", "adapter_revision", "adapter_file",
               "device", "precision", "subject_type", "reference_preprocessing", "scheduler",
               "memory_profile", "vae_precision", "generation_mode", "garment_category", "garment_photo_type",
               "pose_model", "pose_revision", "source_revision", "human_parser", "pose_execution_provider",
               "output_resampling", "input_preprocessing")
    result = {key: value[key] for key in strings if safe_string(value.get(key))}
    for key in ("seed", "steps", "guidance_scale", "reference_strength", "duration_seconds", "width", "height", "native_width", "native_height"):
        item = value.get(key)
        if type(item) in (int, float) and math.isfinite(item) and 0 <= item <= 2**32:
            result[key] = item
    for key in ("cpu_offload", "adapter_active", "segmentation_free", "text_conditioning"):
        if type(value.get(key)) is bool:
            result[key] = value[key]
    if type(value.get("vae_tile_size")) is int and 64 <= value["vae_tile_size"] <= 2048:
        result["vae_tile_size"] = value["vae_tile_size"]
    if type(value.get("reference_count")) is int and 0 <= value["reference_count"] <= 3:
        result["reference_count"] = value["reference_count"]
    if value.get("input_roles") == ["person", "garment"]:
        result["input_roles"] = ["person", "garment"]
    if value.get("ignored_parameters") == ["prompt", "negative_prompt", "reference_strength"]:
        result["ignored_parameters"] = ["prompt", "negative_prompt", "reference_strength"]
    hashes = value.get("input_sha256")
    if isinstance(hashes, list) and len(hashes) == 2 and all(isinstance(item, str) and len(item) == 64
            and all(char in "0123456789abcdef" for char in item) for item in hashes):
        result["input_sha256"] = hashes
    for key in ("peak_vram_allocated_bytes", "peak_vram_reserved_bytes"):
        item = value.get(key)
        if type(item) is int and 0 <= item <= 64 * 1024**3:
            result[key] = item
    scheduler = value.get("scheduler_config")
    if isinstance(scheduler, dict):
        config = {}
        for key in ("algorithm_type", "use_karras_sigmas", "solver_order", "prediction_type",
                    "timestep_spacing", "beta_schedule", "num_train_timesteps", "thresholding"):
            item = scheduler.get(key)
            if (type(item) is bool or (type(item) is int and 0 <= item <= 1_000_000)
                    or (safe_string(item) and len(item) <= 80)):
                config[key] = item
        result["scheduler_config"] = config
    for key, names in (("versions", ("torch", "torchvision", "diffusers", "transformers", "accelerate", "safetensors", "Pillow", "einops", "onnxruntime", "opencv-python-headless")),
                       ("runtime_review", ("python", "torch", "torchvision", "cuda", "gpu", "torch_advisory_exception"))):
        info = value.get(key)
        if isinstance(info, dict):
            result[key] = {name: info[name] for name in names if safe_string(info.get(name))}
    return result


def capture(session, project, scene, references, automatic_references, generation_mode="reference"):
    return {"brief": project.production_brief, "aspect": project.aspect, "kind": project.kind,
            "generation_mode": generation_mode,
            "scene_prompt": scene.prompt if scene else "",
            "references": [{"id": ref.id, "sha256": ref.sha256, "role": ref.role,
                            **({"approved": ref.approved} if ref.role != "reference" else {})} for ref in references],
            "automatic_references": automatic_references,
            "reference_ids": [ref.id for ref in session.exec(select(ProductionMedia).where(
                ProductionMedia.project_id == project.id, ProductionMedia.role == "reference").order_by(ProductionMedia.id)).all()]
                if automatic_references else []}


def stale_input(session, project, inputs, data_dir):
    frozen = dict(inputs["_remote"]["snapshot"])
    # Receipts accepted before the optional mode field continue to mean reference mode.
    frozen.setdefault("generation_mode", "reference")
    session.refresh(project)
    scene = session.get(Scene, inputs["scene_id"]) if inputs["scene_id"] else None
    if scene:
        session.refresh(scene)
    refs = [session.get(ProductionMedia, ref["id"]) for ref in frozen["references"]]
    if (project.status == "generating" or any(not ref or ref.project_id != project.id for ref in refs)
            or (inputs["scene_id"] and (not scene or scene.project_id != project.id))):
        return True
    try:
        if any(sha256(contained(data_dir, ref.path)) != ref.sha256 for ref in refs):
            return True
    except (OSError, ValueError):
        return True
    if capture(session, project, scene, refs, frozen["automatic_references"], inputs.get("generation_mode", "reference")) != frozen:
        return True
    if project.kind == "video":
        from server.text.workflow import assert_project_approved
        try:
            assert_project_approved(session, project.id)
        except HTTPException:
            return True
    return False


def accept_job(session, operation, job, settings, token):
    from server.api.routes.production import media_public, project_or_404
    inputs = json.loads(operation.input_json)
    checkpoint = inputs["_remote"]
    if (job.get("request_id") != operation.request_id or job.get("input_sha256") != checkpoint["input_sha256"]
            or job.get("worker_id") != checkpoint["worker_id"]
            or job.get("status") not in ("queued", "running", "succeeded", "failed")):
        raise remote.ImageUnavailable("Biên nhận worker ảnh không khớp yêu cầu đã lưu.", "invalid_result")
    operation.status, operation.error = job["status"], ""
    if job["status"] == "failed":
        error = job.get("error")
        operation.error = ("Prompt vượt giới hạn 77 token của model ảnh. Rút gọn prompt tạo ảnh, mô tả nhân vật/phong cách, prompt cảnh hoặc negative prompt rồi tạo lượt mới."
                           if isinstance(error, dict) and error.get("code") == "prompt_too_long"
                           else "Worker chưa tạo được ảnh hoặc bị ngắt. Kiểm tra Colab trước khi tạo lượt mới.")
    if job["status"] != "succeeded":
        return
    generation_mode = inputs.get("generation_mode", "reference")
    width, height = VTON_DIMENSIONS if generation_mode == "vton" else DIMENSIONS[checkpoint["snapshot"]["aspect"]]
    raw = remote.verify_result(job.get("result", {}), width, height)
    supplied_metadata = job["result"].get("metadata")
    if (isinstance(supplied_metadata, dict) and "model_revision" in supplied_metadata
            and supplied_metadata["model_revision"] != checkpoint["model_revision"]):
        raise remote.ImageUnavailable("Kết quả ảnh dùng phiên bản model khác biên nhận đã lưu.", "invalid_result")
    metadata = provenance_metadata(supplied_metadata, token)
    reference_count = len(checkpoint["snapshot"]["references"])
    if generation_mode == "text" and (metadata.get("generation_mode") != "text"
            or metadata.get("reference_count") != 0 or metadata.get("adapter_active") is not False):
        raise remote.ImageUnavailable("Worker chưa xác nhận tạo từ mô tả, không có ảnh tham chiếu và adapter đã tắt.", "invalid_result")
    if generation_mode == "vton" and (metadata.get("generation_mode") != "vton"
            or metadata.get("reference_count") != 2 or metadata.get("adapter_active") is not False
            or metadata.get("human_parser") != "excluded" or metadata.get("segmentation_free") is not True
            or metadata.get("text_conditioning") is not False
            or metadata.get("output_resampling") != "none-full-native-canvas"
            or (metadata.get("width"), metadata.get("height")) != VTON_DIMENSIONS
            or (metadata.get("native_width"), metadata.get("native_height")) != VTON_DIMENSIONS
            or metadata.get("model_revision") != checkpoint["model_revision"]
            or metadata.get("input_roles") != ["person", "garment"]
            or metadata.get("input_sha256") != [ref["sha256"] for ref in checkpoint["input_references"]]
            or any(metadata.get(key) != inputs[key] for key in ("garment_category", "garment_photo_type"))):
        raise remote.ImageUnavailable("Worker chưa xác nhận đúng hai ảnh người/sản phẩm, loại trang phục và pipeline thử đồ không dùng adapter.", "invalid_result")
    if (metadata.get("generation_mode", generation_mode) != generation_mode
            or metadata.get("reference_count", reference_count) != reference_count):
        raise remote.ImageUnavailable("Kết quả ảnh không khớp chế độ hoặc số ảnh tham chiếu đã gửi.", "invalid_result")
    project = project_or_404(session, operation.project_id)
    stale = stale_input(session, project, inputs, settings.data_dir)
    folder = settings.data_dir / "production" / "inputs" / str(project.id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"colab-{operation.request_id}.png"
    temporary = path.with_suffix(".part")
    try:
        temporary.write_bytes(raw)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    media = ProductionMedia(project_id=project.id, scene_id=inputs["scene_id"],
        role="archived" if stale else "visual" if inputs["scene_id"] else "portrait",
        path=str(path.resolve()), sha256=hashlib.sha256(raw).hexdigest(), mime="image/png", width=width, height=height,
        review_json=json.dumps({"origin": {"kind": "colab_vton_image" if generation_mode == "vton" else "colab_text_image" if generation_mode == "text" else "colab_reference_image",
            "generation_mode": generation_mode, "reference_count": reference_count, "worker_id": checkpoint["worker_id"],
            "model_revision": checkpoint["model_revision"], "request_id": operation.request_id,
            "input_sha256": checkpoint["input_sha256"], "references": checkpoint["snapshot"]["references"],
            **({key: inputs[key] for key in VTON_FIELDS} if generation_mode == "vton" else {}),
            **({"input_references": checkpoint["input_references"]} if generation_mode == "vton" else {}),
            "subject_type": inputs["subject_type"], "seed": inputs["seed"], "steps": inputs["steps"],
            "guidance_scale": inputs["guidance_scale"], "reference_strength": 0.0 if generation_mode in ("text", "vton") else inputs["reference_strength"],
            "render_metadata": metadata}}, ensure_ascii=False))
    session.add(media)
    session.flush()
    operation.result_json = json.dumps(media_public(media))
    operation.status = "needs_attention" if stale else "succeeded"
    if stale:
        operation.error = "Đầu vào đã đổi; ảnh cũ được lưu trữ, cần tạo lượt mới với đầu vào hiện tại."


def existing(session, project_id, inputs):
    row = session.get(StudioOperation, inputs["request_id"])
    if row:
        saved = json.loads(row.input_json)
        saved.pop("_remote", None)
        saved.setdefault("generation_mode", "reference")
        for key in VTON_FIELDS:
            saved.setdefault(key, None)
        if row.kind != "image" or row.project_id != project_id or saved != inputs:
            raise HTTPException(409, "Request ID đã được dùng cho đầu vào khác.")
    return row


def verified_vton_origin(session, media, data_dir):
    """Require the local successful receipt and unchanged inputs before review or reuse."""
    origin = json.loads(media.review_json).get("origin", {})
    if not isinstance(origin, dict):
        raise ValueError("Nguồn ảnh thử đồ không hợp lệ.")
    if origin.get("generation_mode") != "vton" and origin.get("kind") != "colab_vton_image":
        return None
    operation = session.get(StudioOperation, str(origin.get("request_id", "")))
    inputs = json.loads(operation.input_json) if operation else {}
    checkpoint = inputs.get("_remote", {})
    receipt = json.loads(operation.result_json) if operation else {}
    metadata = origin.get("render_metadata", {})
    refs = checkpoint.get("snapshot", {}).get("references", [])
    normalized = checkpoint.get("input_references", [])
    if (not operation or operation.kind != "image" or operation.project_id != media.project_id
            or operation.status != "succeeded" or inputs.get("provider") != "colab"
            or inputs.get("generation_mode") != "vton" or inputs.get("subject_type") != "human"
            or inputs.get("reference_media_ids") != [] or len(refs) != 2
            or [ref.get("id") for ref in refs] != [inputs.get("person_media_id"), inputs.get("garment_media_id")]
            or not inputs.get("person_media_id") or inputs.get("person_media_id") == inputs.get("garment_media_id")
            or refs[0].get("role") not in ("reference", "portrait", "visual") or refs[1].get("role") != "garment"
            or inputs.get("garment_photo_type") != "flat-lay" or inputs.get("garment_category") not in ("tops", "bottoms", "one-pieces")
            or origin.get("kind") != "colab_vton_image" or origin.get("generation_mode") != "vton"
            or origin.get("reference_count") != 2 or origin.get("references") != refs
            or origin.get("input_references") != normalized or [ref.get("role") for ref in normalized] != ["person", "garment"]
            or any(origin.get(key) != inputs.get(key) for key in VTON_FIELDS)
            or not checkpoint.get("input_sha256") or origin.get("input_sha256") != checkpoint["input_sha256"]
            or origin.get("worker_id") != checkpoint.get("worker_id") or origin.get("model_revision") != checkpoint.get("model_revision")
            or not isinstance(metadata, dict) or metadata.get("generation_mode") != "vton"
            or metadata.get("reference_count") != 2 or metadata.get("adapter_active") is not False
            or metadata.get("human_parser") != "excluded" or metadata.get("segmentation_free") is not True
            or metadata.get("text_conditioning") is not False
            or metadata.get("output_resampling") != "none-full-native-canvas"
            or (metadata.get("width"), metadata.get("height")) != VTON_DIMENSIONS
            or (metadata.get("native_width"), metadata.get("native_height")) != VTON_DIMENSIONS
            or metadata.get("model_revision") != checkpoint.get("model_revision")
            or metadata.get("input_roles") != ["person", "garment"]
            or metadata.get("input_sha256") != [ref.get("sha256") for ref in normalized]
            or any(metadata.get(key) != inputs.get(key) for key in ("garment_category", "garment_photo_type"))
            or receipt.get("id") != media.id or receipt.get("sha256") != media.sha256
            or media.scene_id != inputs.get("scene_id") or receipt.get("scene_id") != media.scene_id
            or (media.width, media.height) != VTON_DIMENSIONS):
        raise ValueError("Ảnh thử đồ thiếu biên nhận thành công xác nhận đúng ảnh người/sản phẩm và loại trang phục.")
    project = session.get(Project, media.project_id)
    if not project or stale_input(session, project, inputs, data_dir):
        raise ValueError("Đầu vào thử đồ đã đổi; cần tạo và duyệt lượt mới.")
    return origin


def submit(project_id, body, session, settings):
    from server.api.routes.production import project_or_404
    inputs = body.model_dump(mode="json")
    with LOCK:
        old = existing(session, project_id, inputs)
        if old:
            return old
        project = project_or_404(session, project_id)
        if project.status == "generating":
            raise HTTPException(409, "Dự án đang chạy.")
        scene = session.get(Scene, body.scene_id) if body.scene_id else None
        if (project.kind not in ("portrait", "video") or project.aspect not in DIMENSIONS
                or (project.kind == "portrait" and body.scene_id)
                or (project.kind == "video" and (not scene or scene.project_id != project.id))):
            raise HTTPException(422, "Chọn dự án chân dung hoặc cảnh thuộc dự án video với tỉ lệ được hỗ trợ.")
        if body.generation_mode == "reference" and project.adapter == "ecommerce_product" and not body.reference_media_ids:
            raise HTTPException(422, "Chọn rõ ảnh người/thú cưng cho Colab; không tự dùng ảnh sản phẩm.")
        if project.kind == "video":
            from server.text.workflow import assert_project_approved
            assert_project_approved(session, project_id)
        ids = body.reference_media_ids
        if body.generation_mode == "vton":
            references = [session.get(ProductionMedia, identity) for identity in (body.person_media_id, body.garment_media_id)]
            person, garment = references
            if (any(not ref or ref.project_id != project_id or not ref.mime.startswith("image/") for ref in references)
                    or person.role not in ("reference", "portrait", "visual")
                    or (person.role != "reference" and not person.approved) or garment.role != "garment"):
                raise HTTPException(422, "Chọn ảnh người đang hoạt động (ảnh thành phẩm cần duyệt) và ảnh sản phẩm riêng thuộc dự án.")
            if person.sha256 == garment.sha256:
                raise HTTPException(422, "Ảnh người và ảnh sản phẩm phải là hai ảnh khác nhau.")
            try:
                origin = verified_vton_origin(session, person, settings.data_dir)
                if origin and "garment_fidelity" not in json.loads(person.review_json).get("checklist", []):
                    raise ValueError("Duyệt độ khớp trang phục trước khi dùng ảnh thử đồ làm ảnh người.")
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        elif body.generation_mode == "text":
            references = []
        elif ids:
            references = [session.get(ProductionMedia, identity) for identity in ids]
        else:
            references = session.exec(select(ProductionMedia).where(ProductionMedia.project_id == project_id,
                ProductionMedia.role == "reference").order_by(ProductionMedia.id)).all()
        if body.generation_mode == "reference" and (not 1 <= len(references) <= 3 or len(set(ids)) != len(ids)
                or any(not ref or ref.project_id != project_id or ref.role == "archived"
                       or ref.role == "garment" or not ref.mime.startswith("image/") or (ref.role != "reference" and not ref.approved)
                       for ref in references)):
            raise HTTPException(422, "Chọn 1–3 ảnh tham chiếu đang hoạt động thuộc dự án.")
        url, token, health = remote.connection.snapshot()
        if body.generation_mode == "text" and "text_to_image" not in health["capabilities"]:
            raise HTTPException(409, "Worker chưa hỗ trợ tạo người hư cấu từ mô tả; tải bộ Colab ảnh mới và kiểm tra lại kết nối.")
        if body.generation_mode == "vton" and "virtual_try_on" not in health["capabilities"]:
            raise HTTPException(409, "Kết nối worker Colab thử đồ trước khi gửi hai ảnh người/sản phẩm.")
        if body.generation_mode == "reference" and "reference_image" not in health["capabilities"]:
            raise HTTPException(409, "Worker hiện tại chỉ thử đồ; kết nối worker Colab ảnh tham chiếu.")
        encoded_refs = []
        try:
            for ref in references:
                path = contained(settings.data_dir, ref.path)
                if path.stat().st_size > remote.MAX_IMAGE or sha256(path) != ref.sha256:
                    raise remote.ImageUnavailable("Ảnh tham chiếu đã đổi hoặc vượt 10 MiB.", "invalid_input")
                raw = remote.reference_png(path.read_bytes())
                encoded_refs.append({"mime": "image/png", "data": base64.b64encode(raw).decode(),
                                     "sha256": hashlib.sha256(raw).hexdigest()})
                if body.generation_mode == "vton":
                    encoded_refs[-1]["role"] = "person" if len(encoded_refs) == 1 else "garment"
        except (OSError, ValueError) as exc:
            raise HTTPException(422, "Không đọc được ảnh tham chiếu hợp lệ trong storage. Nhập lại ảnh.") from exc
        if body.generation_mode == "vton" and encoded_refs[0]["sha256"] == encoded_refs[1]["sha256"]:
            raise HTTPException(422, "Ảnh người và ảnh sản phẩm phải là hai ảnh khác nhau sau chuẩn hóa.")
        frozen = capture(session, project, scene, references,
                         body.generation_mode == "reference" and not ids, body.generation_mode)
        width, height = VTON_DIMENSIONS if body.generation_mode == "vton" else DIMENSIONS[project.aspect]
        brief = json.loads(project.production_brief)
        prompt = "" if body.generation_mode == "vton" else compile_prompt(brief, scene.prompt if scene else "", body.prompt, body.subject_type, body.generation_mode)
        payload = {key: inputs[key] for key in ("request_id", "generation_mode", "subject_type", "negative_prompt", "seed", "steps", "guidance_scale", "reference_strength")}
        if body.generation_mode == "vton":
            payload.update({key: inputs[key] for key in ("garment_category", "garment_photo_type")})
        elif "text_to_image" not in health["capabilities"]:
            payload.pop("generation_mode")  # Older API v1 workers still support the original reference descriptor.
        payload.update(prompt=prompt, width=width, height=height, references=encoded_refs)
        saved = {**inputs, "_remote": {"snapshot": frozen, "input_sha256": remote.digest(payload),
                 "worker_id": health["worker_id"], "model_revision": health["model_revision"]}}
        if body.generation_mode == "vton":
            saved["_remote"]["input_references"] = [{"role": ref["role"], "sha256": ref["sha256"]} for ref in encoded_refs]
        operation = StudioOperation(request_id=inputs["request_id"], project_id=project_id,
                                    kind="image", status="queued", input_json=json.dumps(saved, ensure_ascii=False))
        session.add(operation)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            old = existing(session, project_id, inputs)
            if old:
                return old
            raise
        try:
            accept_job(session, operation, remote.request(url, token, "POST", "/v1/images/jobs", json=payload), settings, token)
        except remote.ImageUnavailable as exc:
            operation.status = "needs_attention"
            operation.error = str(exc) + " Dùng Cập nhật để nhận lại tác vụ đã gửi; không tự gửi lại."
        session.add(operation)
        session.commit()
        session.refresh(operation)
        return operation


def refresh(project_id, request_id, session, settings):
    with LOCK:
        operation = session.get(StudioOperation, str(request_id))
        if not operation or operation.project_id != project_id or operation.kind != "image":
            raise HTTPException(404, "Không tìm thấy tác vụ ảnh.")
        inputs = json.loads(operation.input_json)
        if inputs.get("provider") != "colab":
            raise HTTPException(409, "Chỉ nhận lại biên nhận từ Colab ảnh.")
        if operation.status in ("succeeded", "failed") or json.loads(operation.result_json).get("id"):
            return operation
        try:
            url, token, health = remote.connection.snapshot()
            if health["worker_id"] != inputs["_remote"]["worker_id"]:
                raise remote.ImageUnavailable("Worker ảnh đã đổi; kết nối lại worker giữ biên nhận cũ.", "worker_changed")
            accept_job(session, operation, remote.request(url, token, "GET", f"/v1/images/jobs/{operation.request_id}"), settings, token)
        except remote.ImageUnavailable as exc:
            operation.status, operation.error = "needs_attention", str(exc)
        session.add(operation)
        session.commit()
        session.refresh(operation)
        return operation
