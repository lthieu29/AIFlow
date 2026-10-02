# 00 — Folder Structure Spec

> **Status**: Draft for review
> **Author**: AIFlow design phase
> **Last updated**: 2026-05-26

## Mục đích

Định nghĩa cây thư mục đầy đủ cho project AIFlow tại `D:\Project\AIFlow\app\`.
Mỗi folder phải có lý do tồn tại rõ ràng và quan hệ với các spec khác.

## Nguyên tắc

1. **Single source of truth**: 1 logic = 1 file. Không duplicate code giữa adapters.
2. **Layered separation**: `flow` (Veo3) ≠ `ai` (Gemini) ≠ `audio` ≠ `render` ≠ `content`.
   Mỗi layer chỉ phụ thuộc layer dưới, không cross-import ngang.
3. **Adapter isolation**: mỗi `ContentAdapter` tự đóng gói trong sub-folder, có thể delete mà không break core.
4. **Skills as data**: skills/ là file `.md`, `.yaml`, `.json` thuần — KHÔNG chứa Python code.
5. **Storage tách khỏi code**: `storage/` không vào git, chứa SQLite + media bytes + outputs.
6. **Reference giữ nguyên**: 8 project gốc (`flowboard`, `hyperframes`, ..., `downkyi-2.0.x`) ở `D:\Project\AIFlow\` (cùng cấp với `app/`) — read-only reference, không sửa.

## Cây thư mục đầy đủ

```
D:\Project\AIFlow\
│
├── app\                                   ← PROJECT CHÍNH (mới, viết từ đầu, lift có chọn lọc)
│   │
│   ├── docs\                              ← Tất cả spec (file này nằm ở đây)
│   │   ├── 00-folder-structure.md
│   │   ├── 01-config-spec.md
│   │   ├── 02-db-schema.md
│   │   ├── 03-api-contract.md
│   │   ├── 04-extension-spec.md
│   │   ├── 05-content-adapter-spec.md
│   │   ├── 06-continuity-spec.md
│   │   ├── 07-quality-gate-spec.md
│   │   ├── 08-visual-layer-spec.md
│   │   ├── 09-phase0-execution.md
│   │   ├── PLAN.md                        ← Master plan, file đầu tiên user đọc
│   │   └── adr\                           ← Architecture Decision Records
│   │       ├── 0001-windows-native-not-wsl.md
│   │       ├── 0002-gemini-api-not-cli.md
│   │       ├── 0003-merge-extensions.md
│   │       └── 0004-douyin-api-over-ytdlp.md
│   │
│   ├── extension\                         ← Chrome MV3 extension (gộp Veo3 + cookie sniffer)
│   │   ├── manifest.json
│   │   ├── background.js                  ← Service worker chính
│   │   ├── content.js                     ← Inject vào labs.google
│   │   ├── injected.js                    ← MAIN world cho reCAPTCHA
│   │   ├── modules\
│   │   │   ├── flow_proxy.js              ← Module Veo3 (LIFT từ flowboard/extension/background.js)
│   │   │   ├── cookie_sniffer.js          ← Module cookie (LIFT từ Douyin_TikTok/chrome-cookie-sniffer)
│   │   │   └── shared.js                  ← WS connect + auth secret chung
│   │   ├── popup\
│   │   │   ├── popup.html
│   │   │   ├── popup.js
│   │   │   └── popup.css
│   │   ├── rules.json                     ← declarativeNetRequest CORS rules
│   │   ├── icons\
│   │   │   ├── icon16.png
│   │   │   ├── icon48.png
│   │   │   └── icon128.png
│   │   └── README.md                      ← User install guide
│   │
│   ├── server\                            ← Python backend (FastAPI agent)
│   │   ├── pyproject.toml
│   │   ├── requirements.txt
│   │   ├── .env.example                   ← Template, KHÔNG commit .env thật
│   │   │
│   │   ├── main.py                        ← Entry: uvicorn 127.0.0.1:8101
│   │   ├── config.py                      ← Pydantic Settings (load .env)
│   │   ├── logging_setup.py
│   │   │
│   │   ├── db\
│   │   │   ├── __init__.py
│   │   │   ├── session.py                 ← SQLModel engine + session
│   │   │   ├── models\                    ← Models package (REVIEW-02 #4)
│   │   │   │   ├── __init__.py            ← Re-export mọi class
│   │   │   │   ├── project.py             ← Project
│   │   │   │   ├── job.py                 ← Job, JobLog
│   │   │   │   ├── config.py              ← Config
│   │   │   │   ├── scene.py               ← Phase 2
│   │   │   │   ├── asset.py               ← Phase 2
│   │   │   │   ├── scene_asset.py         ← Phase 2
│   │   │   │   ├── style.py               ← Phase 2
│   │   │   │   ├── quality_gate.py        ← Phase 2
│   │   │   │   └── cookie.py              ← Phase 4.5
│   │   │   └── migrations\                ← Alembic migrations (Phase 1+)
│   │   │       └── README.md
│   │   │
│   │   ├── flow\                          ← Google Flow / Veo3 client (LIFT từ flowboard)
│   │   │   ├── __init__.py
│   │   │   ├── client.py                  ← WS bridge port 9223 (lift flow_client.py)
│   │   │   ├── sdk.py                     ← Veo3 i2v + image gen (lift flow_sdk.py)
│   │   │   ├── ws_server.py               ← WebSocket server cho extension
│   │   │   └── models.py                  ← Pydantic types cho Flow API
│   │   │
│   │   ├── ai\                            ← LLM client + prompt synthesis
│   │   │   ├── __init__.py
│   │   │   ├── gemini.py                  ← Gemini API client (free tier)
│   │   │   ├── vision.py                  ← Vision describe (Gemini Vision)
│   │   │   ├── prompts\
│   │   │   │   ├── __init__.py
│   │   │   │   ├── shot_synth.py          ← Mỗi scene → Veo3 prompt (port flowboard/prompt_synth.py)
│   │   │   │   ├── continuity.py          ← 4 lớp continuity (xem docs/06)
│   │   │   │   ├── style_lock.py          ← Lớp 1
│   │   │   │   ├── asset_lock.py          ← Lớp 2
│   │   │   │   ├── scene_chain.py         ← Lớp 3
│   │   │   │   └── audio_continuity.py    ← Lớp 4
│   │   │   └── tokens.py                  ← Token counter, context budget
│   │   │
│   │   ├── audio\                         ← TTS + transcribe (LIFT từ MoneyPrinterTurbo)
│   │   │   ├── __init__.py
│   │   │   ├── tts\                       ← TTS providers (Phase 3, spec 10)
│   │   │   │   ├── __init__.py            ← Protocol + TTSResult + TTSError
│   │   │   │   ├── service.py             ← TTSService orchestrator
│   │   │   │   ├── vieneu_provider.py
│   │   │   │   ├── edge_provider.py
│   │   │   │   ├── voice_catalog.py       ← VoiceInfo + PRESET_VOICE_METADATA
│   │   │   │   └── voice_metadata.py
│   │   │   ├── ffmpeg_utils.py            ← Audio-specific: probe_duration, encode mp3 (REVIEW-02 #9)
│   │   │   ├── transcribe.py              ← faster-whisper wrapper
│   │   │   └── tts_legacy.py              ← edge_tts standalone (Phase 3.1 fallback)
│   │   │
│   │   ├── render\                        ← Final video composition
│   │   │   ├── __init__.py
│   │   │   ├── composer.py                ← Orchestrate ffmpeg (port daihuo composer.ts)
│   │   │   ├── ffmpeg_utils.py            ← Subprocess wrapper, escape utils
│   │   │   ├── transitions.py             ← Preset library
│   │   │   ├── motions.py                 ← Ken Burns motion presets
│   │   │   └── visual_layer\              ← Mini-hyperframes (xem docs/08)
│   │   │       ├── __init__.py
│   │   │       ├── playwright_renderer.py ← HTML+GSAP → mp4 với alpha
│   │   │       ├── hf_protocol.py         ← `window.__hf` contract types
│   │   │       ├── overlay_compositor.py  ← Overlay lên Veo3 video
│   │   │       └── templates\             ← HTML+GSAP templates (data, không phải code)
│   │   │           ├── intro_card.html
│   │   │           ├── outro_card.html
│   │   │           ├── lower_third.html
│   │   │           ├── chapter_title.html
│   │   │           └── product_card.html
│   │   │
│   │   ├── content\                       ← ContentAdapter framework (xem docs/05)
│   │   │   ├── __init__.py
│   │   │   ├── base.py                    ← Interface ContentAdapter, dataclass
│   │   │   ├── registry.py                ← Auto-discover adapters
│   │   │   ├── shared\                    ← Logic share giữa adapters
│   │   │   │   ├── __init__.py
│   │   │   │   ├── character_dedup.py
│   │   │   │   ├── duration_estimator.py
│   │   │   │   ├── llm_chunking.py
│   │   │   │   └── srt_utils.py
│   │   │   └── adapters\                  ← Mỗi adapter một sub-folder
│   │   │       ├── __init__.py
│   │   │       ├── script_direct\
│   │   │       │   ├── __init__.py
│   │   │       │   └── adapter.py
│   │   │       ├── ecommerce_product\
│   │   │       │   ├── __init__.py
│   │   │       │   ├── adapter.py
│   │   │       │   ├── prompts.py         ← PORT từ daihuo prompts.ts
│   │   │       │   └── templates\
│   │   │       │       └── README.md
│   │   │       ├── narrative_script\
│   │   │       │   └── (Phase 4.2)
│   │   │       ├── blog_article\
│   │   │       │   └── (Phase 4.3)
│   │   │       ├── storyboard_manual\
│   │   │       │   └── (Phase 4.4)
│   │   │       ├── video_remaster\        ← Phase 4.5 — Bilibili/Douyin
│   │   │       │   ├── __init__.py
│   │   │       │   ├── adapter.py
│   │   │       │   ├── url_router.py
│   │   │       │   ├── downloaders\
│   │   │       │   │   ├── base.py
│   │   │       │   │   ├── douyin.py      ← LIFT Douyin_TikTok_API/crawlers/douyin
│   │   │       │   │   ├── bilibili.py    ← LIFT Douyin_TikTok_API/crawlers/bilibili
│   │   │       │   │   ├── tiktok.py
│   │   │       │   │   └── generic.py     ← yt-dlp fallback
│   │   │       │   ├── signing\
│   │   │       │   │   ├── abogus.py      ← LIFT (GPL v3 — xem LICENSE_NOTICES)
│   │   │       │   │   ├── xbogus.py      ← LIFT
│   │   │       │   │   └── wbi.py         ← LIFT
│   │   │       │   ├── cookies\
│   │   │       │   │   ├── manager.py
│   │   │       │   │   └── browser_cookie.py
│   │   │       │   ├── stream_merger.py
│   │   │       │   ├── subtitle_extractor.py
│   │   │       │   ├── translator.py
│   │   │       │   ├── remaster.py
│   │   │       │   └── presets.py
│   │   │       └── epub_novel\            ← Phase 6
│   │   │           └── (Phase 6)
│   │   │
│   │   ├── export\                        ← Export định dạng khác (LIFT VectCutAPI)
│   │   │   ├── __init__.py
│   │   │   ├── capcut.py                  ← Export CapCut draft (Phase 7)
│   │   │   └── srt_export.py
│   │   │
│   │   ├── pipeline\                      ← Orchestration
│   │   │   ├── __init__.py
│   │   │   ├── orchestrator.py            ← Run full flow: idea → final.mp4
│   │   │   ├── quality_gate.py            ← G1-G6 (xem docs/07)
│   │   │   ├── job_queue.py               ← In-process worker queue
│   │   │   └── events.py                  ← Event bus cho UI live updates
│   │   │
│   │   ├── api\                           ← FastAPI routes
│   │   │   ├── __init__.py
│   │   │   ├── routes\
│   │   │   │   ├── __init__.py
│   │   │   │   ├── projects.py
│   │   │   │   ├── scenes.py
│   │   │   │   ├── assets.py
│   │   │   │   ├── jobs.py
│   │   │   │   ├── ext_callback.py        ← Extension callback receiver
│   │   │   │   ├── content.py             ← /api/content/parse
│   │   │   │   └── health.py
│   │   │   └── deps.py                    ← FastAPI dependencies
│   │   │
│   │   ├── tests\                         ← Pytest
│   │   │   ├── __init__.py
│   │   │   ├── conftest.py
│   │   │   ├── test_flow_client.py
│   │   │   ├── test_gemini.py
│   │   │   ├── test_continuity.py
│   │   │   ├── test_quality_gate.py
│   │   │   ├── test_adapters\
│   │   │   │   └── ...
│   │   │   └── fixtures\
│   │   │       ├── sample_script.json
│   │   │       └── sample_image.png
│   │   │
│   │   └── scripts\                       ← Dev / smoke test scripts
│   │       ├── smoke_phase0.py            ← Phase 0 acceptance test
│   │       ├── check_upstream_updates.py  ← Theo dõi Douyin_TikTok_API rotate signing
│   │       └── seed_db.py
│   │
│   ├── ui\                                ← React + Vite frontend (Phase 5)
│   │   ├── package.json
│   │   ├── vite.config.ts
│   │   ├── tsconfig.json
│   │   ├── index.html
│   │   ├── src\
│   │   │   ├── main.tsx
│   │   │   ├── App.tsx
│   │   │   ├── api.ts                     ← Axios client tới agent
│   │   │   ├── pages\
│   │   │   │   ├── new-project.tsx
│   │   │   │   ├── timeline.tsx
│   │   │   │   └── export.tsx
│   │   │   ├── components\
│   │   │   └── store.ts                   ← Zustand
│   │   └── public\
│   │
│   ├── skills\                            ← Skill packs (data, không code)
│   │   ├── README.md                      ← Skill author guide
│   │   ├── _base\                         ← Shared rules cho mọi skill
│   │   │   ├── camera_lock.md
│   │   │   ├── safety.md
│   │   │   └── continuity.md
│   │   ├── ecommerce-fashion\             ← Skill MVP đầu tiên
│   │   │   ├── manifest.yaml
│   │   │   ├── style.json
│   │   │   ├── prefix.md
│   │   │   ├── character.md
│   │   │   ├── scene.md
│   │   │   ├── motion.md
│   │   │   └── voice.yaml
│   │   ├── kdrama-romance\                ← Phase 6 (cho epub)
│   │   ├── explainer-tech\
│   │   └── cinematic-action\
│   │
│   ├── storage\                           ← KHÔNG vào git
│   │   ├── .gitkeep
│   │   ├── projects.db                    ← SQLite chính
│   │   ├── media\                         ← Cache image/video bytes từ Veo3
│   │   │   └── {project_id}\
│   │   ├── output\                        ← Final mp4 + assets
│   │   │   └── {project_id}\
│   │   ├── cookies\                       ← Bilibili/Douyin cookies (sensitive)
│   │   │   ├── bilibili.txt
│   │   │   └── douyin.txt
│   │   └── logs\
│   │       └── agent.log
│   │
│   ├── vendor\                            ← Binary deps (Windows native)
│   │   ├── README.md
│   │   ├── ffmpeg.exe                     ← Pinned version 7.0+
│   │   ├── ffprobe.exe
│   │   └── aria2c.exe                     ← LIFT từ downkyi-2.0.x/third_party
│   │
│   ├── .gitignore
│   ├── .env.example
│   ├── README.md
│   ├── LICENSE
│   ├── LICENSE_NOTICES.md                 ← Third-party origins (GPL/Apache)
│   └── Makefile                           ← Make targets cho Windows (sử dụng `make` hoặc `task`)
│
├── _legacy\                               ← Sau khi MVP done, archive 6 project cũ vào đây
│   └── (rỗng cho đến khi MVP xong)
│
├── flowboard\                             ← Reference (read-only)
├── hyperframes\                           ← Reference
├── MoneyPrinterTurbo\                     ← Reference
├── daihuo-jianshou\                       ← Reference
├── VectCutAPI\                            ← Reference
├── Toonflow-app\                          ← Reference
├── Galaxy-downloader-Ultimate-V23.0\      ← Reference (tham khảo cookie pattern)
├── Galaxy-Bilibili-Downloader\            ← Reference (tham khảo aria2c)
├── Galaxy-Douyin-Ultimate-Studio-2026\    ← Reference (binary only, không lift)
├── Douyin_TikTok_Download_API\            ← REFERENCE QUAN TRỌNG NHẤT cho video-remaster
├── downkyi-2.0.x\                         ← Reference (BvId algorithm)
└── security.md                            ← Note bảo mật chung của AIFlow
```

## Naming conventions

### Folders
- **snake_case** cho Python: `video_remaster`, `script_direct`
- **kebab-case** cho user-facing: `ecommerce-fashion`, `kdrama-romance`
- **camelCase**: KHÔNG dùng

### Files
- Python: `snake_case.py`
- TypeScript/React: `kebab-case.tsx` cho pages, `PascalCase.tsx` cho components
- Markdown spec: `NN-name.md` với prefix số (ordering)
- Config: `.env`, `manifest.yaml`, `style.json`

### Env vars
- `AIFLOW_*` prefix tất cả (tránh xung đột)
- VD: `AIFLOW_GEMINI_API_KEY`, `AIFLOW_FLOW_PLAN`

## Constraint quan trọng

### Folders KHÔNG được chứa code
- `skills/` — chỉ file `.md`, `.yaml`, `.json`, `.txt`
- `storage/` — chỉ runtime data, không source
- `vendor/` — chỉ binary
- `docs/` — chỉ Markdown

### File phải có ở Phase 0 (skeleton, không cần content đầy đủ)
- Mọi file `__init__.py` (Python package marker)
- Mọi `README.md` ở folder con quan trọng (1-2 dòng mô tả)
- `.gitignore`
- `.env.example`
- `pyproject.toml`
- `LICENSE`, `LICENSE_NOTICES.md`

### File DEFER tới Phase tương ứng
- Toàn bộ `ui/` → Phase 5
- `db/migrations/` → Phase 1.1 (khi có schema)
- Adapter folders trừ `script_direct` và `ecommerce_product` skeleton → Phase tương ứng

## .gitignore cần có

```
# Python
__pycache__/
*.pyc
*.pyo
.pytest_cache/
.mypy_cache/
.ruff_cache/

# Virtual env
.venv/
venv/

# Storage (runtime data + secrets)
storage/
!storage/.gitkeep

# Secrets
.env
.env.local
*.pem
*.key

# Cookies (tránh leak personal cookies)
storage/cookies/

# IDE
.vscode/
.idea/
*.swp

# OS
Thumbs.db
.DS_Store

# Build
dist/
build/
*.egg-info/

# UI
ui/node_modules/
ui/dist/

# Vendor lớn — quyết định sau (xem ADR 0005)
# vendor/*.exe   ← KHÔNG ignore, ship theo project (Phase 0 quyết)
```

## ADR records cần viết

Mỗi quyết định kiến trúc lớn = 1 file ADR. Ban đầu cần:

| ADR | Tên | Quyết định |
|-----|-----|------------|
| 0001 | Native Windows, không WSL | Người dùng đã xác nhận |
| 0002 | Gemini API trực tiếp, không CLI | Free tier AI Studio đủ dùng |
| 0003 | Gộp 2 Chrome extensions | Người dùng đã xác nhận |
| 0004 | Douyin_TikTok_API thay yt-dlp | Có signing thuần Python |
| 0005 | Ship FFmpeg/aria2c binary | Pin version, tránh PATH issue |

Mỗi ADR ~1 trang: Context + Decision + Consequences.

## Acceptance criteria cho spec này

- [ ] Người mới đọc folder structure hiểu được layer nào làm gì
- [ ] Mỗi folder có thể truy ngược về 1 spec hoặc Phase
- [ ] Không có folder nào "thập cẩm" — mỗi folder 1 chức năng
- [ ] Đường đi từ entry (`main.py`) tới mọi feature đều rõ ràng
- [ ] Phần lift code từ project cũ ghi rõ origin (LIFT from `xyz`)

## Next steps sau khi spec này được approve

1. Viết spec 01 (config) → biết env vars cần gì
2. Viết spec 02 (db) → biết models cần gì
3. ...spec khác...
4. Review tổng `PLAN.md`
5. CHỈ KHI USER APPROVE PLAN.md → bắt đầu Phase 0 task 0.1 (tạo skeleton)
