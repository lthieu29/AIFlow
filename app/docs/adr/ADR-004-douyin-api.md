# ADR-004 — Douyin/TikTok Download API thay yt-dlp

**Status**: Accepted  
**Date**: 2026-05-27  
**Deciders**: AIFlow project owner

---

## Context

AIFlow Phase 4.5 (`video-remaster` adapter) cần download video từ các platform:
- **Douyin** (抖音) — Chinese TikTok, cần signing phức tạp
- **Bilibili** — Chinese video platform, cần WBI signing
- **TikTok** — International version

Để download video từ các platform này, cần xử lý:
1. **Anti-bot signing**: Douyin dùng `a_bogus` và `x_bogus` algorithm; Bilibili dùng `wbi` signing
2. **Cookie authentication**: cần cookies từ browser session đã đăng nhập
3. **DASH stream merging**: video và audio là 2 stream riêng, cần merge bằng FFmpeg

### Các lựa chọn

#### Option 1: yt-dlp

`yt-dlp` là tool download video phổ biến nhất, hỗ trợ 1000+ sites bao gồm Douyin, Bilibili, TikTok.

**Vấn đề với yt-dlp**:
- Signing algorithm (`a_bogus`, `x_bogus`) được implement trong yt-dlp bằng JavaScript (Node.js subprocess) hoặc reverse-engineered Python — thường lag sau khi platform update
- yt-dlp là monolith (~200K dòng code) — khó embed, khó customize
- Không có Python API ổn định — phải shell-out hoặc dùng `yt_dlp` module với interface thay đổi thường xuyên
- Khi Douyin update anti-bot, phải đợi yt-dlp upstream fix (có thể mất vài ngày)
- Không có `wbi` signing thuần Python trong yt-dlp — dùng JS subprocess

#### Option 2: Douyin_TikTok_Download_API

Project `Douyin_TikTok_Download_API` (GitHub: Evil0ctal/Douyin_TikTok_Download_API) là FastAPI-based crawler chuyên cho Douyin/TikTok/Bilibili với:
- `a_bogus.py` — Douyin anti-bot signing thuần Python
- `x_bogus.py` — Douyin anti-bot signing thuần Python  
- `wbi.py` — Bilibili WBI signing thuần Python
- Crawler modules cho từng platform: `crawlers/douyin/`, `crawlers/bilibili/`, `crawlers/tiktok/`
- Chrome cookie sniffer extension (Module B của AIFlow Bridge)
- Được maintain tích cực, update nhanh khi platform thay đổi

**Vấn đề với Douyin_TikTok_Download_API**:
- License: **GPL v3** — nếu distribute phải open source toàn bộ project
- Là FastAPI server — cần lift crawler modules, không dùng nguyên server
- Signing modules có thể outdated nếu không theo dõi upstream

#### Option 3: Clean-room implementation

Tự implement signing algorithms từ đầu.

**Vấn đề**:
- `a_bogus` là reverse-engineered algorithm phức tạp (~500 dòng)
- Không có documentation chính thức
- Tốn nhiều thời gian, dễ sai

---

## Decision

**Lift crawler modules và signing modules từ `Douyin_TikTok_Download_API`, dùng làm core của `video-remaster` adapter.**

Cụ thể:
- **Lift**: `crawlers/douyin/`, `crawlers/bilibili/`, `crawlers/tiktok/` → `server/content/adapters/video_remaster/downloaders/`
- **Lift**: `a_bogus.py`, `x_bogus.py`, `wbi.py` → `server/content/adapters/video_remaster/signing/`
- **Pin**: upstream commit hash tại thời điểm lift, ghi vào `LICENSE_NOTICES.md`
- **Auto-update check**: `server/scripts/check_upstream_updates.py` — so sánh commit hash, alert khi có update signing modules
- **GPL isolation**: signing modules chạy như subprocess nếu project sau này public (hiện tại personal use)
- **Fallback**: `yt-dlp` làm generic fallback cho các platform không có crawler riêng (`downloaders/generic.py`)
- **Cookie sniffer**: lift `chrome-cookie-sniffer` → `extension/modules/cookie_sniffer.js` (Module B)

### Signing module usage

```python
# Douyin request signing
from server.content.adapters.video_remaster.signing.abogus import ABogus
from server.content.adapters.video_remaster.signing.xbogus import XBogus

# Bilibili WBI signing
from server.content.adapters.video_remaster.signing.wbi import WbiSigner
```

### Auto-update check script

```bash
python server/scripts/check_upstream_updates.py
# Output: "signing/abogus.py: upstream commit abc123 → def456 (3 commits behind)"
```

---

## Consequences

### Tích cực

- **Signing thuần Python**: không cần Node.js subprocess, không cần yt-dlp
- **Platform-specific**: crawler được tối ưu cho từng platform, không phải generic
- **Maintained**: upstream project active, update nhanh khi Douyin/Bilibili thay đổi anti-bot
- **Cookie sniffer bundled**: cùng project cung cấp Chrome extension module cho cookie capture
- **Fallback có sẵn**: yt-dlp vẫn dùng cho generic platforms

### Tiêu cực / Trade-offs

- **GPL v3 license**: nếu project sau này public hoặc commercial, phải isolate signing modules thành subprocess riêng hoặc relicense. Hiện tại personal use không trigger obligation
- **Upstream dependency**: nếu upstream project bị abandon hoặc DMCA, cần tự maintain signing modules
- **Anti-bot arms race**: Douyin/Bilibili có thể update signing algorithm bất cứ lúc nào. Mitigation: auto-update check script + pin commit
- **Lift maintenance**: khi upstream update signing, phải manually merge vào AIFlow

### GPL v3 compliance plan

| Scenario | Action |
|----------|--------|
| Personal use (hiện tại) | Không cần action — GPL v3 không require disclosure cho personal use |
| Distribute binary | Isolate signing modules thành subprocess riêng |
| Open source project | Relicense toàn bộ project dưới GPL v3, hoặc replace signing với clean-room |
| Commercial use | Replace signing với clean-room implementation |

---

## Alternatives considered

| Option | Lý do loại |
|--------|-----------|
| yt-dlp only | Signing lag sau platform update; JS subprocess; monolith khó embed |
| Clean-room signing | Tốn thời gian; dễ sai; không có documentation chính thức |
| Paid API (RapidAPI) | Cost; rate limit; privacy concern (gửi URL lên third-party) |
| Selenium/Playwright scraping | Chậm; fragile; cần browser instance |

---

## References

- [spec 05 — content adapter](../05-content-adapter-spec.md) — video-remaster adapter
- [spec 00 — folder structure](../00-folder-structure.md) — signing/ directory
- [LICENSE_NOTICES.md](../../LICENSE_NOTICES.md) — GPL v3 attribution
- PLAN.md Risk #6 — Anti-bot signing Douyin/Bilibili break
- PLAN.md Risk #7 — a_bogus.py GPL v3 license obligation
- Upstream: https://github.com/Evil0ctal/Douyin_TikTok_Download_API (GPL v3)
