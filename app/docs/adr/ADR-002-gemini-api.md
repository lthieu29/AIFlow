# ADR-002 — Google Gemini API (Veo3 + Gemini)

**Status**: Accepted  
**Date**: 2026-05-27  
**Deciders**: AIFlow project owner

---

## Context

AIFlow cần 2 loại AI capability:

1. **Text generation** — viết prompt Veo3, dịch subtitle, phân tích content
2. **Video generation** — sinh clip 8 giây từ image + text prompt (i2v)

### Các lựa chọn cho video generation

| Option | Model | Cost | Chất lượng | Availability |
|--------|-------|------|-----------|--------------|
| **Google Veo3 (Flow)** | Veo3 | $20/tháng (Pro plan) | State-of-the-art 2026 | Cần Google account + Pro plan |
| Runway Gen-4 | Gen-4 | ~$35+/tháng | Tốt | API public |
| Kling AI | Kling 2.0 | ~$30+/tháng | Tốt | API public |
| Sora (OpenAI) | Sora | Chưa rõ pricing | Tốt | Waitlist |
| fal.ai (Veo3) | Veo3 | Per-generation (~$0.5-1/clip) | Tương đương | API public |

### Vấn đề với Veo3 API trực tiếp

Google chưa cung cấp Veo3 qua API public thông thường. Cách duy nhất để dùng Veo3 là:
- Qua `labs.google/fx/tools/flow` (web UI) với Google Flow Pro plan
- Qua `aisandbox-pa.googleapis.com` — internal API mà web UI dùng, cần Bearer token từ session đã đăng nhập

Chrome extension (`AIFlow Bridge`) capture Bearer token (`ya29.*`) từ browser session và forward tới server. Server dùng token này để gọi `aisandbox-pa.googleapis.com` trực tiếp.

### Các lựa chọn cho text generation

| Option | Model | Cost | Latency |
|--------|-------|------|---------|
| **Gemini API (AI Studio)** | Gemini 2.0 Flash | Free tier: 15 RPM | ~1-2s |
| OpenAI API | GPT-4o | ~$0.01/1K tokens | ~1-3s |
| Anthropic API | Claude 3.5 | ~$0.015/1K tokens | ~2-4s |
| Local LLM (Ollama) | Llama 3 | Free | ~5-30s (CPU) |

Gemini API (AI Studio) có free tier 15 RPM đủ cho personal use. Cùng ecosystem với Veo3 — 1 account, 1 API key.

### Vấn đề với CLI approach

Một số tool dùng `google-generativeai` CLI hoặc shell-out. Approach này:
- Latency cao hơn (subprocess overhead)
- Khó handle streaming response
- Khó retry/error handling
- Không thể dùng async/await

---

## Decision

**Dùng Google Gemini API trực tiếp cho text generation, và Veo3 qua `aisandbox-pa.googleapis.com` (Bearer token từ extension) cho video generation.**

Cụ thể:
- **Text generation**: `google-generativeai` Python SDK, model `gemini-2.0-flash-exp` (free tier)
- **Video generation**: HTTP POST tới `https://aisandbox-pa.googleapis.com/v1/...` với Bearer token capture từ Chrome extension
- **reCAPTCHA flow**: extension inject vào `labs.google` MAIN world để capture `grecaptcha.execute()` token, forward qua WebSocket port 9223
- **Plan requirement**: Google Flow **Pro** ($20/tháng) — cần để dùng Veo3 i2v
- **Fallback**: nếu extension không kết nối, server block và báo lỗi rõ ràng (không silent fail)

### Flow chi tiết

```
User mở labs.google → Extension capture Bearer token ya29.*
                    → Extension capture reCAPTCHA token
                    → Forward qua WS :9223 tới server
                    → Server dùng token gọi aisandbox-pa.googleapis.com
                    → Poll operation status mỗi 5s
                    → Download video bytes khi done
```

---

## Consequences

### Tích cực

- **Cost thấp**: $20/tháng cho Veo3 Pro + Gemini free tier = tổng $20/tháng
- **Chất lượng cao nhất**: Veo3 là state-of-the-art video generation 2026
- **1 ecosystem**: Google account duy nhất, không cần quản lý nhiều API key
- **Gemini free tier**: 15 RPM đủ cho personal use (không phải trả thêm)
- **Async native**: `google-generativeai` SDK hỗ trợ async/await

### Tiêu cực / Trade-offs

- **Phụ thuộc Chrome extension**: nếu extension không chạy, không gen được video. Mitigation: health check endpoint + popup status rõ ràng
- **Token expiry**: Bearer token `ya29.*` expire sau ~1 giờ. Extension tự động re-capture khi user reload trang
- **reCAPTCHA dependency**: Google có thể thay đổi reCAPTCHA flow. Mitigation: extension version pinning + monitor
- **Pro plan required**: cần trả $20/tháng. Không có free tier cho Veo3
- **API không public**: `aisandbox-pa.googleapis.com` là internal API, có thể thay đổi không báo trước. Mitigation: fal.ai fallback (xem PLAN.md Risk #2)
- **Rate limit**: Veo3 Pro có quota giới hạn (không public). Cần track daily usage

### Không ảnh hưởng

- Gemini text generation hoàn toàn độc lập với Veo3 — có thể dùng riêng lẻ
- Extension token capture không ảnh hưởng tới UX của user trên labs.google

---

## Alternatives considered

| Option | Lý do loại |
|--------|-----------|
| fal.ai Veo3 API | Per-generation cost cao hơn ($0.5-1/clip); giữ làm fallback |
| Runway Gen-4 | Chất lượng thấp hơn Veo3; cost cao hơn |
| OpenAI GPT-4o cho text | Có cost; Gemini free tier đủ dùng |
| Local LLM (Ollama) | Latency cao; chất lượng thấp hơn cho prompt synthesis |
| CLI / shell-out | Latency cao; khó async; khó error handling |

---

## References

- [spec 01 — config](../01-config-spec.md) — `AIFLOW_GEMINI_API_KEY`, `AIFLOW_FLOW_PLAN`
- [spec 03 — api contract](../03-api-contract.md) — `/api/ext/callback`, `/api/ext/discovery`
- [spec 04 — extension](../04-extension-spec.md) — token capture flow
- [ADR-003](./ADR-003-merged-extension.md) — extension architecture
- PLAN.md Risk #2 — Chrome ext token capture fail / Veo3 đổi API
