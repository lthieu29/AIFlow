# AIFlow — Master Plan

> **Mục đích**: file này là **point of entry** cho user review toàn bộ thiết kế trước khi bắt đầu code.
> **Reading order**: đọc file này TRƯỚC. Khi cần chi tiết, đi tới spec tương ứng được link.

## TL;DR

AIFlow là tool sinh video cá nhân — kết hợp 8 project nguồn tham khảo trong `D:/Project/AIFlow/` thành 1 pipeline:

```
[Idea / Input] → [Adapter parse] → [Veo3 sinh clips liền mạch] → [Audio + Subtitle] → [final.mp4]
```

- **Personal use**, không public, không thương mại
- **Native Windows**, không WSL
- **Stack**: Python **3.12** (FastAPI) + React 18 (UI Phase 5) + Chrome MV3 extension (Veo3 proxy + cookie sniffer)
- **Cost**: $20/tháng Google Flow Pro plan + Gemini AI Studio (free tier)
- **Total effort MVP**: ~7.5 tuần (Phase 0 → 4.5)
- **Total effort full**: ~11.5 tuần (gồm EPUB Phase 6 + Voice Gallery UI Phase 5.x)

## Quyết định đã chốt

Trước khi bắt đầu, user đã xác nhận:

| Quyết định | Chọn |
|------------|------|
| Plan Veo3 | Google Flow **Pro** ($20/tháng) |
| OS | Windows native (không WSL) |
| Skill MVP đầu tiên | `ecommerce-fashion` |
| Folder layout | Mới: `D:\Project\AIFlow\app\` ; 8 project gốc giữ làm reference; archive vào `_legacy/` sau MVP |
| Cookie strategy | Auto-read Chrome (`browser-cookie3`) + fallback manual paste |
| Extension | Gộp 2 module (Veo3 + cookie sniffer) thành 1 extension `AIFlow Bridge` |
| **TTS engine** | **VieNeu-TTS local (primary) + edge_tts (online fallback)** — auto detect GPU/CPU |
| **TTS preset default** | **`Binh` (VieNeu, nam Bắc) + `vi-VN-HoaiMyNeural` (edge fallback)** |
| **Python version** | **3.12** (cho LMDeploy GPU fast — RTF 0.05× thay vì 0.1-0.2×) |
| **Custom voice** | **Hybrid: LoRA fine-tune (≥30 phút data) hoặc persistent embedding (3-15s ref)** — Colab notebook |

## Bộ tài liệu spec đầy đủ

**Phải đọc theo thứ tự** (mỗi spec tham chiếu spec trước):

| # | File | Lines | Nội dung |
|---|------|-------|---------|
| 00 | [folder-structure](./00-folder-structure.md) | 416 | Cây thư mục `app/`, naming, .gitignore, ADR list |
| 01 | [config-spec](./01-config-spec.md) | 270 | `.env` + Pydantic Settings, 2 secret bắt buộc |
| 02 | [db-schema](./02-db-schema.md) | 441 | 9 bảng SQLite, state machines, indexes |
| 03 | [api-contract](./03-api-contract.md) | 434 | REST + WebSocket + SSE, error codes, e2e flow |
| 04 | [extension-spec](./04-extension-spec.md) | 461 | Chrome MV3 gộp 2 module, manifest, popup |
| 05 | [content-adapter-spec](./05-content-adapter-spec.md) | 519 | Interface `ContentAdapter`, skill manifest |
| 06 | [continuity-spec](./06-continuity-spec.md) | 524 | **4 lớp continuity**: Style/Asset/Scene/Audio |
| 07 | [quality-gate-spec](./07-quality-gate-spec.md) | 385 | G1-G6 checks, cascade, manual override |
| 08 | [visual-layer-spec](./08-visual-layer-spec.md) | 423 | Mini-hyperframes Python + Playwright + 5 templates |
| 09 | [phase0-execution](./09-phase0-execution.md) | 623 | 6 task Phase 0 chi tiết với acceptance |
| 10 | [tts-spec](./10-tts-spec.md) | 1841 | TTS provider abstraction (VieNeu + edge_tts) + Voice Gallery addendum |
| 11 | [custom-voice-training](./11-custom-voice-training.md) | 280 | LoRA fine-tune + persistent embedding, package zip schema |
| - | **PLAN.md** (file này) | - | Master overview + checklist approval |
| - | [reviews/REVIEW-01.md](./reviews/REVIEW-01.md) | 65 | Audit log v1.0 → v1.1 (7 issues fixed) |
| - | [reviews/REVIEW-02.md](./reviews/REVIEW-02.md) | 90 | Audit log v1.2 → v1.3 (12 issues fixed) |
| - | [colab/train_custom_voice.ipynb](../colab/train_custom_voice.ipynb) | 14 cells | Notebook Colab — train hoặc encode giọng custom |

**Tổng**: ~6900 dòng spec sau v1.2, đủ chi tiết để implement không cần hỏi thêm.

## Architecture cao cấp

```
┌─────────────────────────────────────────────────────────────────┐
│                    AIFlow Personal Tool                         │
│                                                                 │
│  ┌─────────────┐    HTTP :8101 / WS :9223    ┌──────────────┐  │
│  │ UI React    │<──────────────────────────>│  Server      │  │
│  │ (Phase 5)   │                              │  FastAPI     │  │
│  └─────────────┘                              │              │  │
│                                                │  - Pipeline  │  │
│  ┌─────────────┐    WS :9223                  │  - Adapters  │  │
│  │ Chrome      │<──────────────────────────>│  - Continuity│  │
│  │ Extension   │                              │  - Q.Gates   │  │
│  │ "AIFlow     │ ← Veo3 proxy                 │  - Render    │  │
│  │  Bridge"    │ ← Cookie sniffer             │              │  │
│  └─────┬───────┘                              └──────┬───────┘  │
│        │                                              │          │
│        │ Bearer ya29.* + cookies                     │          │
│        ↓                                              ↓          │
│  ┌───────────────┐                            ┌──────────────┐  │
│  │ Google Flow   │                            │ SQLite +     │  │
│  │ + Bilibili    │                            │ storage/     │  │
│  │ + Douyin      │                            │              │  │
│  └───────────────┘                            └──────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## Pipeline end-to-end (sau khi MVP done)

