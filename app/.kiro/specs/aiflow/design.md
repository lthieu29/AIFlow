# AIFlow — Design

> **Detail specs**: [docs/00-11](../../../docs/) — this file is summary only
> **Status**: Approved (v1.3 — 12 issues from REVIEW-02 fixed)

## Architecture overview

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

## Pipeline end-to-end

```
1. Input (image/text/URL/EPUB) via UI or CLI
        ↓
2. ContentAdapter.parse() → SceneList
        ↓
3. Apply Skill (style.json + prefix.md)
        ↓
4. Quality Gate G1 (validate SceneList)
        ↓
5. Generate Audio (TTS full_narration)
        ↓
6. Quality Gate G4 + G5 (audio + subtitle)
        ↓
7. Reconcile durations per audio segments
        ↓
8. Generate Asset Refs (parallel, 1 ref per asset)
        ↓
9. Quality Gate G2 (user approve refs)
        ↓
10. Generate Scene Videos (sequential, scene chain)
        ↓
11. Quality Gate G3 per scene (auto retry max 2)
        ↓
12. Compose: scenes + audio + subtitle + visual layer
        ↓
13. Quality Gate G6 (final video)
        ↓
14. storage/output/{project_id}/final.mp4
```

## Layer separation

Strict dependency direction (no horizontal cross-import):

```
┌───────────────────────────────────────────────┐
│  api/      (FastAPI routes)                   │
└───────────────────┬───────────────────────────┘
                    ↓
┌───────────────────────────────────────────────┐
│  pipeline/ (orchestrator, quality_gate, jobs) │
└───────────────────┬───────────────────────────┘
                    ↓
┌────────┬───────┬────────┬─────────┬───────────┐
│ flow/  │ ai/   │ audio/ │ render/ │ content/  │
│ (Veo3) │(Gemini)│ (TTS) │(ffmpeg) │(adapters) │
└────────┴───────┴────────┴─────────┴───────────┘
                    ↓
┌───────────────────────────────────────────────┐
│  db/       (SQLModel + SQLite)                │
└───────────────────────────────────────────────┘
```

## Key design decisions

### D1 — Native Windows, no WSL
**Why**: Chrome extension runs on Windows host. WSL would require proxy + double config.
**Tradeoff**: PowerShell quirks vs setup simplicity.
**ADR**: 0001

### D2 — Gemini API direct, no CLI
**Why**: Free tier 15 RPM is enough. Direct API has lower latency than shell-out.
**Tradeoff**: Can't reuse google-cli auth.
**ADR**: 0002

### D3 — Single Chrome extension (gộp 2 module)
**Why**: 1 service worker = less RAM, 1 connection, unified UX.
**Tradeoff**: Larger permission set requested upfront.
**ADR**: 0003

### D4 — Douyin_TikTok_Download_API over yt-dlp
**Why**: Has a_bogus + WBI signing in pure Python. yt-dlp depends on upstream rotation.
**Tradeoff**: GPL v3 license obligation (mitigated by personal use).
**ADR**: 0004

### D5 — Ship FFmpeg/aria2c binaries in vendor/
**Why**: Pin version, no PATH conflict, Windows native stability.
**Tradeoff**: Larger repo size (~150MB).
**ADR**: 0005

### D6 — Mini-hyperframes Python (300 lines) vs full Hyperframes framework
**Why**: Hyperframes is Bun + WebGPU heavy. We only need HTML+GSAP → MP4.
**Tradeoff**: Re-implement subset, miss advanced features.
**ADR**: 0006 (TBD)

### D7 — 4 orthogonal continuity layers
**Why**: Each layer (Style/Asset/Scene/Audio) independently testable. Avoids tangled prompt synthesis.
**Tradeoff**: More structure to maintain.

### D8 — Skills as data only (no Python code)
**Why**: Users can add/share skills without code review. Easier to swap.
**Tradeoff**: Limited expressivity (config-only).

### D9 — Pydantic Settings nested with env prefix (REVIEW-02 #3)
**Why**: Clean separation of concerns. Validates at startup.
**Tradeoff**: Need explicit env_nested_delimiter testing per spec 01.

### D10 — VoiceInfo as Pydantic BaseModel, not dataclass (REVIEW-02 #12)
**Why**: Used in FastAPI response_model. Dataclass would force conversion.

### D11 — Folder name `voice_gallery/` not `voices/` (REVIEW-02 #11)
**Why**: Consistent with API endpoint `/api/tts/voices/{custom}`. Avoids ambiguity.

