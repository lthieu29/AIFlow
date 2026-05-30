# ADR-003 — Gộp Chrome Extension thành 1 project

**Status**: Accepted  
**Date**: 2026-05-27  
**Deciders**: AIFlow project owner

---

## Context

AIFlow cần 2 Chrome extension module với chức năng khác nhau:

- **Module A (Veo3 proxy)**: Inject vào `labs.google`, capture Bearer token `ya29.*` và reCAPTCHA token, forward tới server qua WebSocket. Lifted từ `flowboard/extension/`.
- **Module B (Cookie sniffer)**: Capture cookies từ `bilibili.com`, `douyin.com`, `tiktok.com` cho video download. Lifted từ `Douyin_TikTok_Download_API/chrome-cookie-sniffer`.

Hai module này ban đầu là 2 extension riêng biệt trong 2 project nguồn khác nhau. Câu hỏi: **gộp thành 1 extension hay giữ 2 extension riêng?**

### Phân tích nếu giữ 2 extension riêng

| Vấn đề | Chi tiết |
|--------|---------|
| UX phức tạp | User phải cài 2 extension, bật/tắt 2 chỗ, 2 popup khác nhau |
| RAM overhead | 2 service worker chạy song song, mỗi cái ~5-10MB |
| Port management | 2 WS connection tới server, cần quản lý 2 port hoặc multiplex thủ công |
| Permission trùng lặp | Cả 2 đều cần `storage`, `cookies`, `webRequest` — khai báo 2 lần |
| Branding lộn xộn | 2 icon, 2 tên, user không biết cái nào làm gì |
| Sync state | Module A cần biết cookies từ Module B (cho Douyin download sau khi gen video) — cross-extension messaging phức tạp |
| Development friction | 2 repo, 2 manifest, 2 reload cycle khi develop |

### Phân tích nếu gộp 1 extension

| Lợi ích | Chi tiết |
|---------|---------|
| UX đơn giản | 1 extension, 1 popup, 1 toggle |
| 1 service worker | Share state, 1 WS connection, multiplex messages theo `type` field |
| 1 manifest | Khai báo permissions 1 lần |
| Shared utils | `modules/shared.js` dùng chung cho cả 2 module |
| Auto-discovery | Extension tự tìm server qua `GET /api/ext/discovery`, không cần config |
| Cohesive branding | "AIFlow Bridge" — 1 tên, 1 logo |

### Cấu trúc sau khi gộp

```
extension/
├── background.js              ← Service worker orchestrator
├── modules/
│   ├── shared.js              ← WS connect, auth secret, common utils
│   ├── flow_proxy.js          ← Module A: Veo3 token capture
│   └── cookie_sniffer.js      ← Module B: cookie capture (Phase 4.5)
└── ...
```

Module B (`cookie_sniffer.js`) được defer tới Phase 4.5 — placeholder trong Phase 0.

---

## Decision

**Gộp 2 module thành 1 Chrome MV3 extension duy nhất tên "AIFlow Bridge", đặt trong `app/extension/`.**

Cụ thể:
- Extension sống trong `app/extension/` — cùng repo với server, không tách repo riêng
- 1 service worker (`background.js`) orchestrate cả 2 module
- 1 WebSocket connection tới `ws://127.0.0.1:9223` — multiplex messages theo `type` field
- Module A (`flow_proxy.js`) active từ Phase 0
- Module B (`cookie_sniffer.js`) placeholder Phase 0, implement Phase 4.5
- Extension tự discover server: `GET http://127.0.0.1:8101/api/ext/discovery` → nhận `ws_url`
- `discoverAttempts` UX: 0-4 lần = "Connecting...", 5+ lần = "Agent not running" với hint
- Shared config: `callback_secret` được server gửi khi WS connect, extension lưu trong memory

### Communication protocol

```
Extension → Server (WS):
  { type: "extension_ready", version: "1.0" }
  { type: "token_captured", token: "ya29.*", recaptcha: "..." }
  { type: "cookies_captured", platform: "douyin", cookies: [...] }
  { type: "pong", timestamp: ... }

Server → Extension (WS):
  { type: "callback_secret", secret: "..." }
  { type: "ping" }
  { type: "request_token" }
```

---

## Consequences

### Tích cực

- **Single install**: user cài 1 lần, không cần quản lý nhiều extension
- **Simpler development**: 1 reload cycle, 1 manifest, 1 codebase
- **Shared state**: Module A và B có thể share cookies/tokens trong service worker memory
- **Single repo**: extension code và server code cùng repo → dễ refactor, dễ review
- **Auto-discovery**: extension tự tìm server, không cần user config port thủ công
- **RAM efficient**: 1 service worker thay vì 2

### Tiêu cực / Trade-offs

- **Module coupling**: nếu Module B có bug, có thể ảnh hưởng Module A (service worker chung). Mitigation: mỗi module wrap trong try/catch riêng
- **Manifest permissions**: phải khai báo permissions cho cả 2 module ngay từ đầu, kể cả khi Module B chưa implement. User thấy permission request cho Bilibili/Douyin dù Phase 0 chưa dùng
- **Extension size**: gộp 2 module → extension lớn hơn một chút (~30-50KB total, không đáng kể)
- **Review complexity**: Chrome Web Store review (nếu sau này publish) sẽ xem xét tất cả permissions

### Không ảnh hưởng

- Server-side logic hoàn toàn độc lập với extension structure
- Extension không chứa business logic — chỉ là proxy/bridge

---

## Alternatives considered

| Option | Lý do loại |
|--------|-----------|
| 2 extension riêng | UX phức tạp; 2 WS connection; cross-extension messaging phức tạp |
| Extension + native messaging host | Overkill cho personal tool; setup phức tạp hơn |
| Tách extension ra repo riêng | Không có lợi ích rõ ràng; tăng friction khi develop |
| Không dùng extension (polling) | Không thể capture Bearer token từ Google session mà không có extension |

---

## References

- [spec 04 — extension](../04-extension-spec.md) — full extension spec
- [spec 03 — api contract](../03-api-contract.md) — `/api/ext/discovery`, `/api/ext/callback`
- [ADR-002](./ADR-002-gemini-api.md) — Veo3 token flow
- flowboard/extension/ — source của Module A
- Douyin_TikTok_Download_API/chrome-cookie-sniffer — source của Module B