```
1. User nhập input (image/text/URL/EPUB) qua UI hoặc CLI
                  │
2. ContentAdapter.parse() → SceneList chuẩn
                  │
3. Apply Skill (style.json + prefix.md)
                  │
4. Quality Gate G1 (validate SceneList)
                  │
5. Generate Audio (TTS full_narration)
                  │
6. Quality Gate G4 + G5 (audio + subtitle)
                  │
7. Reconcile durations theo audio segments
                  │
8. Generate Asset Refs (1 ref/asset, parallel)
                  │
9. Quality Gate G2 (user approve refs)
                  │
10. Generate Scene Videos (sequential, scene chain)
                  │
11. Quality Gate G3 per scene (auto retry max 2)
                  │
12. Compose: scenes + audio + subtitle + visual layer overlays
                  │
13. Quality Gate G6 (final video)
                  │
14. Output: storage/output/{project_id}/final.mp4
```

## Folder structure (root level)

```
D:\Project\AIFlow\
├── app/                                  ← PROJECT MỚI (viết từ đầu, lift có chọn lọc)
│   ├── docs/                             (toàn bộ spec — bạn đang ở đây)
│   ├── extension/                        (Chrome MV3 gộp Veo3 + cookie sniffer)
│   ├── server/                           (Python FastAPI + pipeline + adapters)
│   ├── ui/                               (React, Phase 5)
│   ├── skills/                           (skill packs — data only)
│   ├── storage/                          (runtime, gitignored)
│   ├── vendor/                           (ffmpeg.exe, aria2c.exe)
│   └── tests/
│
├── _legacy/                              ← Archive 8 project sau MVP
│
└── (8 project reference giữ nguyên hiện tại)
    ├── flowboard/                        ← LIFT extension + flow_sdk + flow_client
    ├── hyperframes/                      ← Idea HfProtocol (không lift framework)
    ├── MoneyPrinterTurbo/                ← LIFT llm + voice + subtitle + video
    ├── daihuo-jianshou/                  ← PORT prompts + composer
    ├── VectCutAPI/                       ← LIFT pyJianYingDraft (Phase 7)
    ├── Toonflow-app/                     ← PORT extractAssets logic (Phase 6)
    ├── Galaxy-*/                         ← Reference patterns (yt-dlp, aria2c)
    ├── Douyin_TikTok_Download_API/       ← LIFT crawlers (Phase 4.5)
    └── downkyi-2.0.x/                    ← Reference (Bilibili URL parser)
```

Chi tiết: [spec 00](./00-folder-structure.md).

## Roadmap đầy đủ — 11 tuần