### D12 — `location_hint` Literal enum, not free string (REVIEW-02 #6)
**Why**: Free strings caused `"coffee shop"` vs `"café"` mismatch. Enum forces canonical form for chain reset detection.

## State machines

### Job state
```
pending → running → success
                  ↘ failed → (manual retry) → pending
```

### Quality Gate state
```
pending → checking → passed
                   ↘ failed → (auto retry up to 2) → checking
                   ↘ expired (G2.8 SLA timeout, REVIEW-02 #7)
                   ↘ overridden (manual user override)
```

### Scene state
```
draft → queued → generating → quality_check → approved
                                           ↘ rejected → (re-queue, max 2)
```

## Database schema (key tables)

- `Project` — top-level container, has skill + adapter
- `Scene` — order, duration, status, location_hint (enum)
- `Asset` — character/product/location refs
- `SceneAsset` — many-to-many with role
- `Style` — Lớp 1 continuity JSON
- `QualityGate` — G1-G6 tracking with score + expired_at
- `Job` + `JobLog` — async work tracking
- `Config` — schema_version + runtime config
- `Cookie` — Phase 4.5 platform cookies

Full schema: [docs/02-db-schema.md](../../../docs/02-db-schema.md)

## API surface (key endpoints)

- `GET  /api/health` — extension status + agent version
- `GET  /api/ext/discovery` — WS port discovery (no auth, REVIEW-01 #2)
- `POST /api/ext/callback` — extension callback (auth via X-Callback-Secret)
- `GET  /api/projects`, `POST /api/projects` — project CRUD
- `GET  /api/scenes/{id}`, `PATCH /api/scenes/{id}` — scene editor
- `POST /api/content/parse` — adapter dispatch
- `GET  /api/tts/voices` — voice catalog
- `POST /api/tts/synthesize` — TTS on demand
- `GET  /api/jobs/{id}/stream` — SSE for live updates
- `WS   /ws/{project_id}` — UI live event stream

Full API: [docs/03-api-contract.md](../../../docs/03-api-contract.md)

## Configuration model

Pydantic Settings with nested groups:
- `Settings.gemini` — API key, model, timeout
- `Settings.flow` — plan, default quality/aspect
- `Settings.tts` — primary backend, default voice
- `Settings.whisper` — model, device, compute_type
- `Settings.remaster` — preset, target lang, cookie source

Env vars: `AIFLOW_*` prefix for everything.

Full config: [docs/01-config-spec.md](../../../docs/01-config-spec.md)

## Testing strategy

### Phase 0 — smoke tests only
- `test_gemini.py` — Gemini API smoke
- `test_gen_image.py` — Veo3 image gen
- `smoke_phase0.py` — full Phase 0 acceptance (7 checks)

### Phase 1+ — pytest suite
- Unit tests per layer (flow, ai, audio, render)
- Integration tests per adapter
- E2E tests for full pipeline (sample script → final.mp4)

### Test isolation
- Each test creates its own SQLite (`:memory:`)
- HTTP/WS mocked via `httpx.MockTransport`
- Fixtures in `server/tests/fixtures/`

## Security considerations

### S1 — Secrets handling
- All secrets in `.env` (gitignored)
- Pydantic SecretStr wrapping for API keys
- No echo of secret values in logs

### S2 — Local-only binding
- FastAPI binds to `127.0.0.1` (not 0.0.0.0)
- WS server same — local only

### S3 — Extension callback auth
- Runtime-generated `callback_secret` (per session)
- Verified via `X-Callback-Secret` header
- Rotates on agent restart

### S4 — Cookie privacy
- `storage/cookies/` gitignored
- No cookie logging
- Personal use → no cross-user concern

### S5 — GPL v3 isolation (Phase 4.5+)
- a_bogus.py / x_bogus.py / wbi.py from Douyin_TikTok_API are GPL v3
- Personal use exempts source disclosure
- If ever public: isolate as subprocess

## Known limitations

- **L1**: Veo3 token capture depends on labs.google not changing API (mitigated by extension version pinning)
- **L2**: VieNeu-TTS GPU mode requires Python 3.12+ (we're on 3.14, OK ✅)
- **L3**: Anti-bot signing for Bilibili/Douyin can break (mitigated by upstream commit pinning)
- **L4**: EPUB adapter is heuristic-driven, may need manual override for complex novels
- **L5**: Single-machine (no distributed processing) — long novels may take many hours
