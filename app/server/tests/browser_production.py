"""Real management UI + API in temporary storage, no inference or user DB."""
import json
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from playwright.sync_api import expect, sync_playwright
from sqlmodel import Session, SQLModel, create_engine

from server.api.routes import production
from server.config import Settings
from server.tests.test_production import image_bytes


def main():
    with tempfile.TemporaryDirectory(prefix="aiflow-production-ui-") as directory:
        root = Path(directory)
        engine = create_engine(f"sqlite:///{root / 'test.db'}", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(engine)
        app = FastAPI()
        app.include_router(production.router)
        def sessions():
            with Session(engine) as db:
                yield db
        app.dependency_overrides[production.get_session] = sessions
        app.dependency_overrides[production.get_settings] = lambda: Settings(data_dir=root)
        with patch.object(production, "get_engine", return_value=engine), TestClient(app) as client, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            def handle(route):
                request = route.request
                url = urlsplit(request.url)
                if not url.path.startswith("/api/"):
                    route.continue_()
                    return
                if url.path == "/api/health":
                    route.fulfill(json={"extension_connected": False})
                    return
                response = client.request(request.method, url.path + ("?" + url.query if url.query else ""),
                    content=request.post_data_buffer, headers={"Content-Type": request.headers.get("content-type", "application/json"), "X-AIFlow-Client": "1"})
                route.fulfill(status=response.status_code, body=response.content, headers={"Content-Type": response.headers.get("content-type", "application/json")})
            page.route("**/api/**", handle)
            page.goto("http://127.0.0.1:5177/production")
            for name, value in [("Tên dự án", "Browser fixture"), ("Kênh / thương hiệu (tùy chọn)", "pets"), ("Loài / giống thú cưng", "Cat"), ("Phong cách", "Watercolor"), ("Đặc điểm nhận diện phải giữ", "Green eyes")]:
                page.get_by_label(name, exact=True).fill(value)
            page.get_by_role("button", name="Tạo dự án chân dung", exact=True).click()
            expect(page.get_by_role("heading", name="Browser fixture", exact=True)).to_be_visible()
            payload = {"name": "fixture.png", "mimeType": "image/png", "buffer": image_bytes()}
            page.get_by_label("Thêm ảnh tham chiếu", exact=False).set_input_files(payload)
            expect(page.get_by_alt_text("Ảnh tham chiếu", exact=False)).to_be_visible()
            page.get_by_label("Nhập chân dung", exact=False).set_input_files(payload)
            expect(page.get_by_alt_text("Ảnh cần duyệt", exact=False)).to_be_visible()
            for checkbox in page.get_by_role("checkbox").all():
                checkbox.check()
            page.get_by_role("button", name="Xác nhận đã kiểm tra", exact=True).click()
            expect(page.get_by_text("96 × 128px · Đã duyệt", exact=False)).to_be_visible()
            page.get_by_role("button", name="Xuất lượt mới", exact=True).click()
            page.get_by_role("button", name="Xem và duyệt", exact=True).click()
            expect(page.get_by_role("heading", name="Duyệt bộ file", exact=False)).to_be_visible()
            for checkbox in page.get_by_role("checkbox").all():
                checkbox.check()
            page.get_by_role("button", name="Xác nhận đã kiểm tra", exact=True).click()
            expect(page.get_by_role("link", name="Tải ZIP đã duyệt")).to_be_visible()
            screenshots = Path("storage/verification/production")
            screenshots.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(screenshots / "desktop.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Mobile overflow"
            page.screenshot(path=str(screenshots / "mobile.png"), full_page=True)
            for path, heading in [("/", "Hôm nay cần làm gì?"), ("/work-queue", "Tác vụ & khôi phục"), ("/library", "Thư viện theo dự án")]:
                page.goto("http://127.0.0.1:5177" + path)
                expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert not errors, errors
            browser.close()
            print(json.dumps({"flow": "create portrait > upload reference/art > review > render > final review > ZIP available", "page_errors": errors, "screenshots": str(screenshots)}, ensure_ascii=False))
        engine.dispose()


if __name__ == "__main__":
    main()
