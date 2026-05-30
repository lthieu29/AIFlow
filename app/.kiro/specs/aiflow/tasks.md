# Implementation Plan

## Overview

AIFlow is a personal AI video generation tool (Windows-native) that transforms inputs into polished videos using Google Veo3 + Gemini + TTS. Implementation is organized in phases: Phase 0 (foundation), Phase 1 (core video), Phase 2 (continuity), Phase 3 (audio/visual), Phase 4 (adapters), Phase 5 (UI), Phase 6 (epub), Phase 7 (export).

**Spec source**: docs/PLAN.md + spec 00-11  
**MVP boundary** (Phase 0 → 4.5): ~7.5 weeks  
**Full v1.0** (Phase 0 → 7): ~11 weeks

## Tasks

### Phase 0 — Setup nền tảng

- [x] 1. Task 0.1 — Skeleton folder + dependencies
  - Create folder tree per spec 00 (server/, extension/, ui/, skills/, storage/, vendor/, docs/)
  - Create all `__init__.py` for Python packages (20 files)
  - Create `pyproject.toml` with Python 3.12+ + dependencies
  - Create `.gitignore`, `.env.example`, `LICENSE`, `LICENSE_NOTICES.md`, `README.md`
  - Setup venv `.venv/` and install dependencies `pip install -e .[dev]`
  - Verify `python -c "import server"` works
  - **Acceptance**: Folder structure matches spec 00, import test passes ✅

- [x] 2. Task 0.2 — Lift extension + load Chrome
  - Lift files from `flowboard/extension/` to `app/extension/`
  - Update `manifest.json`: name="AIFlow Bridge", add host_permissions for Bilibili/Douyin (spec 04)
  - Refactor `background.js` → `background.js` + `modules/flow_proxy.js` + `modules/shared.js`
  - Lift `content.js`, `injected.js` (reCAPTCHA MAIN world)
  - Lift + rebrand `popup/popup.html`, `popup.js`, `popup.css`
  - Update `rules.json` (declarativeNetRequest CORS)
  - Create placeholder icons SVG (16/48/128)
  - Hardcode `AGENT_DISCOVERY_URL=http://127.0.0.1:8101/api/ext/discovery`
  - Implement `discoverAttempts` UX: 0-4 = "Connecting...", 5+ = "Agent not running" hint
  - Skip `cookie_sniffer.js` (defer Phase 4.5)
  - **Acceptance**: Extension loads without red errors, service worker active, popup opens

- [x] 3. Task 0.3 — Config + Pydantic Settings + Gemini smoke test
  - Implement `server/config.py` per spec 01: `Settings` class with host/port/ws_port/data_dir/debug, nested `GeminiSettings` and `FlowSettings`
  - Validation fail-fast: missing `AIFLOW_GEMINI_API_KEY` → raise immediately
  - Auto `mkdir -p data_dir` if not exists
  - Test 3 Pydantic env loading cases: single underscore key, .env file priority, missing key raises `ConfigError`
  - Implement `server/ai/gemini.py` minimal: `GeminiClient` wrapper, `generate_text(prompt)`, `health_check()`, friendly error messages for 401/429/network
  - Create `.env` file (gitignored) with API key
  - Write `scripts/test_gemini.py` smoke test
  - **Acceptance**: `python scripts/test_gemini.py` returns "AIFlow ready" ✅
  - **Depends on**: Task 0.1

