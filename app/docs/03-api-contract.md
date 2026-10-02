# 03 — API Contract Spec

> **Status**: Draft for review
> **Depends on**: 01-config, 02-db-schema
> **Used by**: extension, ui, scripts

## Mục đích

Định nghĩa toàn bộ surface API giữa 3 thành phần:

```
┌──────────────┐         WebSocket :9223         ┌──────────────┐
│              │<───────────────────────────────>│              │
│  Extension   │                                 │   Server     │
│  Chrome MV3  │         HTTP :8101              │   FastAPI    │
│              │<───────────────────────────────>│              │
└──────────────┘                                 │              │
                                                  │              │
┌──────────────┐         HTTP :8101               │              │
│  UI React    │<────────────────────────────────>│              │
│  (Phase 5)   │         + SSE/WS for live        │              │
│              │           updates                │              │
└──────────────┘                                  └──────────────┘
                                                          │
                                                          ↓
                                                    SQLite + storage/
```

## Convention chung

- Base URL: `http://127.0.0.1:8101`
- Tất cả request body + response: JSON (UTF-8)
- Date format: ISO 8601 với timezone (`2026-05-26T10:30:00+07:00`)
- ID format: short_id string (`p_a3f9`, `s_k3j8`) — KHÔNG expose integer PK
- Error format: thống nhất (xem dưới)
- Authentication: localhost-only, không cần auth user. Extension dùng `X-Callback-Secret`.

## Error response format

```json
{
  "error": {
    "code": "FLOW_QUOTA_EXCEEDED",
    "message": "Daily Veo3 credit budget reached (100/100)",
    "details": {
      "credits_used": 100,
      "credits_limit": 100,
      "reset_at": "2026-05-27T00:00:00Z"
    },
    "correlation_id": "req_a3f9k2"
  }
}
```

HTTP status code:
- `200` success
- `400` invalid request
- `404` not found
- `409` conflict (vd: project đang generating, không thể edit)
- `422` validation error (Pydantic)
- `429` rate limit
- `500` internal error
- `503` external service down (Flow / Gemini)

Error codes quy ước (constants/enum trong server):

| Code | Ý nghĩa |
|------|---------|
| `CONFIG_INVALID` | `.env` thiếu field bắt buộc |
| `EXTENSION_DISCONNECTED` | Extension chưa connect WS |
| `FLOW_TOKEN_EXPIRED` | Bearer token Veo3 hết hạn |
| `FLOW_QUOTA_EXCEEDED` | Daily credit budget hết |
| `FLOW_API_BREAK` | Flow đổi schema, signing fail |
| `GEMINI_QUOTA_EXCEEDED` | Free tier 15 RPM hết |
| `GEMINI_BLOCKED` | Content blocked (safety) |
| `COOKIE_EXPIRED` | Bilibili/Douyin cookie expired |
| `ADAPTER_INVALID_INPUT` | Adapter từ chối input |
| `JOB_NOT_FOUND` | job_id không tồn tại |
| `STATE_CONFLICT` | Project đang generating, không edit được |

---

## Phần 1 — REST API (Server)

### Health & status

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/health` | Liveness check |
| GET | `/api/status` | Full status: extension connected, gemini OK, etc. |
| GET | `/api/ext/discovery` | **Public — extension đọc để biết WS port động (REVIEW-01 #2)** |

#### `GET /api/ext/discovery`

Endpoint này KHÔNG yêu cầu auth (extension chưa có callback_secret). Trả về thông tin extension cần để connect đúng port.

Response:
```json
{
  "agent_version": "0.1.0",
  "ws_port": 9223,
  "ws_url": "ws://127.0.0.1:9223",
  "callback_url": "http://127.0.0.1:8101/api/ext/callback",
  "supported_modules": ["flow_proxy", "cookie_sniffer"],
  "min_extension_version": "0.1.0"
}
```

Extension flow:
```
1. Page load / service worker start
2. Extension fetch GET http://127.0.0.1:8101/api/ext/discovery
   - Nếu fail (agent chưa run) → retry mỗi 3s
