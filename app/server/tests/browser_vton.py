"""Real React and isolated API; mock only external VTON worker transport.

Run against Vite on 5177: python -m server.tests.browser_vton
No GPU inference, live credentials or user database.
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
from server.image import remote


def image_bytes(color, size=(600, 900)):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


def main():
    jobs, submissions, generation_inputs, promotions, downloads, page_errors, api_errors = {}, [], [], [], [], [], []
    vton_capability, lost_ack, refresh_count = False, True, 0
    worker_id, revision = str(uuid.uuid4()), "a" * 40
    token_value = "FAKE_VTON_UI_TOKEN_ONLY_" * 3

    def worker(url, token, method, path, **kwargs):
        nonlocal refresh_count
        assert token.get_secret_value() == token_value
        if path == "/v1/health":
            return {"api_version": "1", "worker_id": worker_id, "model_revision": revision,
                    "capabilities": ["image", "reference_image"] + (["virtual_try_on"] if vton_capability else []),
                    "persistent_jobs": True, "status": "ready"}
        if method == "POST" and path == "/v1/images/jobs":
            payload = kwargs["json"]
            assert payload["generation_mode"] == "vton"
            assert [ref["role"] for ref in payload["references"]] == ["person", "garment"]
            assert payload["references"][0]["sha256"] != payload["references"][1]["sha256"]
            assert (payload["width"], payload["height"]) == (576, 864)
            assert payload["garment_category"] == "tops" and payload["garment_photo_type"] == "flat-lay"
            assert payload["guidance_scale"] == 1.5
            submissions.append(payload)
            jobs[payload["request_id"]] = {"request_id": payload["request_id"], "worker_id": worker_id,
                "input_sha256": remote.digest(payload), "status": "queued"}
            if lost_ack:
                raise remote.ImageUnavailable("Fixture acknowledgement lost; worker retains receipt")
            return dict(jobs[payload["request_id"]])
        if method == "GET" and path.startswith("/v1/images/jobs/"):
            refresh_count += 1
            result = dict(jobs[path.rsplit("/", 1)[-1]])
            payload = next(item for item in submissions if item["request_id"] == result["request_id"])
            result["status"] = "running" if refresh_count == 1 else "succeeded"
            if result["status"] == "succeeded":
                raw = image_bytes("#646a36", (576, 864))
                result["result"] = {"mime": "image/png", "data": base64.b64encode(raw).decode(),
                    "sha256": hashlib.sha256(raw).hexdigest(), "width": 576, "height": 864,
                    "metadata": {"generation_mode": "vton", "reference_count": 2, "adapter_active": False,
                        "input_roles": ["person", "garment"], "input_sha256": [ref["sha256"] for ref in payload["references"]],
                        "garment_category": payload["garment_category"], "garment_photo_type": payload["garment_photo_type"],
                        "model_revision": revision, "human_parser": "excluded", "segmentation_free": True,
                        "text_conditioning": False, "output_resampling": "none-full-native-canvas",
                        "width": 576, "height": 864, "native_width": 576, "native_height": 864}}
            return result
        raise AssertionError(f"Unexpected external worker call {method} {path}")

    with tempfile.TemporaryDirectory(prefix="aiflow-vton-ui-") as directory:
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
            target = Project(short_id="vton-ui-video-target", title="VTON video fixture", kind="video", production_brief="{}")
            db.add(target); db.flush()
            db.add(Scene(project_id=target.id, order=0, prompt="Natural light scene"))
            db.commit(); db.refresh(target)
            target_id = target.id
        try:
            with patch.object(remote, "connection", remote.ImageConnection()), patch.object(remote, "request", side_effect=worker), \
                patch.object(production, "_flow_capability", new=AsyncMock(return_value={"available": False,
                    "project_url": "https://flow.google.com/", "message": "Offline fixture"})), \
                TestClient(app) as client, sync_playwright() as playwright:
                response = client.put("/api/studio/connections/colab-image", json={"url": "https://fixture.trycloudflare.com", "token": token_value}, headers={"X-AIFlow-Client": "1"})
                assert response.status_code == 200, response.text
                browser = playwright.chromium.launch(headless=True, channel=os.environ.get("AIFLOW_TEST_BROWSER_CHANNEL"))
                try:
                    page = browser.new_page(viewport={"width": 1440, "height": 1000})
                    page.on("pageerror", lambda error: page_errors.append(str(error)))
                    def api(route):
                        request, url = route.request, urlsplit(route.request.url)
                        if not url.path.startswith("/api/"):
                            route.continue_(); return
                        if request.method == "POST" and url.path.endswith("/generate-image"):
                            generation_inputs.append(json.loads(request.post_data))
                        if request.method == "POST" and url.path.endswith("/references"):
                            promotions.append(json.loads(request.post_data))
                        if url.path.startswith("/api/studio/colab-vton/"):
                            assert request.headers.get("x-aiflow-client") == "1"
                            downloads.append(url.path)
                        response = client.request(request.method, url.path + ("?" + url.query if url.query else ""),
                            content=request.post_data_buffer, headers=request.headers)
                        if response.status_code >= 400:
                            api_errors.append(f"{request.method} {url.path}: {response.status_code} {response.text}")
                        route.fulfill(status=response.status_code, body=response.content,
                            headers={"Content-Type": response.headers.get("content-type", "application/json")})
                    page.route("**/api/**", api)
                    page.goto("http://127.0.0.1:5177/studio-settings")
                    for label in ("Tải notebook VTON", "Tải gói worker VTON"):
                        with page.expect_download():
                            page.get_by_role("button", name=label, exact=True).click()
                    assert len(downloads) == 2
                    page.goto("http://127.0.0.1:5177/production")
                    for label, value in [("Tên dự án", "VTON fixture"), ("Chủ thể / loài / giống", "Human"),
                                         ("Phong cách", "Natural photograph"), ("Đặc điểm nhận diện phải giữ", "Slim fictional VN01 adult")]:
                        page.get_by_label(label, exact=True).fill(value)
                    page.get_by_role("button", name="Tạo dự án chân dung", exact=True).click()
                    expect(page.get_by_role("heading", name="VTON fixture", exact=True)).to_be_visible()
                    project_id = int(urlsplit(page.url).query.split("project=")[-1])
                    page.get_by_label("Thêm ảnh tham chiếu", exact=False).set_input_files({"name": "person.png", "mimeType": "image/png", "buffer": image_bytes("#36664a")})
                    expect(page.get_by_alt_text("Ảnh tham chiếu", exact=False)).to_be_visible()
                    page.get_by_label("Thêm ảnh trang phục shop", exact=False).set_input_files({"name": "garment.png", "mimeType": "image/png", "buffer": image_bytes("#46366a", (700, 700))})
                    expect(page.get_by_alt_text("Trang phục shop", exact=False)).to_be_visible()
                    with Session(engine) as db:
                        rows = db.exec(select(ProductionMedia).where(ProductionMedia.project_id == project_id)).all()
                        person_id = next(row.id for row in rows if row.role == "reference")
                        garment_id = next(row.id for row in rows if row.role == "garment")
                    page.get_by_label("Provider tạo ảnh", exact=True).select_option("colab")
                    page.get_by_label("Cách tạo ảnh", exact=True).select_option("vton")
                    expect(page.get_by_label("Chủ thể", exact=True)).to_have_value("human")
                    expect(page.get_by_label("Chủ thể", exact=True)).to_be_disabled()
                    expect(page.get_by_role("slider")).to_have_count(0)
                    expect(page.get_by_label("Mô tả bổ sung cho ảnh", exact=True)).to_have_count(0)
                    person_picker = page.get_by_label("Ảnh người", exact=True)
                    garment_picker = page.get_by_label("Ảnh trang phục shop", exact=True)
                    assert person_picker.locator(f"option[value='{garment_id}']").count() == 0
                    assert garment_picker.locator(f"option[value='{person_id}']").count() == 0
                    create = page.get_by_role("button", name="Tạo ảnh", exact=True)
                    expect(create).to_be_disabled()
                    expect(page.get_by_text("Worker chưa hỗ trợ thử trang phục", exact=False)).to_be_visible()
                    person_picker.select_option(str(person_id)); garment_picker.select_option(str(garment_id))
                    expect(create).to_be_disabled()
                    vton_capability = True
                    page.get_by_role("button", name="Kiểm tra worker ảnh", exact=True).click()
                    expect(create).to_be_enabled()
                    create.click(); expect(create).to_be_disabled()
                    assert len(submissions) == 1 and len(generation_inputs) == 1
                    assert generation_inputs[0]["person_media_id"] == person_id
                    assert generation_inputs[0]["garment_media_id"] == garment_id
                    assert "reference_media_ids" not in generation_inputs[0]
                    assert generation_inputs[0]["prompt"] == ""
                    page.reload(); expect(create).to_be_disabled()
                    expect(page.get_by_label("Cách tạo ảnh", exact=True)).to_have_value("vton")
                    expect(person_picker).to_have_value(str(person_id)); expect(garment_picker).to_have_value(str(garment_id))
                    refresh = page.get_by_role("button", name="Kiểm tra kết quả (không tạo lại)", exact=True)
                    refresh.click(); expect(page.get_by_text("Đang tạo ảnh", exact=False).first).to_be_visible()
                    refresh.click(); expect(create).to_be_enabled()
                    assert len(submissions) == 1 and refresh_count == 2
                    with Session(engine) as db:
                        generated = db.exec(select(ProductionMedia).where(ProductionMedia.project_id == project_id, ProductionMedia.role == "portrait")).one()
                        generated_id = generated.id
                        assert (generated.width, generated.height) == (576, 864) and not generated.approved
                    expect(page.get_by_alt_text(f"Người gốc của ảnh {generated_id}", exact=True)).to_be_visible()
                    expect(page.get_by_alt_text(f"Sản phẩm shop gốc của ảnh {generated_id}", exact=True)).to_be_visible()
                    page.get_by_alt_text(f"Kết quả thử trang phục {generated_id}", exact=True).scroll_into_view_if_needed()
                    expect(page.get_by_alt_text(f"Kết quả thử trang phục {generated_id}", exact=True)).to_be_visible()
                    approved = page.get_by_label("Ảnh đã duyệt", exact=True)
                    assert approved.locator(f"option[value='{generated_id}']").count() == 0
                    fidelity = page.get_by_role("checkbox", name="Đã so với sản phẩm shop", exact=False)
                    for checkbox in page.get_by_role("checkbox").all():
                        # Check only base review, leave product fidelity unchecked.
                        if "Đã so với sản phẩm shop" not in checkbox.locator("..").inner_text():
                            checkbox.check()
                    review = page.get_by_role("button", name="Xác nhận đã kiểm tra", exact=True)
                    expect(review).to_be_disabled()
                    screenshots = Path("storage/verification/vton")
                    screenshots.mkdir(parents=True, exist_ok=True)
                    page.locator("article").filter(has=page.get_by_role("heading", name=f"So sánh ảnh thử trang phục #{generated_id}", exact=True)).screenshot(path=str(screenshots / "review.png"))
                    fidelity.check(); expect(review).to_be_enabled(); review.click()
                    expect(approved.locator(f"option[value='{generated_id}']")).to_have_count(1)
                    with Session(engine) as db:
                        receipt = json.loads(db.get(ProductionMedia, generated_id).review_json)
                        assert "garment_fidelity" in receipt["checklist"] and receipt["origin"]["generation_mode"] == "vton"
                    approved.select_option(str(generated_id))
                    page.get_by_label("ID dự án video nhận ảnh", exact=True).fill(str(target_id))
                    page.get_by_role("button", name="Dùng làm ảnh tham chiếu", exact=True).click()
                    expect(page.get_by_role("link", name="Mở dự án nhận ảnh", exact=True)).to_have_attribute("href", f"/production?project={target_id}")
                    assert promotions == [{"media_id": generated_id}]
                    with Session(engine) as db:
                        promoted = db.exec(select(ProductionMedia).where(ProductionMedia.project_id == target_id)).one()
                        assert promoted.role == "reference" and Path(promoted.path).is_file()
                        assert hashlib.sha256(Path(promoted.path).read_bytes()).hexdigest() == promoted.sha256
                    page.screenshot(path=str(screenshots / "desktop.png"), full_page=True)
                    page.set_viewport_size({"width": 390, "height": 844})
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Horizontal overflow"
                    page.screenshot(path=str(screenshots / "mobile.png"), full_page=True)
                    assert not page_errors, page_errors
                    assert not api_errors, api_errors
                    print(json.dumps({"browser": "Chromium", "api": "real isolated production/studio", "flow": "upload person + garment separately > old worker blocked > capability check > VTON > lost acknowledgement > reload > refresh > compare originals > fidelity gate > approve receipt > promote canonical reference > mobile", "generation_calls": len(submissions), "refresh_calls": refresh_count, "page_errors": page_errors, "api_errors": api_errors, "screenshots": str(screenshots)}))
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