- [x] 4. Task 0.4 — Flow client + WebSocket server
  - Implement `server/db/session.py`: `get_engine(settings)`, `bootstrap_schema(settings)` idempotent create_all, set `schema_version` in Config table
  - Implement Phase 0 models in `server/db/models/`: `project.py` (Project), `job.py` (Job, JobLog), `config.py` (Config), `__init__.py` re-exporting all
  - Implement `server/flow/ws_server.py`: WebSocket endpoint port 9223, send `callback_secret` on connect, listen `extension_ready`/`token_captured`/`pong`
  - Implement `server/flow/client.py`: `FlowClient` singleton, `is_connected()`, `wait_for_token()`, `wait_for_extension(timeout)`
  - Implement `server/api/routes/health.py`: `GET /api/health` returning status + extension_connected
  - Implement `server/api/routes/ext_callback.py`: `POST /api/ext/callback` verifying `X-Callback-Secret`
  - Implement `server/api/routes/ext_discovery.py`: `GET /api/ext/discovery` (no auth) returning ws_port
  - Implement `server/main.py`: FastAPI app with lifespan, startup: bootstrap_schema → ws_task → gate_task, register routes
  - Implement `server/pipeline/quality_gate.py`: `periodic_gate_checker()` Phase 0 no-op skeleton
  - Implement `server/logging_setup.py` — loguru config
  - Update extension `background.js` discovery flow: GET `/api/ext/discovery` retry 3s, parse ws_url, connect WS, receive callback_secret, send extension_ready
  - **Acceptance**: `python -m server.main` runs on ports 8101+9223, `/api/health` returns ok, extension popup shows "Connected", DB file has 4 tables
  - **Depends on**: Task 0.2, Task 0.3

- [x] 5. Task 0.5 — Flow SDK minimal — gen_image
  - Lift `server/flow/sdk.py` from `flowboard/agent/.../flow_sdk.py`: keep only `gen_image()`, `IMAGE_MODELS` dict with GEM_PIX_2 default, `resolve_image_model()` helper
  - Implement gen_image flow: get user info, ensure plan=Pro/Ultra, get reCAPTCHA token via WS, POST to aisandbox-pa.googleapis.com, parse response → mediaId + signed URL, download bytes to `storage/media/{project_id}/`, verify file size > 50KB
  - Write `scripts/test_gen_image.py`: wait extension connected + token captured, call gen_image with test prompt, assert file exists + size OK
  - **Acceptance**: `python scripts/test_gen_image.py` generates 1 PNG ✅
  - **Depends on**: Task 0.4

- [x] 6. Task 0.6 — Phase 0 acceptance smoke test
  - Implement `server/scripts/smoke_phase0.py` with 7 checks: Config loads from .env, DB bootstrap succeeded, Agent server reachable, Extension connected, Bearer token captured, Gemini API works, Veo3 image gen works
  - Output ✅/❌ per check + summary, exit code 0 = all pass / 1 = any fail
  - Update `docs/PLAN.md` status table → Phase 0 ✅
  - **Acceptance**: `python scripts/smoke_phase0.py` → `🎉 Phase 0 PASSED (7/7 checks)`
  - **Depends on**: Task 0.5

### Phase 1 — Core video flow

- [x] 7. Task 1.1 — SQLite schema full Phase 1 subset
  - Setup Alembic: `alembic init server/db/migrations`
  - First migration `0001_phase0_schema.py`: Project + Job + JobLog + Config (already from Phase 0)
  - State machine for Job: pending → running → success/failed
  - Add indexes per spec 02
  - **Depends on**: Task 0.6

- [x] 8. Task 1.2 — Implement gen_video i2v
  - Extend `server/flow/sdk.py`: `gen_video(start_image, prompt, duration=8, aspect="9:16")`, async submission returning `operation_name`, poll `check_async(operation_name)` every 5s
  - Update `IMAGE_MODELS` + `VIDEO_MODELS` registry
  - **Depends on**: Task 1.1

- [x] 9. Task 1.3 — Polling + callback handler
  - Lift `batchCheckAsync` logic from flowboard
  - Background task watching pending operations (`server/pipeline/poller.py`)
  - Update Job status on completion
  - Download video bytes to `storage/media/`
  - **Depends on**: Task 1.2

- [x] 10. Task 1.4 — CLI command `aiflow gen-clip`
  - Click-based CLI entrypoint (`server/cli.py`)
  - Args: `--prompt "..." --start-image path --output path`
  - Progress bar (tqdm)
  - Save Job + JobLog to DB
  - **Depends on**: Task 1.3