3. Parse ws_url, gọi `new WebSocket(ws_url)`
4. WS handshake bình thường (callback_secret, etc.)
```

Lý do HTTP port 8101 cố định (không động): chicken-and-egg — extension phải có 1 endpoint biết trước để hỏi. HTTP 8101 default + WS port mới động.

User vẫn override được HTTP port qua `AIFLOW_PORT`, nhưng phải edit extension code (1 dòng `BASE = "http://127.0.0.1:XXXX"`) — trade-off accepted vì WS port + agent version mới là phần hay đổi.

#### `GET /api/health`
Response:
```json
{ "status": "ok", "version": "0.1.0", "uptime_sec": 1234 }
```

#### `GET /api/status`
Response:
```json
{
  "server": { "version": "0.1.0", "uptime_sec": 1234 },
  "extension": {
    "connected": true,
    "token_captured_at": "2026-05-26T10:00:00+07:00",
    "user": { "email": "***@gmail.com", "plan": "Pro" },
    "credits_used_today": 37,
    "credits_limit": 100
  },
  "gemini": {
    "configured": true,
    "model": "gemini-2.5-flash",
    "last_call_at": "2026-05-26T10:25:00+07:00"
  },
  "cookies": {
    "bilibili": { "valid": true, "source": "auto", "captured_at": "..." },
    "douyin":   { "valid": false, "source": "manual" }
  }
}
```

### Projects

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/projects` | List projects |
| POST | `/api/projects` | Create new project |
| GET | `/api/projects/{short_id}` | Get project detail |
| PATCH | `/api/projects/{short_id}` | Update title/description |
| DELETE | `/api/projects/{short_id}` | Delete (cascade) |
| POST | `/api/projects/{short_id}/generate` | Start generation pipeline |
| POST | `/api/projects/{short_id}/cancel` | Cancel running generation |
| POST | `/api/projects/{short_id}/archive` | Archive |

#### `POST /api/projects`
Request:
```json
{
  "title": "Sample TikTok video",
  "adapter_name": "ecommerce_product",
  "adapter_input": {
    "product_image_path": "/uploads/abc.jpg",
    "price": "299000",
    "category": "fashion"
  },
  "skill_id": "ecommerce-fashion",
  "aspect_ratio": "9:16",
  "target_duration_sec": 30
}
```
Response:
```json
{
  "short_id": "p_a3f9",
  "status": "draft",
  "created_at": "..."
}
```

#### `GET /api/projects/{short_id}`
Response: full project DTO bao gồm scenes[], assets[], current job nếu có.

### Scenes

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/projects/{pid}/scenes` | List scenes của project |
| GET | `/api/scenes/{sid}` | Scene detail |
| POST | `/api/scenes/{sid}/regenerate` | Re-gen scene (giữ asset refs) |
| PATCH | `/api/scenes/{sid}` | Edit narration / visual_prompt |
| POST | `/api/scenes/{sid}/skip` | Mark user_skipped |

### Assets

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/projects/{pid}/assets` | List assets |
| GET | `/api/assets/{aid}` | Asset detail |
| POST | `/api/assets/{aid}/regenerate` | Re-gen ref image |
| POST | `/api/assets/{aid}/upload` | User upload thay AI gen | (multipart/form-data) |
| PATCH | `/api/assets/{aid}` | Edit description |

### Jobs

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/projects/{pid}/jobs` | List jobs (default: only active) |
| GET | `/api/jobs/{jid}` | Job detail |
| GET | `/api/jobs/{jid}/logs` | Job logs (stream-able) |
| POST | `/api/jobs/{jid}/cancel` | Cancel queued/running job |

### Quality gates

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/projects/{pid}/gates` | List gate states |
| POST | `/api/gates/{gid}/override` | User force-pass 1 gate |

