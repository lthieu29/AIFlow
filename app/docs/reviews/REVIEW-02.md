# Review #2 — Spec audit (2026-05-27)

> **Reviewer**: User
> **Timestamp**: 2026-05-27 ~14:00 ICT
> **Action**: Fixed in spec v1.3
> **Trigger**: User audit toàn bộ spec sau khi v1.2 (TTS + Voice Gallery + Custom Voice) hoàn tất

## Summary

User audit lần 2 (~6900 dòng spec sau v1.2) — tìm ra **12 issues** chia 4 nhóm:

| Nhóm | Số lượng | Severity |
|------|----------|----------|
| Phải fix trước Phase 0 | 1 | 🔴 Critical (Python version + Pydantic nested) |
| Phải fix trước Phase 2 | 2 | 🟡 Medium (DB bootstrap import order, gate background task) |
| Phải fix trước Phase 3.1 | 4 | 🟡 Medium (ffmpeg_utils path, helper functions, folder name conflict, VoiceInfo class) |
| Quyết định + UX | 5 | 🟢 Low (đã quyết hoặc defer phase tương ứng) |

Tất cả 12 đã được fix trong spec v1.3 hoặc đã chốt quyết định.

## Issue table

| # | Severity | Issue | Spec(s) | Fix summary |
|---|----------|-------|---------|-------------|
| 1 | 🔴 Critical | Python version conflict — pyproject `>=3.11` nhưng LMDeploy chỉ chạy 3.12 | 09, 10, PLAN | **Bump `requires-python = ">=3.12"`**. Lý do: LMDeploy cho RTF 0.05× thay vì 0.1-0.2× (5× nhanh hơn), wheel pre-built đã có sẵn cho cp312-win_amd64 + cp312-cp312-manylinux. Spec 10 `_resolve_mode` bỏ check `sys.version_info[:2] == (3, 12)` — luôn try LMDeploy. |
| 2 | 🟡 Medium | PLAN.md có 2 checkbox pending block Phase 3 | PLAN | Chốt: Python 3.12 (issue 1) + TTS preset default = `Binh` (VieNeu) + `vi-VN-HoaiMyNeural` (edge fallback). Fjern checkbox, ghi vào "Quyết định đã chốt". |
| 3 | 🔴 Critical | Pydantic nested Settings env prefix — risk `AIFLOW_GEMINI_API_KEY` không load đúng | 01 | **Flatten approach**: bỏ `BaseSettings` cho sub-settings, chuyển sang `BaseModel` regular. `Settings` (root) custom `model_validator(mode='before')` tự đọc `os.environ['AIFLOW_GEMINI_API_KEY']` rồi gán vào `gemini` dict. Test ngay task 0.3 trước khi đi tiếp. |
| 4 | 🟡 Medium | `bootstrap_schema()` cần import models đúng thứ tự để register tables | 02, 09 | Tạo file `server/db/models/__init__.py` re-export TẤT CẢ models. `bootstrap_schema()` `from server.db import models  # noqa` để force register. Phase 0 chỉ có 4 model (Project/Job/JobLog/Config) → tách 4 file riêng + `__init__.py` import all. |
| 5 | 🟢 Low (UX) | Extension `discoverAgent()` retry vô hạn không hữu ích cho user | 04 | Thêm `discoverAttempts` counter. < 5 attempts → "Connecting..." spinner. ≥ 5 → "Agent not running. Run: `python -m server.main`". WS connected nhưng chưa token → "Connected — token missing. Open labs.google/fx/tools/flow". |
| 6 | 🟢 Low (defer Phase 4) | `location_hint` string tự do → khó so sánh giữa adapters | 05, 06 | Thay `Optional[str]` bằng `LocationCategory = Literal[...]` 10 giá trị: `indoor_studio`/`indoor_home`/`indoor_office`/`indoor_retail`/`indoor_cafe`/`outdoor_urban`/`outdoor_nature`/`outdoor_night`/`abstract`/`unspecified`. Lớp 3 chỉ reset chain khi cả 2 scene khác `unspecified` VÀ category khác nhau. |
| 7 | 🟡 Medium | G2.8 timeout `check_expired_gates()` không được schedule | 07, 09 | Spec 09 task 0.4 (lifespan) thêm `asyncio.create_task(periodic_gate_checker(settings, interval=60))`. Helper `periodic_gate_checker` định nghĩa trong `server/pipeline/quality_gate.py`. Phase 2.2 mới activate (Phase 0 chỉ skeleton). |
| 8 | 🟢 Low | `quality_gate.score` field orphan — chưa gate nào ghi | 02, 07 | Note rằng field reserved cho Phase 4+ LLM-as-judge gate (G3.9, G1.8). G2.4 face confidence sẽ ghi vào `score` (0-1). Không xoá field — backwards compat với future use. |
| 9 | 🟡 Medium | `probe_duration()` import path không tồn tại | 10 | Tạo MỚI `server/audio/ffmpeg_utils.py` riêng cho audio (probe duration, run ffmpeg encode mp3). `server/render/ffmpeg_utils.py` (spec 00) là cho video composer (subprocess heavy). 2 module có overlap nhưng audio-specific helper sống ở audio/ tránh import vòng. |
| 10 | 🟡 Medium | `_load_custom_catalog()`, `_get_or_load_vieneu()` chỉ mention không define | 10 | Thêm implementation đầy đủ vào spec 10 Addendum A.11 (helpers): cache catalog.json + lazy-load engine với asyncio.Lock. |
| 11 | 🟡 Medium | Folder conflict — spec 10 `storage/voice_gallery/`, spec 11 `storage/voices/` | 10, 11 | **Chốt `storage/voice_gallery/`** (spec 10 nói trước). Spec 11 update tất cả reference. Lý do: tên rõ ràng hơn cho user, phân biệt với `storage/voices/` có thể bị nhầm với "voice samples". |
| 12 | 🟡 Medium | `VoiceInfo` 2 spec định nghĩa khác class type | 10, 11 | **Chốt Pydantic `BaseModel`** (spec 10). Spec 11 update từ `@dataclass` sang `BaseModel`. Lý do: FastAPI `response_model` cần Pydantic, dataclass phải convert thêm bước. |