- [x] 11. Task 1.5 — First video output end-to-end test
  - End-to-end test: input image + prompt → 8s mp4
  - Verify quality, no broken frames
  - **Acceptance**: 1 clip mp4 8 seconds from CLI ✅
  - **Depends on**: Task 1.4

### Phase 2 — Continuity engine 4 lớp

- [x] 12. Task 2.1 — Models đầy đủ Phase 2
  - `Scene` model (project, order, duration, status, location_hint Literal enum)
  - `Asset` model (project, name, type, ref_url, source)
  - `SceneAsset` many-to-many with role
  - `Style` model (project, json field — Layer 1 continuity)
  - `QualityGate` model (gate_id, scene_id?, status, score, expired_at)
  - Alembic migration `0002_phase2_models.py`
  - **Depends on**: Task 1.5

- [x] 13. Task 2.2 — 4 lớp continuity
  - Layer 1 Style Lock (`server/ai/prompts/style_lock.py`): load `style.json` from skill, inject into every Veo3 prompt
  - Layer 2 Asset Lock (`server/ai/prompts/asset_lock.py`): pin character ref images, pin product/location refs, hard anchor in prompt template
  - Layer 3 Scene Chain (`server/ai/prompts/scene_chain.py`): `start_frame` = last frame of scene N-1, reset chain when `location_hint` changes
  - Layer 4 Audio Continuity (`server/ai/prompts/audio_continuity.py`): audio plan (BGM mood, voice tone), sync with scene timing
  - **Depends on**: Task 2.1

- [x] 14. Task 2.3 — Quality Gates G1-G3
  - G1: Validate SceneList structure (`pipeline/gates/g1_scene_list.py`)
  - G2: User approve asset refs (`pipeline/gates/g2_asset_approval.py`) with G2.8 SLA timeout via `check_expired_gates()`
  - G3: Per-scene quality (`pipeline/gates/g3_scene_quality.py`) — auto retry max 2, bounded cascade depth limit
  - **Depends on**: Task 2.2

- [x] 15. Task 2.4 — Pipeline orchestrator
  - `server/pipeline/orchestrator.py`: run full flow SceneList → 5 clips, sequential scene gen (chain), job queue via `job_manager.py`, event bus (`event_bus.py`) for UI updates
  - **Acceptance**: 5 scenes seamless in character + style ✅
  - **Depends on**: Task 2.3

### Phase 3.1 — TTS provider + edge_tts

- [x] 16. Task 3.1.1 — TTS provider abstraction
  - `server/audio/tts/__init__.py` — Protocol `TTSProvider` + `TTSResult` + `TTSError`
  - `BackendName` Literal type
  - Fallback chain definition
  - **Depends on**: Task 2.4

- [x] 17. Task 3.1.2 — EdgeProvider implementation
  - `server/audio/tts/edge_provider.py` (lift from MoneyPrinterTurbo)
  - `is_available() -> bool` (network check)
  - `synthesize(text, voice, output_path, speed)` → MP3 192kbps mono 24kHz
  - `probe_duration()` from `server/audio/ffmpeg_utils.py`
  - **Depends on**: Task 3.1.1

- [x] 18. Task 3.1.3 — TTSService orchestrator
  - `server/audio/tts/service.py`
  - Load preference from skill + project + .env
  - Try primary → fallback chain
  - Audit log every attempt
  - **Depends on**: Task 3.1.2

- [x] 19. Task 3.1.4 — Pipeline TTS integration
  - Hook into orchestrator: full_narration → audio.mp3
  - Smoke test with 1 Vietnamese voice (`vi-VN-HoaiMyNeural`)
  - **Depends on**: Task 3.1.3

### Phase 3.2 — VieNeu-TTS local + Voice Catalog

- [x] 20. Task 3.2.1 — VieNeuProvider
  - `server/audio/tts/vieneu_provider.py`
  - Auto-detect device: cuda → cpu
  - 4 backends: `vieneu_gpu_lmdeploy`, `vieneu_gpu_gguf`, `vieneu_cpu_standard`, `vieneu_cpu_turbo`
  - Model download lazy (first call)
  - LMDeploy only loads if Python 3.12+ (already satisfied ✅)
  - **Depends on**: Task 3.1.4