### Content adapter

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/adapters` | List available adapters |
| GET | `/api/adapters/{name}` | Adapter detail (input schema) |
| POST | `/api/adapters/{name}/parse` | Parse input → SceneList preview (không tạo project) |

#### `POST /api/adapters/{name}/parse`
Cho user preview SceneList trước khi commit thành project (Phase 4+).

### Skills

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/skills` | List skills |
| GET | `/api/skills/{id}` | Skill detail (manifest + style.json) |

### Cookies management

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/cookies` | List per-platform status |
| POST | `/api/cookies/{platform}/refresh` | Re-read browser cookies |
| POST | `/api/cookies/{platform}/manual` | Paste cookie string |
| DELETE | `/api/cookies/{platform}` | Clear |

### Render & export

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/projects/{pid}/output` | Stream final.mp4 (range support) |
| POST | `/api/projects/{pid}/export/capcut` | Export CapCut draft (Phase 7) |
| GET | `/api/projects/{pid}/srt` | Download .srt |

---

## Phần 2 — Extension callback API

### `POST /api/ext/callback`

Header: `X-Callback-Secret: {secret từ WS handshake}`

Extension dùng để gửi response của Flow API về cho agent. Body:
```json
{
  "request_id": "req_xyz",
  "status": "success",
  "response": {
    "headers": { "...": "..." },
    "body": { ... },
    "status_code": 200
  }
}
```
Hoặc fail:
```json
{
  "request_id": "req_xyz",
  "status": "error",
  "error": {
    "code": "NETWORK_ERROR",
    "message": "Failed to fetch"
  }
}
```

### `POST /api/ext/cookie_captured`

Khi cookie sniffer module bắt được cookie mới:
```json
{
  "platform": "bilibili",
  "cookie_string": "SESSDATA=xxx; bili_jct=yyy; ...",
  "source": "extension_sniffer"
}
```

---

## Phần 3 — WebSocket protocol (Extension ↔ Agent)

WS endpoint: `ws://127.0.0.1:9223`

### Connection lifecycle

```
1. Extension connect WS
2. Server gửi ngay:
   { "type": "callback_secret", "secret": "abc..." }
3. Extension save secret, gửi:
   { "type": "extension_ready", "version": "0.1.0", "modules": ["flow_proxy", "cookie_sniffer"] }
4. Heartbeat: client ping mỗi 25s, server pong
5. Disconnect → server retry sau 1s, exponential backoff max 30s
```

### Message envelope

Mọi message:
```json
{
  "id": "msg_xyz",          // Optional, có nếu cần response
  "type": "<type>",
  "params": { ... }
}
```

### Server → Extension

| `type` | `params` | Mô tả |
|--------|----------|-------|
| `callback_secret` | `{secret}` | Initial handshake |
| `api_request` | `{url, method, headers, body, request_id}` | Yêu cầu extension fetch URL trong session user |
| `get_captcha` | `{request_id, page_action}` | Yêu cầu extension solve reCAPTCHA |
| `read_cookie` | `{request_id, platform}` | Yêu cầu cookie sniffer module đọc cookie |
| `ping` | `{}` | Heartbeat |

### Extension → Server

| `type` | `params` | Mô tả |
|--------|----------|-------|
| `extension_ready` | `{version, modules}` | Initial signal |
| `token_captured` | `{token}` | Captured Bearer Veo3 token |
| `user_info` | `{email, plan, sku, credits}` | Profile pulled từ Flow |
| `cookie_captured` | `{platform, cookie}` | Cookie sniffer fired |
| `request_completed` | `{request_id, status}` | API request done (chi tiết qua HTTP callback) |
| `pong` | `{}` | Heartbeat reply |
| `status` | `{state, metrics}` | Periodic status update |

### Flow control

