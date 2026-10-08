"""Real React + isolated studio API; only external Colab/Flow transport is mocked.

Run against Vite: python -m server.tests.browser_colab_image
No inference, live credentials or user database.
"""
import base64
import hashlib
import io
import json
import os
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from playwright.sync_api import expect, sync_playwright
from sqlmodel import Session, SQLModel, create_engine, select
from sqlalchemy.pool import NullPool

from server.api.routes import production, scripts, studio
from server.config import Settings
from server.db.models.production import ProductionMedia
from server.db.models.project import Project
from server.db.models.scene import Scene
from server.db.models.studio import StorySeries
from server.image import remote
from server.tests.test_production import image_bytes


def main():
    jobs, submissions, promotions, downloads, api_errors, page_errors = {}, [], [], [], [], []
    job_refreshes, generation_inputs = {}, []
    refresh_count, fail_check, text_capability = 0, False, True
    worker_id, revision = str(uuid.uuid4()), "a" * 40
    token_value = "FAKE_UI_TOKEN_ONLY_" * 3

    def worker(url, token, method, path, **kwargs):
        nonlocal refresh_count
        assert token.get_secret_value() == token_value
        if path == "/v1/health":
            return {"api_version": "1", "worker_id": worker_id, "model_revision": revision,
                    "capabilities": ["image", "reference_image"] + (["text_to_image"] if text_capability else []), "persistent_jobs": True,
                    "status": "warming_up" if fail_check else "ready"}
        if method == "POST" and path == "/v1/images/jobs":
            payload = kwargs["json"]
            assert len(payload["references"]) == (0 if payload["generation_mode"] == "text" else 1)
            submissions.append(payload)
            jobs[payload["request_id"]] = {"request_id": payload["request_id"], "worker_id": worker_id,
                "input_sha256": remote.digest(payload), "status": "queued"}
            if payload["subject_type"] == "pet":
                raise remote.ImageUnavailable("Fixture acknowledgement lost; receipt remains on worker")
            return dict(jobs[payload["request_id"]])
        if method == "GET" and path.startswith("/v1/images/jobs/"):
            refresh_count += 1
            result = dict(jobs[path.rsplit("/", 1)[-1]])
            payload = next(item for item in submissions if item["request_id"] == result["request_id"])
            job_refreshes[result["request_id"]] = job_refreshes.get(result["request_id"], 0) + 1
            result["status"] = "failed" if payload["subject_type"] == "pet" else "running" if payload["generation_mode"] == "reference" and job_refreshes[result["request_id"]] == 1 else "succeeded"
            if result["status"] == "succeeded":
                buffer = io.BytesIO()
                Image.new("RGB", (payload["width"], payload["height"]), "#6a4936" if payload["generation_mode"] == "text" else "#36664a").save(buffer, "PNG")
                raw = buffer.getvalue()
                result["result"] = {"mime": "image/png", "data": base64.b64encode(raw).decode(),
                    "sha256": hashlib.sha256(raw).hexdigest(), "width": payload["width"], "height": payload["height"]}
                if payload["generation_mode"] == "text":
                    result["result"]["metadata"] = {"generation_mode": "text", "reference_count": 0, "adapter_active": False}
            return result
        raise AssertionError(f"Unexpected external worker call {method} {path}")

    with tempfile.TemporaryDirectory(prefix="aiflow-image-ui-") as directory:
        root = Path(directory)
        engine = create_engine(f"sqlite:///{root / 'test.db'}", connect_args={"check_same_thread": False}, poolclass=NullPool)
        SQLModel.metadata.create_all(engine)
        settings = Settings(_env_file=None, data_dir=root)
        app = FastAPI()
        for module in (production, studio, scripts):
            app.include_router(module.router)
        def sessions():
            with Session(engine) as db:
                yield db
        for module in (production, studio, scripts):
            app.dependency_overrides[module.get_session] = sessions
        for module in (production, studio):
            app.dependency_overrides[module.get_settings] = lambda: settings
        @app.get("/api/health")
        def health():
            return {"extension_connected": False}
        with Session(engine) as db:
            db.add(StorySeries(name="Initial fetch fixture", bible=""))
            target = Project(short_id="ui-video-target", title="Video fixture", kind="video", production_brief="{}")
            db.add(target); db.flush()
            db.add(Scene(project_id=target.id, order=0, prompt="Natural light scene"))
            db.commit(); db.refresh(target)
            target_id = target.id
        try:
            with patch.object(remote, "connection", remote.ImageConnection()), patch.object(remote, "request", side_effect=worker), \
                patch.object(production, "_flow_capability", new=AsyncMock(return_value={"available": False,
                    "project_url": "https://flow.google.com/", "message": "Offline fixture"})), \
                TestClient(app) as client, sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, channel=os.environ.get("AIFLOW_TEST_BROWSER_CHANNEL"))
                try:
                    page = browser.new_page(viewport={"width": 1440, "height": 1000})
                    page.on("pageerror", lambda error: page_errors.append(str(error)))
                    delayed_connections = []
                    delay_initial_connection = True
                    def api(route):
                        request, url = route.request, urlsplit(route.request.url)
                        if not url.path.startswith("/api/"):
                            route.continue_(); return
                        if delay_initial_connection and request.method == "GET" and url.path == "/api/studio/connections/colab-image":
                            delayed_connections.append(route)
                            return
                        if request.method == "POST" and url.path.endswith("/references"):
                            promotions.append(json.loads(request.post_data))
                        if request.method == "POST" and url.path.endswith("/generate-image"):
                            generation_inputs.append(json.loads(request.post_data))
                        if url.path.startswith("/api/studio/colab-image/"):
                            assert request.headers.get("x-aiflow-client") == "1"
                            downloads.append(url.path)
                        response = client.request(request.method, url.path + ("?" + url.query if url.query else ""),
                            content=request.post_data_buffer, headers=request.headers)
                        if response.status_code >= 400 and not (fail_check and url.path.endswith("/colab-image/check")):
                            api_errors.append(f"{request.method} {url.path}: {response.status_code} {response.text}")
                        route.fulfill(status=response.status_code, body=response.content,
                            headers={"Content-Type": response.headers.get("content-type", "application/json")})
                    page.route("**/api/**", api)
                    page.goto("http://127.0.0.1:5177/studio-settings")
                    page.get_by_label("URL worker ảnh", exact=True).fill("https://fixture.trycloudflare.com")
                    token = page.get_by_label("Token worker ảnh", exact=True)
                    expect(token).to_have_attribute("type", "password")
                    token.fill(token_value)
                    assert delayed_connections, "Initial connection request must remain delayed while typing"
                    delay_initial_connection = False
                    for route in delayed_connections:
                        response = client.get("/api/studio/connections/colab-image", headers={"X-AIFlow-Client": "1"})
                        route.fulfill(status=response.status_code, body=response.content, content_type="application/json")
                    expect(page.get_by_role("button", name="Initial fetch fixture · v1", exact=True)).to_be_visible()
                    expect(page.get_by_label("URL worker ảnh", exact=True)).to_have_value("https://fixture.trycloudflare.com")
                    page.get_by_role("button", name="Lưu kết nối ảnh", exact=True).click()
                    expect(token).to_have_value("")
                    assert token_value not in page.evaluate("JSON.stringify(localStorage) + JSON.stringify(sessionStorage)")
                    assert token_value not in page.content()
                    expect(page.get_by_text("Worker ảnh sẵn sàng", exact=False)).to_be_visible()
                    for label in ("Tải notebook ảnh", "Tải gói worker ảnh"):
                        with page.expect_download():
                            page.get_by_role("button", name=label, exact=True).click()
                    assert len(downloads) == 2

                    page.goto("http://127.0.0.1:5177/production")
                    for label, value in [("Tên dự án", "Colab image fixture"), ("Chủ thể / loài / giống", "Human"),
                                         ("Phong cách", "Natural photograph"), ("Đặc điểm nhận diện phải giữ", "Dark eyes")]:
                        page.get_by_label(label, exact=True).fill(value)
                    page.get_by_role("button", name="Tạo dự án chân dung", exact=True).click()
                    expect(page.get_by_role("heading", name="Colab image fixture", exact=True)).to_be_visible()
                    project_id = int(urlsplit(page.url).query.split("project=")[-1])
                    page.get_by_label("Thêm ảnh tham chiếu", exact=False).set_input_files({"name": "reference.png", "mimeType": "image/png", "buffer": image_bytes()})
                    expect(page.get_by_alt_text("Ảnh tham chiếu", exact=False)).to_be_visible()
                    with Session(engine) as db:
                        reference = db.exec(select(ProductionMedia).where(ProductionMedia.project_id == project_id)).one()
                        reference_id = reference.id
                    page.get_by_label("Provider tạo ảnh", exact=True).select_option("colab")
                    page.get_by_label("Chủ thể", exact=True).select_option("human")
                    create = page.get_by_role("button", name="Tạo ảnh", exact=True)
                    expect(create).to_be_disabled()
                    page.get_by_label("Ảnh tham chiếu gửi tới Colab", exact=False).select_option([str(reference_id)])
                    page.get_by_label("Mô tả bổ sung cho ảnh", exact=True).fill("Natural photograph, real skin texture")
                    create.click(); expect(create).to_be_disabled()
                    assert len(submissions) == 1 and submissions[0]["subject_type"] == "human"
                    assert submissions[0]["seed"] == 0 and submissions[0]["reference_strength"] == 0.45
                    assert submissions[0]["steps"] == 30 and submissions[0]["guidance_scale"] == 4.5
                    page.reload(); expect(create).to_be_disabled()
                    expect(page.get_by_label("Provider tạo ảnh", exact=True)).to_have_value("colab")
                    expect(page.get_by_label("Chủ thể", exact=True)).to_have_value("human")
                    refresh = page.get_by_role("button", name="Kiểm tra kết quả (không tạo lại)", exact=True)
                    refresh.click(); expect(page.get_by_text("Đang tạo ảnh", exact=False).first).to_be_visible()
                    refresh.click(); expect(create).to_be_enabled()
                    assert len(submissions) == 1 and refresh_count == 2
                    approved = page.get_by_label("Ảnh đã duyệt", exact=True)
                    assert approved.locator("option").count() == 1
                    for checkbox in page.get_by_role("checkbox").all():
                        checkbox.check()
                    page.get_by_role("button", name="Xác nhận đã kiểm tra", exact=True).click()
                    with Session(engine) as db:
                        generated = db.exec(select(ProductionMedia).where(ProductionMedia.project_id == project_id, ProductionMedia.role == "portrait")).one()
                        generated_id = generated.id
                    expect(approved.locator(f"option[value='{generated_id}']")).to_have_count(1)
                    approved.select_option(str(generated_id))
                    page.get_by_label("ID dự án video nhận ảnh", exact=True).fill(str(target_id))
                    page.get_by_role("button", name="Dùng làm ảnh tham chiếu", exact=True).click()
                    expect(page.get_by_role("link", name="Mở dự án nhận ảnh", exact=True)).to_have_attribute("href", f"/production?project={target_id}")
                    assert promotions == [{"media_id": generated_id}]
                    with Session(engine) as db:
                        promoted = db.exec(select(ProductionMedia).where(ProductionMedia.project_id == target_id)).one()
                        assert promoted.role == "reference" and Path(promoted.path).is_file()
                        promoted_id = promoted.id
                    screenshots = Path("storage/verification/colab-image")
                    screenshots.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(screenshots / "desktop.png"), full_page=True)
                    page.get_by_label("Chủ thể", exact=True).select_option("pet")
                    create.click(); refresh.click()
                    expect(page.get_by_text("Worker chưa tạo được ảnh", exact=False).first).to_be_visible()
                    expect(create).to_be_enabled()
                    assert len(submissions) == 2 and submissions[-1]["subject_type"] == "pet"
                    # Existing selected project photos must not be sent in text mode.
                    page.get_by_label("Cách tạo ảnh", exact=True).select_option("text")
                    expect(page.get_by_label("Chủ thể", exact=True)).to_have_value("human")
                    expect(page.get_by_label("Chủ thể", exact=True)).to_be_disabled()
                    expect(page.get_by_label("Ảnh tham chiếu gửi tới Colab", exact=False)).to_have_count(0)
                    expect(page.get_by_role("slider")).to_have_count(0)
                    create.click(); refresh.click(); expect(create).to_be_enabled()
                    assert generation_inputs[-1]["reference_media_ids"] == []
                    assert submissions[-1]["generation_mode"] == "text" and submissions[-1]["references"] == []

                    # The real creation form also reaches text mode with zero uploads.
                    page.goto("http://127.0.0.1:5177/production")
                    for label, value in [("Tên dự án", "Fictional human fixture"), ("Chủ thể / loài / giống", "Human"),
                                         ("Phong cách", "Natural photograph"), ("Đặc điểm nhận diện phải giữ", "Fictional adult with brown eyes")]:
                        page.get_by_label(label, exact=True).fill(value)
                    page.get_by_role("button", name="Tạo dự án chân dung", exact=True).click()
                    expect(page.get_by_role("heading", name="Fictional human fixture", exact=True)).to_be_visible()
                    text_project_id = int(urlsplit(page.url).query.split("project=")[-1])
                    with Session(engine) as db:
                        assert db.exec(select(ProductionMedia).where(ProductionMedia.project_id == text_project_id)).all() == []
                    page.get_by_label("Provider tạo ảnh", exact=True).select_option("colab")
                    expect(create).to_be_disabled()
                    page.get_by_label("Cách tạo ảnh", exact=True).select_option("text")
                    expect(create).to_be_enabled()
                    create.click(); expect(create).to_be_disabled()
                    assert generation_inputs[-1]["generation_mode"] == "text" and generation_inputs[-1]["reference_media_ids"] == []
                    assert submissions[-1]["subject_type"] == "human" and submissions[-1]["references"] == []
                    page.reload()
                    expect(page.get_by_label("Cách tạo ảnh", exact=True)).to_have_value("text")
                    refresh.click(); expect(create).to_be_enabled()
                    for checkbox in page.get_by_role("checkbox").all():
                        checkbox.check()
                    page.get_by_role("button", name="Xác nhận đã kiểm tra", exact=True).click()
                    with Session(engine) as db:
                        fictional = db.exec(select(ProductionMedia).where(ProductionMedia.project_id == text_project_id)).one()
                        fictional_id, fictional_sha = fictional.id, fictional.sha256
                    approved.select_option(str(fictional_id))
                    page.get_by_label("ID dự án video nhận ảnh", exact=True).fill(str(target_id))
                    page.get_by_role("button", name="Dùng làm ảnh tham chiếu", exact=True).click()
                    expect(page.get_by_role("link", name="Mở dự án nhận ảnh", exact=True)).to_have_attribute("href", f"/production?project={target_id}")
                    with Session(engine) as db:
                        canonical = db.exec(select(ProductionMedia).where(ProductionMedia.project_id == target_id, ProductionMedia.sha256 == fictional_sha)).one()
                        assert canonical.role == "reference" and Path(canonical.path).is_file()
                        assert hashlib.sha256(Path(canonical.path).read_bytes()).hexdigest() == fictional_sha
                        canonical_id = canonical.id
                    text_capability = False
                    page.get_by_role("button", name="Kiểm tra worker ảnh", exact=True).click()
                    expect(page.get_by_text("Worker chưa hỗ trợ tạo từ mô tả", exact=False)).to_be_visible()
                    expect(create).to_be_disabled()
                    text_capability = True
                    page.get_by_role("button", name="Kiểm tra worker ảnh", exact=True).click()
                    expect(create).to_be_enabled()
                    fail_check = True
                    page.get_by_role("button", name="Kiểm tra worker ảnh", exact=True).click()
                    expect(page.get_by_text("Worker ảnh chưa sẵn sàng", exact=False)).to_be_visible()
                    expect(create).to_be_disabled()
                    page.set_viewport_size({"width": 390, "height": 844})
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Horizontal overflow"
                    page.screenshot(path=str(screenshots / "mobile.png"), full_page=True)
                    page.get_by_role("link", name="Mở dự án nhận ảnh", exact=True).click()
                    expect(page.get_by_role("heading", name="Video fixture", exact=True)).to_be_visible()
                    picker = page.get_by_label("Tham chiếu dùng cho lượt tạo tiếp theo", exact=False)
                    expect(picker.locator(f"option[value='{promoted_id}']")).to_have_count(1)
                    expect(picker.locator(f"option[value='{canonical_id}']")).to_have_count(1)
                    assert not page_errors, page_errors
                    assert not api_errors, api_errors
                    print(json.dumps({"browser": "Chromium", "api": "real isolated production/studio", "flow": "connect > downloads > human reference > reload > refresh > approve > promote > pet lost acknowledgement > refresh failure > text ignores project photos > zero-upload fictional human > reload > approve > canonical reference > warmup > video reference picker", "generation_calls": len(submissions), "refresh_calls": refresh_count, "page_errors": page_errors, "api_errors": api_errors, "screenshots": str(screenshots)}))
                except Exception:
                    print(json.dumps({"page_errors": page_errors, "api_errors": api_errors,
                        "body": page.locator("body").inner_text()[:6000]}, ensure_ascii=True))
                    raise
                finally:
                    browser.close()
        finally:
            engine.dispose()


if __name__ == "__main__":
    main()
