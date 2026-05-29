# 09 — Phase 0 Execution Plan

> **Status**: Draft for review
> **Depends on**: spec 00-08 (đầy đủ)
> **Used by**: developer thực thi Phase 0

## Mục đích

Spec này dịch toàn bộ kiến trúc đã thiết kế (spec 00-08) thành **6 task cụ thể** cho Phase 0 — task đầu tiên thực sự đụng code.

Phase 0 mục tiêu duy nhất: **Extension capture được token Veo3 và agent gọi sinh được 1 image qua Python**.

KHÔNG mục tiêu Phase 0:
- Continuity engine (Phase 2)
- Audio (Phase 3)
- UI (Phase 5)
- Adapter framework (Phase 4)
- Database schema đầy đủ (chỉ skeleton subset)

## Tổng quan 6 task

| # | Task | Effort | Deliverable | Acceptance |
|---|------|--------|-------------|------------|
| 0.1 | Tạo skeleton folder + git + dependencies | 0.5 ngày | `app/` có structure đúng | `cd app && python -c "import server"` không lỗi |
| 0.2 | Lift extension và load Chrome | 0.5 ngày | Extension hiển thị "Disconnected" trong popup | `chrome://extensions` thấy AIFlow Bridge |
| 0.3 | Setup `.env` + Pydantic Settings + Gemini smoke test | 0.5 ngày | `python scripts/test_gemini.py` trả response | Không hardcode key |
| 0.4 | Implement `flow/client.py` + `ws_server.py` (lift từ flowboard) | 1 ngày | Extension popup → "Connected" | WS handshake OK |
| 0.5 | Implement `flow/sdk.py` minimal (chỉ `gen_image`) | 1 ngày | Gọi Veo3 sinh 1 ảnh | File PNG xuất hiện trong `storage/media/` |
| 0.6 | Smoke test end-to-end + viết Phase 0 acceptance script | 0.5 ngày | `scripts/smoke_phase0.py` pass | Output rõ ràng: ✅ tất cả check |

**Tổng**: ~4 ngày làm việc tập trung.

---

## Task 0.1 — Skeleton folder + dependencies

### Mục tiêu

Có folder `app/` với cấu trúc đúng spec 00, tất cả file Python rỗng (chỉ docstring) nhưng import được.

### Steps

1. **Tạo folder tree**: chạy script PowerShell tạo toàn bộ folder + `__init__.py` rỗng theo spec 00. Skip phần defer (ui/, adapters trừ skeleton, etc.).

2. **Tạo `pyproject.toml`** với dependencies tối thiểu:

```toml
[project]
name = "aiflow"
version = "0.1.0"
requires-python = ">=3.12"           # REVIEW-02 #1 — bumped từ 3.11 cho LMDeploy
dependencies = [
    "fastapi>=0.110.0",
    "uvicorn[standard]>=0.32.0",
    "pydantic>=2.7.0",
    "pydantic-settings>=2.4.0",
    "sqlmodel>=0.0.21",
    "httpx>=0.27.0",
    "websockets>=13.0",
    "python-dotenv>=1.0.0",
    "loguru>=0.7.3",
    "google-genai>=0.5.0",       # Gemini SDK chính thức
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "ruff>=0.5",
    "mypy>=1.10",
]

# Phase 3 dependencies (chưa cần Phase 0)
audio = [
    "edge-tts>=7.0",
    "faster-whisper>=1.1",
]

# Phase 3.5
visual = [
    "playwright>=1.45",
]

# Phase 4.5
remaster = [
    "yt-dlp>=2024.12",
    "browser-cookie3>=0.19",
    "gmssl>=3.2",
    "aiofiles>=23.2",
]
```

3. **Tạo `.gitignore`** theo spec 00.

4. **Tạo `.env.example`** theo spec 01.

5. **Tạo `LICENSE`** (Personal use disclaimer) và `LICENSE_NOTICES.md` (placeholder, chưa có third-party).

6. **Tạo `README.md`** root với:
   - 1-paragraph mô tả project
   - Link tới `docs/PLAN.md`
   - Quick start ngắn
   - Hard requirements: Python 3.11+, Chrome, Flow Pro plan, Gemini API key

7. **Setup venv + install**:
```powershell
cd D:\Project\AIFlow\app
py -3.12 -m venv .venv               # REVIEW-02 #1 — explicit Python 3.12
.venv\Scripts\activate
python --version                     # Verify: Python 3.12.x
pip install -e .[dev]
```