| Phase | Tên | Effort | Deliverable | Phase mapping spec |
|-------|-----|--------|-------------|--------------------|
| **0** | **Setup nền tảng** | **4 ngày** | **Extension + Veo3 + Gemini hoạt động** ✅ | **spec 09** |
| 1 | Core video flow một-shot | 1 tuần | 1 clip Veo3 từ CLI | spec 02, 03 |
| 2 | Continuity engine 4 lớp | 2 tuần | 5 clip liền mạch | spec 06 |
| 3.1 | TTS provider + edge_tts | 2 ngày | edge_tts pipeline integration | spec 10 |
| 3.2 | VieNeu-TTS local + voice catalog + pre-gen demos | 3 ngày | VieNeu CPU/GPU + `/api/tts/voices` đầy đủ | spec 10 |
| 3.3 | Audio compose + Whisper subtitle | 2 ngày | TTS + subtitle + ffmpeg merge | spec 10 |
| 3.5 | Visual Layer | 4 ngày | Intro/outro card đẹp | spec 08 |
| 4.0 | ContentAdapter foundation | 1 tuần | Framework + 1st adapter | spec 05 |
| 4.1 | Adapter `ecommerce-product` | 2 ngày | Image → TikTok video | spec 05 |
| 4.2 | Adapter `narrative-script` | 1.5 ngày | Markdown → video | spec 05 |
| 4.3 | Adapter `blog-article` | 2 ngày | URL → explainer | spec 05 |
| 4.4 | Adapter `storyboard-manual` | 1 ngày | JSON storyboard | spec 05 |
| 4.5 | Adapter `video-remaster` | 5.5 ngày | Bilibili/Douyin → re-cut với sub VN | (Phase 4.5 specific) |
| 5.1 | Voice Gallery API + custom import | 2 ngày | `/api/tts/voices/custom/*` endpoints | spec 10 §A.4, spec 11 |
| 5.2 | UI tối thiểu (project + Voice Gallery + timeline) | 1 tuần | New project + voice picker + export | spec 03, spec 10 §A.7 |
| 6 | Adapter `epub-novel` | 2 tuần | EPUB → multi-episode drama | (Phase 6 specific) |
| 7 | Export CapCut | 3 ngày | Draft cho user edit thủ công | spec 02 |

**MVP boundary** (P0+P1 essentials): Phase 0 → 4.5 = **~7.5 tuần**.
**Full v1.0**: Phase 0 → 7 = **~11 tuần**.

## Technical decisions ghi lại

| Quyết định | Lý do | ADR |
|-----------|-------|-----|
| Native Windows, không WSL | Chrome extension chạy trên Windows host, dùng WSL phải proxy thêm | ADR-0001 |
| Gemini API trực tiếp, không CLI | Free tier 15 RPM đủ, latency thấp hơn shell-out | ADR-0002 |
| 1 Chrome extension gộp 2 module | UX tốt hơn, RAM tiết kiệm, quản lý 1 connection | ADR-0003 |
| Douyin_TikTok_Download_API thay yt-dlp | Có a_bogus + WBI signing thuần Python, không phụ thuộc yt-dlp upstream | ADR-0004 |
| Ship FFmpeg/aria2c binary trong vendor/ | Pin version, không phụ thuộc PATH, Windows native ổn định | ADR-0005 |
| Mini-hyperframes Python tự build | Hyperframes framework quá nặng (Bun + WebGPU), 300 dòng Python đủ dùng | (sẽ ghi ADR-0006) |
| 4 lớp continuity orthogonal | Mỗi lớp giải quyết 1 dimension độc lập, dễ test | (Phase 2 review) |

## Top 10 Risks & Mitigations

| # | Risk | Severity | Mitigation chính |
|---|------|----------|------------------|
| 1 | Veo3 i2v drift identity giữa clip | 🔴 High | Hard anchor character ref (frontal, neutral) + source pinning + manual gate G2 |
| 2 | Chrome ext token capture fail / Veo3 đổi API | 🔴 High | Fallback fal.ai + health check + extension version pinning |
| 3 | FFmpeg/moviepy Windows path + sync drift | 🟡 Medium | Ship FFmpeg binary + UUID filename + audio-driven timing |
| 4 | Playwright Windows + concurrent ffmpeg | 🟡 Medium | Atomic temp folders + sequential render + path normalization |
| 5 | EPUB adapter quality gap | 🟡 Medium | 3 tier (direct/episode/manual range) + 3 manual checkpoints + skill restriction |
| 6 | Anti-bot signing Douyin/Bilibili break | 🔴 High | Pin upstream commit + auto-update check + 5-step fallback chain |
| 7 | a_bogus.py GPL v3 license obligation | 🟡 Medium | Personal use không trigger; tách subprocess nếu sau public |
| 8 | Bilibili VIP/charge content + region lock | 🟢 Low | Detect error code + UI warn + require proxy |
| 9 | Translation timing drift (Whisper segments) | 🟡 Medium | Mode A subtitle-only safe; Mode B atempo speed-up TTS |
| 10 | Long novel cost over budget | 🟡 Medium | 3 tier limit, episode mode, daily Veo3 quota tracking |