## Files changed v1.3

| Spec | Sections changed | Lines |
|------|------------------|-------|
| `00-folder-structure.md` | Thêm `server/audio/ffmpeg_utils.py` + thêm `server/db/models/__init__.py` + 4 model files Phase 0 | ~+15 |
| `01-config-spec.md` | `GeminiSettings`/`FlowSettings`/etc. dùng `BaseModel` thay `BaseSettings`. `Settings` custom `model_validator(mode='before')` parse env vars thủ công | ~+50, -30 |
| `02-db-schema.md` | Bootstrap section bổ sung import order + `models/__init__.py` pattern | ~+25 |
| `04-extension-spec.md` | `shared.js` thêm `discoverAttempts` counter + 4 popup states | ~+30 |
| `05-content-adapter-spec.md` | Scene/SceneList field `location_hint: LocationCategory` thay `Optional[str]` + định nghĩa Literal type | ~+20 |
| `06-continuity-spec.md` | Lớp 3 location_change check refactor: `if scene.loc != 'unspecified' and prev.loc != 'unspecified' and scene.loc != prev.loc` | ~+15 |
| `07-quality-gate-spec.md` | Note `score` field reserved cho future LLM judge + ghi G2.4 face confidence | ~+10 |
| `09-phase0-execution.md` | Task 0.3 thêm step verify Pydantic env loading. Task 0.4 thêm `periodic_gate_checker` (skeleton, no-op Phase 0). Models import pattern | ~+30 |
| `10-tts-spec.md` | LMDeploy bỏ check Python 3.12 (giờ luôn dùng được). Addendum A.5 fix folder = `voice_gallery`. Addendum A.11 mới — helpers full impl | ~+60, -20 |
| `11-custom-voice-training.md` | `VoiceInfo` → BaseModel. `storage/voices/` → `storage/voice_gallery/` | ~+5, -10 |
| `PLAN.md` | Quyết định: Python 3.12, TTS default Binh + HoaiMyNeural. Bỏ 2 checkbox pending. v1.3 changelog | ~+15, -5 |

Không file nào bị xoá. Tổng dòng thay đổi: ~+275 added, ~-65 removed.

## Validation

Sau fix, các spec có:
- ✅ Python version chốt 3.12 — LMDeploy fast path active mặc định
- ✅ Pydantic Settings load env vars có test plan ngay task 0.3
- ✅ DB bootstrap có pattern import models rõ ràng (file `__init__.py`)
- ✅ Extension UX cho user 4 trạng thái distinct
- ✅ Location enum cố định, không drift giữa adapters
- ✅ Background gate checker có hook trong lifespan
- ✅ ffmpeg_utils path không ambiguous
- ✅ Folder + class type không conflict 2 spec

## Lessons learned

Cho v3 review:
- Nested Pydantic Settings + env prefix luôn cần test thực tế, không trust documentation
- Mọi background task (asyncio loop) phải có entry point trong lifespan
- 2 spec viết cùng concept (VoiceInfo) phải cross-reference từ đầu
- Type hints lỏng (string tự do) là nợ kỹ thuật trong adapter framework — luôn dùng Literal/Enum
- LMDeploy version compatibility (Python 3.12 only) là constraint cứng — quyết định Python version sớm

## Next action

User review v1.3 → approve → bắt đầu Phase 0 task 0.1.

---

**Status**: All 12 issues addressed. Spec v1.3 ready for re-review.