- [x] 21. Task 3.2.2 — Voice catalog
  - `server/audio/tts/voice_catalog.py`: `VoiceInfo` Pydantic BaseModel (NOT dataclass), `PRESET_VOICE_METADATA` for preset voices
  - `server/audio/tts/voice_metadata.py`
  - Helpers: `_load_custom_catalog()`, `_get_or_load_vieneu()`
  - Pre-gen demo audio for 5 preset voices
  - Default voice: `Binh` (VieNeu Vietnamese male) + edge fallback `vi-VN-HoaiMyNeural`
  - **Depends on**: Task 3.2.1

- [x] 22. Task 3.2.3 — TTS API endpoints
  - `GET /api/tts/voices` — list preset + custom voices
  - `POST /api/tts/synthesize` — synth on demand
  - Storage folder: `storage/voice_gallery/`
  - Implemented in `server/api/routes/tts.py`
  - **Depends on**: Task 3.2.2

### Phase 3.3 — Audio compose + Whisper subtitle

- [x] 23. Task 3.3.1 — Whisper transcribe
  - `server/audio/transcribe.py` (lift from MoneyPrinterTurbo)
  - faster-whisper with model selector
  - Output SRT segments
  - **Depends on**: Task 3.2.3

- [x] 24. Task 3.3.2 — Audio compose
  - `server/render/composer.py` — port daihuo composer.ts
  - FFmpeg: TTS + BGM mix + subtitle burn-in
  - Reconcile durations (audio-driven scene timing)
  - **Depends on**: Task 3.3.1

- [x] 25. Task 3.3.3 — Quality Gates G4-G5
  - G4: Audio quality check (`pipeline/gates/g4_audio_quality.py`)
  - G5: Subtitle quality check (`pipeline/gates/g5_subtitle_quality.py`)
  - **Depends on**: Task 3.3.2

### Phase 3.5 — Visual Layer

- [x] 26. Task 3.5.1 — Playwright renderer
  - `server/render/visual_layer/playwright_renderer.py`
  - HTML+GSAP → MP4 with alpha channel
  - `pip install playwright && playwright install chromium`
  - GSAP local bundle (`gsap_bundle.py`)
  - **Depends on**: Task 3.3.3

- [x] 27. Task 3.5.2 — HF Protocol
  - `server/render/visual_layer/hf_protocol.py`
  - `window.__hf` contract types
  - `template_registry.py` for template discovery
  - **Depends on**: Task 3.5.1

- [x] 28. Task 3.5.3 — Visual layer templates
  - `intro_card.html`, `outro_card.html`
  - `lower_third.html`, `chapter_title.html`, `product_card.html`
  - All 5 templates present in `render/visual_layer/templates/`
  - **Depends on**: Task 3.5.2

- [x] 29. Task 3.5.4 — Overlay compositor
  - `server/render/overlay_compositor.py` — overlay on Veo3 video
  - FFmpeg filter graph (`render/ffmpeg_utils.py`)
  - **Depends on**: Task 3.5.3

### Phase 4.0 — ContentAdapter foundation

- [x] 30. Task 4.0.1 — ContentAdapter interface
  - `server/content/base.py` — interface + dataclass
  - `server/content/registry.py` — auto-discover adapters
  - Skill manifest schema (`skill_manifest.py`, `skill_loader.py`, `style_validator.py`)
  - **Depends on**: Task 3.5.4

- [x] 31. Task 4.0.2 — Shared adapter logic
  - `server/content/character_dedup.py`
  - `server/content/duration_estimator.py`
  - `server/content/llm_chunking.py`
  - `server/content/srt_utils.py`
  - **Depends on**: Task 4.0.1

- [x] 32. Task 4.0.3 — Skills framework
  - `skills/_base/` rules (camera_lock, safety, continuity)
  - Manifest YAML loader
  - Style.json validator
  - `ecommerce-fashion` and `kdrama-romance` skills complete
  - **Depends on**: Task 4.0.2

