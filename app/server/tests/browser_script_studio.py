"""Run manually against Vite: python -m server.tests.browser_script_studio.

Real React UI + real script API routed to a temporary DB. No production server/inference.
Requires the optional Playwright package and its Chromium browser.
"""

import json
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright, expect
from sqlmodel import Session, SQLModel, create_engine

from server.api.routes import scripts
from server.tests.test_script_studio import create_script


def main():
    with tempfile.TemporaryDirectory(prefix="aiflow-script-ui-") as folder:
        engine = create_engine(f"sqlite:///{Path(folder) / 'scripts.db'}", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(engine)
        app = FastAPI()
        app.include_router(scripts.router)
        def session():
            with Session(engine) as db:
                yield db
        app.dependency_overrides[scripts.get_session] = session
        def forbidden(*args, **kwargs):
            raise AssertionError("Browser smoke must never call inference")
        original = scripts.provider.generate_structured
        scripts.provider.generate_structured = forbidden
        try:
            with TestClient(app, headers={"X-AIFlow-Client": "1"}) as client, sync_playwright() as playwright:
                _, draft = create_script(client)
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                def route_api(route):
                    request = route.request
                    url = urlsplit(request.url)
                    if not url.path.startswith("/api/"):
                        route.continue_()
                        return
                    if url.path == "/api/health":
                        route.fulfill(json={"extension_connected": False})
                        return
                    response = client.request(request.method, url.path + ("?" + url.query if url.query else ""),
                        content=request.post_data, headers={"Content-Type": "application/json", "X-AIFlow-Client": "1"})
                    route.fulfill(status=response.status_code, body=response.content,
                                  headers={"Content-Type": "application/json"})
                page.route("**/api/**", route_api)
                page.goto(f"http://127.0.0.1:5177/scripts?revision={draft['id']}")
                expect(page.get_by_role("heading", name="Kịch bản & phiên bản")).to_be_visible()
                expect(page.get_by_role("heading", name="Kiểm tra trước sản xuất", exact=False)).to_be_visible()
                page.get_by_text("Sửa từng cảnh trực tiếp", exact=True).click()
                page.get_by_label("Cảnh thay đổi điều gì?").first.fill("A missing hour forces Mara to investigate the locked cabinet.")
                page.get_by_role("button", name="Lưu bản sửa mới", exact=True).click()
                expect(page.get_by_role("status").first).to_contain_text("Đã lưu bản sửa mới")
                expect(page.get_by_text("A missing hour forces Mara", exact=False).first).to_be_visible()
                for checkbox in page.get_by_role("checkbox").all():
                    checkbox.check()
                page.get_by_role("button", name="Duyệt phiên bản", exact=False).click()
                expect(page.get_by_role("button", name="Tạo dự án từ bản đã duyệt", exact=True)).to_be_visible()
                output = Path("storage/verification/script-studio")
                output.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(output / "desktop.png"), full_page=True)
                page.set_viewport_size({"width": 390, "height": 844})
                page.screenshot(path=str(output / "mobile.png"), full_page=True)
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "Horizontal overflow"
                assert not errors, errors
                page.get_by_role("button", name="Tạo dự án từ bản đã duyệt", exact=True).click()
                page.wait_for_url("**/timeline/*")
                browser.close()
                print(json.dumps({"browser": "chromium", "desktop": "1440x1000", "mobile": "390x844",
                    "flow": "load > edit scene > save new revision > quality > checklist > approve > create project",
                    "page_errors": errors, "screenshots": str(output)}, ensure_ascii=False))
        finally:
            scripts.provider.generate_structured = original
            engine.dispose()


if __name__ == "__main__":
    main()