### Acceptance

```powershell
cd D:\Project\AIFlow\app
.venv\Scripts\activate

# Import works
python -c "import server; print(server.__name__)"

# Folder tree đúng
tree /F /A | findstr "server\|extension\|skills\|docs"

# pyproject ok
python -c "import tomllib; tomllib.load(open('pyproject.toml','rb'))"
```

Expected output:
- `server` import OK, no error
- Tree cho thấy đầy đủ folder
- `__init__.py` tồn tại trong mọi Python package

---

## Task 0.2 — Lift extension + load Chrome

### Mục tiêu

Có `extension/` directory load được vào Chrome, popup hiển thị, dù chưa connect được agent.

### Steps

1. **Lift files** từ `flowboard/extension/` về `app/extension/`:
   - `manifest.json` → ĐỔI: name="AIFlow Bridge", host_permissions thêm Bilibili+Douyin (theo spec 04)
   - `background.js` → giữ nguyên skeleton, sẽ refactor task 0.4
   - `content.js`, `injected.js` → lift nguyên
   - `popup.html`, `popup.js`, `popup.css` → lift, đổi branding
   - `rules.json` → mở rộng theo spec 04
   - `icons/` → tạm dùng icon placeholder (1 file SVG đơn giản)

2. **Refactor structure** theo spec 04:
   - Chia background.js thành `background.js` (entry) + `modules/flow_proxy.js` + `modules/shared.js`
   - Phase 0 KHÔNG cần `modules/cookie_sniffer.js` (defer Phase 4.5)

3. **Sửa hardcoded URL**:
   - `AGENT_WS_URL` = `ws://127.0.0.1:9223` (giống flowboard)
   - `CALLBACK_URL` = `http://127.0.0.1:8101/api/ext/callback`

4. **Test load**:
   - Mở Chrome → `chrome://extensions`
   - Bật Developer mode
   - Load unpacked → chọn `D:\Project\AIFlow\app\extension`
   - Extension xuất hiện, có icon, không error

5. **Test popup**:
   - Click icon → popup mở
   - Hiển thị "Disconnected" (vì agent chưa run)
   - Không lỗi JS console

### Acceptance

- Extension load không có error đỏ trong `chrome://extensions`
- Service worker active (click "service worker" link → DevTools)
- Popup mở được, hiển thị state "Disconnected"
- DevTools console không có error

---

## Task 0.3 — Config + Gemini smoke test

### Mục tiêu

`.env` load đúng, Pydantic validate, gọi được Gemini API thành công.

### Steps

1. **Implement `server/config.py`** theo spec 01:
   - `Settings` class (subset Phase 0: chỉ `host`, `port`, `ws_port`, `data_dir`, `gemini.api_key`, `flow.plan`, `gemini.model`)
   - Validation fail-fast nếu `AIFLOW_GEMINI_API_KEY` empty

2. **Implement `server/ai/gemini.py`** minimal:
   - Wrapper `google.genai.Client`
   - Method `generate_text(prompt: str) -> str`
   - Method `health_check() -> bool` (gọi 1 prompt nhỏ "say OK")

3. **Tạo file thật `app/.env`** (gitignored):
```
AIFLOW_GEMINI_API_KEY=AIzaSy...      # User điền
AIFLOW_FLOW_PLAN=Pro
```

4. **Viết script `app/scripts/test_gemini.py`**:
```python
"""Smoke test: load config, call Gemini once."""
import asyncio
from server.config import Settings
from server.ai.gemini import GeminiClient

async def main():
    settings = Settings()
    print(f"Gemini model: {settings.gemini.model}")
    print(f"API key configured: {bool(settings.gemini.api_key.get_secret_value())}")
    
    client = GeminiClient(settings.gemini)
    response = await client.generate_text("Say 'AIFlow ready' in one short sentence.")
    print(f"Response: {response}")
    
    assert "ready" in response.lower(), "Unexpected response"
    print("✅ Gemini smoke test passed")

if __name__ == "__main__":
    asyncio.run(main())
```

### Acceptance

```powershell
cd D:\Project\AIFlow\app
python scripts/test_gemini.py
```

Expected:
```
Gemini model: gemini-2.5-flash
API key configured: True
Response: AIFlow ready and operational.
✅ Gemini smoke test passed
```

Failure cases được handle:
- Missing API key → `ConfigError: AIFLOW_GEMINI_API_KEY required`
- Bad API key → `GeminiError: 401 unauthorized`
- Quota exceeded → `GeminiError: 429 rate limited`