### Phase 4.1 — Adapter ecommerce-product

- [x] 33. Task 4.1 — Adapter ecommerce-product
  - `content/adapters/ecommerce_product/adapter.py` + `prompts.py`
  - Port prompts from `daihuo-jianshou/script-engine/prompts.ts`
  - Complete `ecommerce-fashion` skill
  - Test: 1 product image → TikTok video
  - **Depends on**: Task 4.0.3

### Phase 4.2 — Adapter narrative-script

- [x] 34. Task 4.2 — Adapter narrative-script
  - `content/adapters/narrative_script/adapter.py` + `parser.py`
  - Markdown parser
  - Scene extraction from narrative
  - Test: 1 markdown → video
  - **Depends on**: Task 4.0.3

### Phase 4.3 — Adapter blog-article

- [x] 35. Task 4.3 — Adapter blog-article
  - `content/adapters/blog_article/adapter.py` + `fetcher.py`
  - URL fetch + readability extract
  - LLM chunking → scenes
  - Test: 1 blog URL → explainer video
  - **Depends on**: Task 4.0.3

### Phase 4.4 — Adapter storyboard-manual

- [x] 36. Task 4.4 — Adapter storyboard-manual
  - `content/adapters/storyboard_manual/adapter.py` + `schema.py`
  - JSON schema for storyboard
  - Validator
  - Test: 1 JSON → video
  - **Depends on**: Task 4.0.3

### Phase 4.5 — Adapter video-remaster

- [x] 37. Task 4.5.1 — Cookie sniffer module in extension
  - `extension/modules/cookie_sniffer.js`
  - Capture cookies for 3 platforms (Bilibili, Douyin, TikTok)
  - **Depends on**: Task 4.0.3

- [x] 38. Task 4.5.2 — Downloaders
  - `content/crawlers/bilibili/downloader.py`
  - `content/crawlers/douyin/downloader.py`
  - `content/crawlers/tiktok/downloader.py`
  - `content/crawlers/generic.py` (yt-dlp fallback)
  - aria2c parallel download via `flow/downloader.py`
  - **Depends on**: Task 4.5.1

- [x] 39. Task 4.5.3 — Signing modules (GPL v3 component)
  - `content/crawlers/signing/a_bogus.py`, `x_bogus.py`, `wbi.py`
  - `content/crawlers/signing/update_check.py` — auto-update check script
  - Pin upstream commit
  - **Depends on**: Task 4.5.2

- [x] 40. Task 4.5.4 — Cookie manager + browser-cookie3
  - `content/crawlers/cookies/manager.py`
  - Auto-read Chrome (browser-cookie3)
  - Manual file fallback
  - **Depends on**: Task 4.5.3

- [x] 41. Task 4.5.5 — Stream merger + subtitle extractor
  - `content/crawlers/stream_merger.py` — FFmpeg merge audio+video DASH
  - Whisper transcribe original
  - **Depends on**: Task 4.5.4

- [x] 42. Task 4.5.6 — Translator + remaster
  - `content/crawlers/remaster.py` — Gemini translate to Vietnamese
  - Re-cut with new subtitle
  - 3 presets: light, aggressive, translate_only
  - **Depends on**: Task 4.5.5

### Phase 5.1 — Voice Gallery API + custom import

- [x] 43. Task 5.1 — Voice Gallery API
  - `POST /api/tts/voices/custom` — upload voice package zip
  - `GET /api/tts/voices/custom/{id}` — voice info
  - `DELETE /api/tts/voices/custom/{id}`
  - Schema validation via `audio/tts/voice_package.py` (spec 11)
  - Hook into Colab notebook output format
  - **Depends on**: Task 3.2.3

### Phase 5.2 — UI tối thiểu

- [x] 44. Task 5.2.1 — React + Vite setup
  - `ui/package.json` + Vite config
  - Zustand store (`ui/src/store/index.ts`), axios API client (`ui/src/api/client.ts`)
  - **Depends on**: Task 5.1