Chi tiết Risk 1-3 trong messages trước (đã thảo luận).
Chi tiết Risk 4-5 trong [spec 06](./06-continuity-spec.md).
Chi tiết Risk 6-10 trong [spec phase 4.5 docs] (sẽ viết khi tới Phase 4.5).

## Lift / Port / Build matrix tổng hợp

| Component | Source | Strategy | Phase |
|-----------|--------|----------|-------|
| Chrome extension Veo3 proxy | flowboard/extension | LIFT (refactor structure) | 0.2 |
| Chrome extension cookie sniffer | Douyin_TikTok_API/chrome-cookie-sniffer | LIFT + mở rộng 3 platform | 4.5 |
| `flow_client.py` + `flow_sdk.py` | flowboard/agent/services | LIFT (subset, Phase 0 chỉ gen_image) | 0.4-0.5 |
| `prompt_synth.py` continuity | flowboard/agent/services | PORT + đơn giản hoá | 2 |
| Gemini client | MoneyPrinter/llm.py phần Gemini | LIFT subset | 0.3 |
| `tts.py` edge_tts | MoneyPrinter/voice.py | LIFT | 3.1 |
| VieNeu-TTS provider | VieNeu-TTS SDK | LIFT (wrap as provider) | 3.2 |
| LoRA fine-tune (Colab) | VieNeu-TTS/finetune | LIFT | 5.x (notebook đã viết) |
| `transcribe.py` Whisper | MoneyPrinter/subtitle.py | LIFT | 3.3 |
| `composer.py` ffmpeg orchestration | daihuo/video-composer | PORT TS→Python | 3 |
| `prompts.py` ecommerce templates | daihuo/script-engine/prompts.ts | PORT | 4.1 |
| ContentAdapter interface | (mới) | BUILD | 4.0 |
| Continuity engine 4 lớp | (mới, lấy idea từ flowboard) | BUILD | 2 |
| Quality gate framework | (mới) | BUILD | 2-3 |
| Visual layer renderer | hyperframes idea + mới | BUILD (300 dòng) | 3.5 |
| Templates HTML+GSAP | (mới, lấy style hyperframes) | BUILD | 3.5 |
| Bilibili crawler | Douyin_TikTok_API/crawlers/bilibili | LIFT | 4.5 |
| Douyin crawler + a_bogus | Douyin_TikTok_API/crawlers/douyin | LIFT (chú ý GPL) | 4.5 |
| Skill packs | Toonflow skills format + mới | BUILD | 4.0+ |
| EPUB parser | Toonflow extractAssets logic | PORT + đơn giản | 6 |
| CapCut export | VectCutAPI/pyJianYingDraft | LIFT | 7 |

## Checklist approval

Trước khi tôi bắt đầu code Phase 0 (task 0.1), bạn cần xác nhận từng mục:

### Spec review

- [ ] Đọc qua [spec 00 — folder structure](./00-folder-structure.md), thấy hợp lý
- [ ] Đọc qua [spec 01 — config](./01-config-spec.md), env vars OK
- [ ] Đọc qua [spec 02 — db schema](./02-db-schema.md), bảng + state machine OK
- [ ] Đọc qua [spec 03 — api contract](./03-api-contract.md), REST + WS endpoints OK
- [ ] Đọc qua [spec 04 — extension](./04-extension-spec.md), gộp 2 module OK
- [ ] Đọc qua [spec 05 — content adapter](./05-content-adapter-spec.md), interface OK
- [ ] Đọc qua [spec 06 — continuity](./06-continuity-spec.md), 4 lớp hợp lý
- [ ] Đọc qua [spec 07 — quality gate](./07-quality-gate-spec.md), G1-G6 OK
- [ ] Đọc qua [spec 08 — visual layer](./08-visual-layer-spec.md), Playwright OK
- [ ] Đọc qua [spec 09 — phase 0 execution](./09-phase0-execution.md), 6 task rõ ràng
- [ ] Đọc qua [spec 10 — TTS + Voice Gallery](./10-tts-spec.md), provider + voice catalog OK
- [ ] Đọc qua [spec 11 — custom voice training](./11-custom-voice-training.md), Colab notebook approach OK