---

## Task 0.4 — Flow client + WebSocket server

### Mục tiêu

Extension connect được vào agent qua WS, agent broadcast `callback_secret`, extension send `extension_ready` lại. Popup hiển thị "Connected".

### Steps

1. **Implement `server/flow/ws_server.py`** (lift từ flowboard `services/ws_server.py`):
   - WebSocket endpoint port 9223
   - Singleton FlowClient quản lý ws connection
   - Send `callback_secret` ngay khi extension connect
   - Listen `extension_ready`, `token_captured`, `pong`

2. **Implement `server/flow/client.py`** (lift từ flowboard `services/flow_client.py` SUBSET):
   - `FlowClient` singleton
   - Method `is_connected()` → bool
   - Method `wait_for_token()` → str (Bearer token)
   - State: callback_secret, captured token

3. **Implement `server/api/routes/health.py`** + `ext_callback.py` + `ext_discovery.py` (REVIEW-01 #2):
   - `GET /api/health` trả `{status: "ok", extension_connected: bool}`
   - `POST /api/ext/callback` verify `X-Callback-Secret`, route theo `request_id`
   - `GET /api/ext/discovery` (no auth) trả `{ws_port, ws_url, agent_version, ...}` — extension cần để biết WS port động

4. **Implement `server/main.py`**:
```python
"""AIFlow agent entry point."""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from server.config import load_settings
from server.db.session import bootstrap_schema
from server.flow.client import flow_client
from server.flow.ws_server import start_ws_server
from server.api.routes import health, ext_callback

settings = load_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    bootstrap_schema(settings)            # ← REVIEW-01 #1: DB bootstrap fail-fast
    log.info(f"DB ready: {settings.data_dir / 'projects.db'}")
    
    ws_task = asyncio.create_task(start_ws_server(settings.ws_port))
    
    # REVIEW-02 #7 — Background gate checker (Phase 2.2 mới activate, Phase 0 no-op)
    from server.pipeline.quality_gate import periodic_gate_checker
    gate_task = asyncio.create_task(periodic_gate_checker(settings, interval_sec=60))
    
    yield
    
    # Shutdown
    ws_task.cancel()
    gate_task.cancel()
    
    # TTS service close (Phase 3+)
    if hasattr(app.state, "tts"):
        await app.state.tts.close_all()

app = FastAPI(title="AIFlow Agent", version="0.1.0", lifespan=lifespan)
app.include_router(health.router, prefix="/api")
app.include_router(ext_callback.router, prefix="/api/ext")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server.main:app", host=settings.host, port=settings.port, reload=settings.debug)
```

Phase 0 skeleton cho `periodic_gate_checker`:

```python
# server/pipeline/quality_gate.py — Phase 0 no-op skeleton
import asyncio
import logging

log = logging.getLogger(__name__)


async def periodic_gate_checker(settings, interval_sec: int = 60):
    """Phase 2.2+ — Quét QualityGate expired (G2.8 SLA timeout, REVIEW-01 #7).
    Phase 0: no-op skeleton để lifespan không crash."""
    log.info(f"Gate checker started (interval={interval_sec}s)")
    while True:
        try:
            await asyncio.sleep(interval_sec)
            # Phase 2.2: thực hiện check_expired_gates() ở đây
            # await check_expired_gates(settings)
        except asyncio.CancelledError:
            log.info("Gate checker stopped")
            break
        except Exception as e:
            log.error(f"Gate checker error (continuing): {e}")
```

Tham chiếu: [spec 02 — Bootstrap & migration strategy](./02-db-schema.md#bootstrap--migration-strategy).

5. **Update extension `background.js`** (đã refactor task 0.2):
   - Implement WS connection với **discovery flow** (REVIEW-01 #2):
     - GET `http://127.0.0.1:8101/api/ext/discovery` retry 3s nếu agent chưa run
     - Parse `ws_url` từ response, connect WS tới đó
     - Re-discover khi WS close (agent có thể restart đổi port)
   - Receive `callback_secret`, store
   - Send `extension_ready`
   - Update popup state qua chrome.runtime.sendMessage

### Acceptance

```powershell
# Terminal 1: chạy agent
cd D:\Project\AIFlow\app
python -m server.main
# Output: "Uvicorn running on http://127.0.0.1:8101"
#         "WebSocket server listening on :9223"

# Terminal 2: test health
curl http://127.0.0.1:8101/api/health
# {"status":"ok","extension_connected":false,"version":"0.1.0"}

# Reload extension trong Chrome
# Popup → giờ hiển thị "Connected"

# Curl lại
curl http://127.0.0.1:8101/api/health
# {"status":"ok","extension_connected":true,...}
```

---

## Task 0.5 — Flow SDK minimal (gen_image)

### Mục tiêu

Agent gọi được Veo3 image gen API qua extension, lưu được file PNG về local.

### Steps

1. **Lift `server/flow/sdk.py`** từ `flowboard/agent/flowboard/services/flow_sdk.py`:
   - Chỉ giữ `gen_image()` method
   - `IMAGE_MODELS` dict với GEM_PIX_2 default
   - `resolve_image_model()` helper
   - **Bỏ** video gen + upload image + check_async (Phase 1+)

2. **Lift `gen_image` flow**:
   ```
   1. Get user info, ensure plan="Pro"|"Ultra"
   2. Get reCAPTCHA token via WS get_captcha
   3. POST aisandbox-pa.googleapis.com/v1/image:generateImage
      với prompt + model + captcha
   4. Response trả mediaId + signed URL
   5. Download image bytes về storage/media/{project_id}/
   ```

3. **Mở Flow tab** trong Chrome lúc test:
   - User mở `labs.google/fx/tools/flow` → token Bearer được capture
   - Extension báo `token_captured` lên agent

4. **Viết script `scripts/test_gen_image.py`**:
```python
"""Phase 0 acceptance: gen 1 image via Veo3."""
import asyncio
from pathlib import Path
from server.config import Settings
from server.flow.client import flow_client
from server.flow.sdk import gen_image

async def main():
    settings = Settings()
    
    # Wait extension connected + token captured
    await flow_client.wait_for_extension(timeout=30)
    await flow_client.wait_for_token(timeout=30)
    
    print("Extension connected, token captured.")
    
    # Gen 1 image
    out_dir = settings.data_dir / "media" / "phase0_test"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    result = await gen_image(
        prompt="A simple red cube on a white background, studio lighting, 3D render",
        aspect_ratio="9:16",
        output_dir=out_dir,
    )
    
    print(f"Image gen result: {result}")
    
    # Verify file exists
    assert result["local_path"].exists()
    assert result["local_path"].stat().st_size > 50000  # > 50KB
    
    print(f"✅ Gen image OK: {result['local_path']}")

if __name__ == "__main__":
    asyncio.run(main())
```

### Acceptance

```powershell
# Terminal 1: agent running
python -m server.main

# Terminal 2: gen test
python scripts/test_gen_image.py
```

Expected:
```
Extension connected, token captured.
Image gen result: {'media_id': '...', 'local_path': PosixPath('storage/media/phase0_test/img_xxx.png'), 'duration_ms': 8421}
✅ Gen image OK: storage\media\phase0_test\img_xxx.png
```

File PNG mở được, là ảnh red cube studio.

### Failure cases & mitigation

| Failure | Cause | Mitigation |
|---------|-------|-----------|
| Token không capture | User chưa mở Flow tab | Spec popup nói rõ "Open Flow tab to start" |
| 401 unauthorized | Token expired | Re-trigger từ extension, retry |
| 403 quota | Daily credits hết | Surface error rõ tới user |
| reCAPTCHA timeout | Page chưa load grecaptcha | Increase timeout 25s → 45s |
| Image bytes corrupt | Download interrupt | Verify size + retry 1 lần |

---

## Task 0.6 — Phase 0 acceptance script

### Mục tiêu

1 script chạy hết, output rõ ràng pass/fail mọi check Phase 0.

### Implementation `scripts/smoke_phase0.py`

```python
"""
Phase 0 acceptance smoke test.

Run after `python -m server.main` is up + extension loaded + Flow tab open.
"""
import asyncio
import sys
from pathlib import Path

import httpx

from server.config import Settings
from server.ai.gemini import GeminiClient
from server.flow.client import flow_client
from server.flow.sdk import gen_image


CHECKS = []

def check(name: str):
    def decorator(fn):
        async def wrapper():
            try:
                await fn()
                print(f"✅ {name}")
                return True
            except Exception as e:
                print(f"❌ {name}: {e}")
                return False
        CHECKS.append(wrapper)
        return wrapper
    return decorator


@check("Config loads from .env")
async def check_config():
    settings = Settings()
    assert settings.gemini.api_key.get_secret_value()
    assert settings.flow.plan in ("Pro", "Ultra")


@check("DB bootstrap succeeded (REVIEW-01 #1)")
async def check_db():
    from server.db.session import get_engine
    from server.db.models import Config
    from sqlmodel import Session, select
    
    settings = Settings()
    engine = get_engine(settings)
    with Session(engine) as session:
        version = session.exec(select(Config).where(Config.key == "schema_version")).first()
        assert version is not None, "schema_version missing — bootstrap failed"
        assert (settings.data_dir / "projects.db").exists()


@check("Agent server is reachable")
async def check_health():
    async with httpx.AsyncClient() as client:
        r = await client.get(f"http://127.0.0.1:8101/api/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"


@check("Extension is connected")
async def check_extension():
    async with httpx.AsyncClient() as client:
        r = await client.get(f"http://127.0.0.1:8101/api/health")
        data = r.json()
        assert data["extension_connected"] is True, "Extension not connected — load it in Chrome"


@check("Bearer token captured")
async def check_token():
    await asyncio.wait_for(flow_client.wait_for_token(), timeout=10)


@check("Gemini API works")
async def check_gemini():
    settings = Settings()
    client = GeminiClient(settings.gemini)
    response = await client.generate_text("Say 'AIFlow ready' in 3 words.")
    assert "ready" in response.lower()


@check("Veo3 image gen works")
async def check_image_gen():
    settings = Settings()
    out_dir = settings.data_dir / "media" / "phase0_test"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    result = await gen_image(
        prompt="A simple red cube on white background",
        aspect_ratio="9:16",
        output_dir=out_dir,
    )
    
    assert result["local_path"].exists()
    assert result["local_path"].stat().st_size > 50_000


async def main():
    print("=" * 60)
    print("AIFlow — Phase 0 Acceptance Smoke Test")
    print("=" * 60)
    print()
    
    results = []
    for chk in CHECKS:
        results.append(await chk())
    
    print()
    print("=" * 60)
    passed = sum(results)
    total = len(results)
    if passed == total:
        print(f"🎉 Phase 0 PASSED ({passed}/{total} checks)")
        sys.exit(0)
    else:
        print(f"💥 Phase 0 FAILED ({passed}/{total} checks)")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
```

### Acceptance

```powershell
python scripts/smoke_phase0.py
```

Expected output:
```
============================================================
AIFlow — Phase 0 Acceptance Smoke Test
============================================================

✅ Config loads from .env
✅ Agent server is reachable
✅ Extension is connected
✅ Bearer token captured
✅ Gemini API works
✅ Veo3 image gen works

============================================================
🎉 Phase 0 PASSED (6/6 checks)
```

---

## Tổng kết Phase 0

Sau Phase 0, project có:

| Component | State |
|-----------|-------|
| Folder structure | ✅ Đầy đủ skeleton |
| Config system | ✅ `.env` load + validate |
| Gemini client | ✅ Smoke test pass |
| Chrome extension | ✅ Load + connect WS |
| Flow client (WS bridge) | ✅ Token capture |
| Flow SDK (gen_image only) | ✅ Sinh được 1 image |
| Acceptance script | ✅ 6/6 checks pass |

Sau Phase 0, **đủ móng** để Phase 1 build core video flow:
- DB schema (Project + Job)
- gen_video i2v
- Polling + download
- CLI command `aiflow gen-clip`

Phase 0 KHÔNG có:
- Database (chỉ skeleton, không tables)
- UI
- ContentAdapter
- Continuity engine
- Audio
- Quality gates
- Visual layer
- Adapters

## Definition of Done cho Phase 0

- [ ] Tất cả 6 task pass acceptance
- [ ] `smoke_phase0.py` PASSED 6/6
- [ ] Git commit "Phase 0 complete" với tag `v0.1.0-phase0`
- [ ] `docs/PLAN.md` cập nhật trạng thái Phase 0 = ✅
- [ ] User hands-on test: chạy `smoke_phase0.py` thành công trên máy

## Phase 1 preview (sau Phase 0)

Phase 1 task list — chỉ làm sau khi Phase 0 done:

- 1.1 Setup SQLite schema (Project + Job + JobLog + Config)
- 1.2 Implement gen_video i2v trong flow/sdk.py
- 1.3 Polling + callback handler (lift batchCheckAsync logic)
- 1.4 CLI command `aiflow gen-clip --prompt "..." --start-image path`
- 1.5 First video output: 1 clip 8s mp4 từ Veo3