- [x] 45. Task 5.2.2 — UI pages
  - `ui/src/pages/NewProject.tsx` — input adapter + skill picker + voice picker
  - `ui/src/pages/Timeline.tsx` — scene editor
  - `ui/src/pages/Export.tsx` — final video preview + download
  - **Depends on**: Task 5.2.1

- [x] 46. Task 5.2.3 — Voice Gallery UI
  - `ui/src/pages/VoiceGallery.tsx`
  - List preset + custom voices
  - Demo audio playback
  - Upload custom voice zip
  - **Depends on**: Task 5.2.2

### Phase 6 — Adapter epub-novel

- [x] 47. Task 6.1 — EPUB parser
  - `content/epub/parser.py` — port extractAssets logic from Toonflow
  - Chapter detection, character extraction
  - **Depends on**: Task 4.0.3

- [x] 48. Task 6.2 — 3-tier mode
  - `content/adapters/epub_novel/tiers.py`
  - Tier 1: direct (short novel)
  - Tier 2: episode (long novel, split)
  - Tier 3: manual range (user-selected chapters)
  - **Depends on**: Task 6.1

- [x] 49. Task 6.3 — EPUB quality checkpoints
  - `content/adapters/epub_novel/quality_gates.py` + `pipeline/gates/epub_checkpoints.py`
  - 3 manual gates (character, plot, style)
  - Skill restriction (kdrama-romance only)
  - **Depends on**: Task 6.2

### Phase 7 — Export CapCut

- [x] 50. Task 7.1 — Lift pyJianYingDraft from VectCutAPI
  - `export/capcut/` — `draft.py`, `models.py`, `writer.py`
  - **Depends on**: Task 3.3.3

- [x] 51. Task 7.2 — Export CapCut draft
  - `export/capcut_exporter.py` — export draft with scenes + audio + subtitle
  - API route `server/api/routes/export.py`
  - **Depends on**: Task 7.1

- [x] 52. Task 7.3 — SRT export standalone
  - `export/srt_exporter.py`
  - **Depends on**: Task 7.2

### Cross-cutting

- [x] 53. Task ADR records
  - 5 ADR files written: `ADR-001-native-windows.md`, `ADR-002-gemini-api.md`, `ADR-003-merged-extension.md`, `ADR-004-douyin-api.md`, `ADR-005-ship-binary.md`
  - **Depends on**: Task 0.6

- [x] 54. Task Vendor binaries
  - Download FFmpeg 7.0+ → `vendor/ffmpeg.exe`, `vendor/ffprobe.exe`
  - Download aria2c → `vendor/aria2c.exe`
  - `download_vendor.py` is PATH-aware: skips binaries already on PATH (ffmpeg/ffprobe used from system PATH here); downloads only what's missing (aria2c vendored)
  - Script output is ASCII-safe for any Windows console codepage; verifies ffmpeg with `-version`, aria2c with `--version`
  - **Depends on**: Task 3.3.2

### Phase 5.3 — Core API routes (missing from Phase 5.2)

- [x] 55. Task 5.3 — Project + Scene + Content API routes
  - `GET /api/projects` — list all projects
  - `POST /api/projects` — create project (adapter + skill selection)
  - `GET /api/projects/{id}` — project detail + scene list
  - `DELETE /api/projects/{id}` — delete project
  - `GET /api/scenes/{id}` — scene detail
  - `PATCH /api/scenes/{id}` — update scene (prompt, duration, status)
  - `POST /api/content/parse` — dispatch to ContentAdapter, return SceneList
  - `GET /api/jobs/{id}/stream` — SSE for live job progress updates
  - `WS /ws/{project_id}` — UI live event stream (pipeline events)
  - `Cookie` DB model (`server/db/models/cookie.py`) for Phase 4.5 platform cookies
  - **Depends on**: Task 5.2.3

### Phase 2.5 — Quality Gate G6 (Final video QA)