### Decisions còn pending

(Đã chốt mọi quyết định lớn ở v1.3. Xem [REVIEW-02](./reviews/REVIEW-02.md).)

### Risks acknowledgement

- [ ] Hiểu rằng Veo3 i2v identity drift là risk #1, mitigation chính là hard anchor character ref
- [ ] Hiểu rằng Chrome extension signing có thể break (Veo3 đổi API), cần monitor
- [ ] Hiểu rằng Phase 0 KHÔNG có UI, chỉ CLI smoke test
- [ ] Chấp nhận MVP timeline ~7.5 tuần (P0 → P4.5)

### Pre-flight môi trường

- [ ] Đã đăng ký **Google Flow Pro plan** ($20/tháng) tại labs.google
- [ ] Đã có **Google account đăng nhập** Chrome (để Flow auth + AI Studio)
- [ ] Đã đăng ký **Gemini API key** tại aistudio.google.com (free tier)
- [ ] Có **Chrome browser** (Edge cũng OK với MV3)
- [ ] Có **Python 3.12+** trên máy (cần cho LMDeploy GPU fast)
- [ ] Có **Node.js 20+** (cho UI Phase 5, không cần Phase 0)
- [ ] Có **Git** (để init repo)

### Approval

- [ ] **APPROVED** — bắt đầu code Phase 0 task 0.1

## Next action sau khi approve

Tôi sẽ bắt đầu Phase 0 task 0.1 trong session tiếp theo:

1. Tạo folder tree đúng spec 00
2. Tạo `pyproject.toml`, `.gitignore`, `.env.example`, `README.md`, `LICENSE`
3. Setup Python venv + install dependencies
4. Tạo `__init__.py` cho mọi Python package
5. Verify `python -c "import server"` chạy không error
6. Commit lần đầu `git commit -m "Phase 0.1 — skeleton"`

Sau đó báo cáo bạn, đợi green light → task 0.2.

---

## Status tracking

| Item | State |
|------|-------|
| Spec phase v1.0 (docs/) | ✅ DONE — 11 file, ~4500 dòng |
| User review #1 → v1.1 | ✅ DONE — 7 issues fixed (REVIEW-01) |
| Spec 10 — TTS + Voice Gallery (v1.2) | ✅ DONE |
| Spec 11 — Custom Voice Training (v1.2) | ✅ DONE |
| Colab notebook `train_custom_voice.ipynb` (v1.2) | ✅ DONE — 29 cell .py + notebook vỏ |
| User review #2 → v1.3 | ✅ DONE — 12 issues fixed (REVIEW-02) |
| User approval | ✅ APPROVED |
| Phase 0 task 0.1 | ✅ DONE |
| Phase 0 task 0.2-0.6 | ✅ DONE |
| Phase 1 | ⚪ NOT STARTED |
| ... | ⚪ |

**Last updated**: 2026-05-27 (v1.3 — 12 issues từ REVIEW-02 fixed)

## Changelog

- **v1.0** (2026-05-26 ~10:30) — Initial spec
- **v1.1** (2026-05-26 ~10:50) — Fixed 7 issues from REVIEW-01:
  - 3 critical: DB bootstrap, WS port discovery, G3 cascade depth limit
  - 4 non-critical: GSAP local bundle, friendly Gemini error, SceneAsset indexes, G2.8 SLA
- **v1.2** (2026-05-27) — TTS phase + Voice Gallery + Custom Voice Training:
  - Spec 10 — TTS provider abstraction (VieNeu + edge_tts) + Voice Gallery addendum
  - Spec 11 — Hybrid LoRA fine-tune + persistent embedding cho custom voice
  - Colab notebook `colab/train_custom_voice.ipynb` — 14 cells với runtime selector cho cả Colab Free (T4) và Pro (L4/A100/H100)
  - Phase 3 chia 3 sub-phase (3.1 edge_tts, 3.2 VieNeu, 3.3 Whisper compose); thêm Phase 5.1 Voice Gallery API; Phase 5 cũ → 5.2 UI
- **v1.3** (2026-05-27) — Fixed 12 issues from [REVIEW-02](./reviews/REVIEW-02.md):
  - 2 critical: Python 3.12 (chốt từ 3.11), Pydantic nested Settings env prefix
  - 6 medium: DB bootstrap import order, gate background scheduler, ffmpeg_utils path, helpers undefined, voice_gallery folder name conflict, VoiceInfo class type
  - 4 quyết định/UX: Extension discoverAttempts UX, location_hint Literal enum, score field reserved, TTS default voice + Python version chốt