- **Single-flight per type**: VD chỉ 1 `api_request` cùng `request_id` được serve. Extension dedupe.
- **Timeout**: server đợi `api_request` callback tối đa 180s. Quá thời gian → mark fail.
- **Backpressure**: nếu queue > 50 pending → reject mới với code `EXT_BUSY`.

---

## Phần 4 — Server-Sent Events (UI live updates)

Dùng SSE (đơn giản hơn WS cho 1-chiều server→client).

### `GET /api/events?topics=jobs,gates,scenes&project_id=p_a3f9`

```
event: job.update
data: {"job_id": "j_xx", "status": "running", "progress": 0.4}

event: gate.update
data: {"gate_id": "...", "status": "fail", "reason": "..."}

event: scene.update
data: {"scene_id": "s_xx", "status": "ready", "video_local_path": "..."}

event: project.status
data: {"project_id": "...", "status": "composing"}
```

UI subscribe → live update timeline view.

---

## Phần 5 — Sample request flow end-to-end

### Tạo project ecommerce + gen video (Phase 4.1+ ready)

```
[UI / curl]                [Server]                  [Extension]              [Flow / Gemini]
   │                          │                          │                          │
   │ POST /api/projects        │                          │                          │
   ├─────────────────────────>│                          │                          │
   │   adapter_input={image}   │                          │                          │
   │                          │ adapter.parse()           │                          │
   │                          │ → SceneList               │                          │
   │                          │ Save to DB                │                          │
   │ 201 {short_id, status:"ready"} │                     │                          │
   │<─────────────────────────│                          │                          │
   │                          │                          │                          │
   │ POST /api/projects/p_xx/generate                     │                          │
   ├─────────────────────────>│                          │                          │
   │                          │ Enqueue jobs              │                          │
   │ 202 {accepted}            │                          │                          │
   │<─────────────────────────│                          │                          │
   │                          │                          │                          │
   │ GET /api/events SSE       │                          │                          │
   ├─────────────────────────>│                          │                          │
   │                          │                          │                          │
   │                          │ Worker pull job (gen_image asset)                    │
   │                          │ ── api_request ─────────>│                          │
   │                          │                          │ fetch Flow API           │
   │                          │                          ├─────────────────────────>│
   │                          │                          │<─────────────────────────│
   │                          │ <── ext callback ────────│                          │
   │ event: job.update progress=0.5                       │                          │
   │<─────────────────────────│                          │                          │
   │                          │ Save asset.ref_local_path  │                        │
   │                          │ → next job (gen_video)     │                        │
   │                          │ ...                       │                          │
   │ event: project.status=done                           │                          │
   │<─────────────────────────│                          │                          │
   │                          │                          │                          │
   │ GET /api/projects/p_xx/output                        │                          │
   ├─────────────────────────>│                          │                          │
   │ stream final.mp4          │                          │                          │
   │<─────────────────────────│                          │                          │
```

---

## Phần 6 — Versioning

- Path-based: `/api/v1/...` từ Phase 1+. Phase 0 không version (chưa stable).
- Header `X-API-Version: 1`.
- Breaking change → bump major. Add field optional → minor.

## Acceptance criteria cho spec này

- [ ] Mọi entity (project, scene, asset, job) có endpoint CRUD đầy đủ
- [ ] WS protocol đủ để extension làm proxy Flow + sniff cookies
- [ ] Error codes đủ cho UI hiển thị thông điệp người dùng-friendly
- [ ] SSE event types đủ cho UI live update timeline
- [ ] Có flow diagram end-to-end cho ít nhất 1 use case
- [ ] Spec đủ chi tiết để implement FastAPI routes mà không hỏi thêm

## Phase mapping

| Group | Phase |
|-------|-------|
| Health, status | 0 |
| Extension callback + WS | 0-1 |
| Projects CRUD | 1 |
| Scenes, Assets | 2 |
| Jobs, gates | 2-3 |
| Cookies | 4.5 |
| Adapters, Skills | 4 |
| Render output, SRT | 3 |
| CapCut export | 7 |