- [x] 56. Task 2.5 — Quality Gate G6
  - `pipeline/gates/g6_final_video.py` — final video quality check
  - Validate output MP4: duration, resolution, audio sync, no black frames
  - Hook into orchestrator after compose step (pipeline step 13)
  - Manual override path for user acceptance
  - **Depends on**: Task 2.4

## Task Dependency Graph

```json
{
  "waves": [
    { "wave": 1, "tasks": ["1"] },
    { "wave": 2, "tasks": ["2"] },
    { "wave": 3, "tasks": ["3"] },
    { "wave": 4, "tasks": ["4"] },
    { "wave": 5, "tasks": ["5"] },
    { "wave": 6, "tasks": ["6", "53"] },
    { "wave": 7, "tasks": ["7"] },
    { "wave": 8, "tasks": ["8"] },
    { "wave": 9, "tasks": ["9"] },
    { "wave": 10, "tasks": ["10"] },
    { "wave": 11, "tasks": ["11"] },
    { "wave": 12, "tasks": ["12"] },
    { "wave": 13, "tasks": ["13"] },
    { "wave": 14, "tasks": ["14"] },
    { "wave": 15, "tasks": ["15", "56"] },
    { "wave": 16, "tasks": ["16"] },
    { "wave": 17, "tasks": ["17"] },
    { "wave": 18, "tasks": ["18"] },
    { "wave": 19, "tasks": ["19"] },
    { "wave": 20, "tasks": ["20"] },
    { "wave": 21, "tasks": ["21"] },
    { "wave": 22, "tasks": ["22"] },
    { "wave": 23, "tasks": ["23", "43"] },
    { "wave": 24, "tasks": ["24"] },
    { "wave": 25, "tasks": ["25", "54"] },
    { "wave": 26, "tasks": ["26", "50"] },
    { "wave": 27, "tasks": ["27", "51"] },
    { "wave": 28, "tasks": ["28", "52"] },
    { "wave": 29, "tasks": ["29"] },
    { "wave": 30, "tasks": ["30"] },
    { "wave": 31, "tasks": ["31"] },
    { "wave": 32, "tasks": ["32"] },
    { "wave": 33, "tasks": ["33", "34", "35", "36", "37", "47"] },
    { "wave": 34, "tasks": ["38", "48"] },
    { "wave": 35, "tasks": ["39", "49"] },
    { "wave": 36, "tasks": ["40"] },
    { "wave": 37, "tasks": ["41"] },
    { "wave": 38, "tasks": ["42"] },
    { "wave": 39, "tasks": ["44"] },
    { "wave": 40, "tasks": ["45"] },
    { "wave": 41, "tasks": ["46", "55"] }
  ]
}
```

## Notes

- Tasks 1–56 are complete (`[x]`).
- Task 54 (Vendor binaries): `download_vendor.py` is PATH-aware — ffmpeg/ffprobe are used from the system PATH (not re-downloaded), aria2c is vendored to `vendor/aria2c.exe`. Runtime resolver checks `vendor/` first then PATH.
- Task 55 (Core API routes): Implemented — `projects.py`, `scenes.py`, `content.py`, `jobs.py`, `ws.py` routes + `Cookie` DB model. All registered in `main.py`.
- Task 56 (G6 Final video QA): Implemented — `pipeline/gates/g6_final_video.py` with G6.1–G6.5 checks, hooked into orchestrator `compose_with_g6()`, 34 unit tests passing.
- All tasks run sequentially per phase; parallel execution is possible within Phase 4 adapters (Tasks 33-36 and 37-42 share only the Task 4.0.3 dependency).
- Phase 4.5 signing modules (Task 39) are GPL v3 — personal use only, isolate as subprocess if ever made public.
- VieNeu-TTS GPU mode requires Python 3.12+ (already satisfied with Python 3.14.3).
- Vendor binaries (FFmpeg, aria2c) must be placed in `vendor/` — do not rely on PATH.
- All secrets go in `.env` (gitignored); never echo secret values in logs.
- Extension binds to `127.0.0.1` only — no public exposure.
