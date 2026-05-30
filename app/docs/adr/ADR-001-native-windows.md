# ADR-001 — Native Windows, không WSL

**Status**: Accepted  
**Date**: 2026-05-27  
**Deciders**: AIFlow project owner

---

## Context

AIFlow cần chạy trên máy cá nhân của người dùng để điều phối Chrome extension, gọi Google Veo3 API, và xử lý video với FFmpeg. Có 3 lựa chọn deployment:

1. **Windows native** — Python chạy trực tiếp trên Windows host
2. **WSL (Windows Subsystem for Linux)** — Python chạy trong Linux layer trên Windows
3. **Cross-platform** — hỗ trợ cả Windows, macOS, Linux

Người dùng mục tiêu là cá nhân dùng Windows 10/11 với Chrome browser đã đăng nhập Google account. Chrome extension (`AIFlow Bridge`) chạy trên Windows host và cần giao tiếp với server qua `127.0.0.1`.

### Vấn đề với WSL

- Chrome extension chạy trên Windows host, không thể kết nối trực tiếp tới `127.0.0.1` trong WSL mà không cần port forwarding thêm
- `browser-cookie3` (đọc Chrome cookies) không hoạt động trong WSL vì Chrome profile nằm trên Windows filesystem
- FFmpeg binary path và subprocess spawning phức tạp hơn khi cross WSL boundary
- Playwright (Visual Layer renderer) cần Chromium — cài trong WSL nhưng Chrome thật nằm trên Windows host gây nhầm lẫn
- Người dùng phải quản lý 2 môi trường (Windows + WSL), tăng friction

### Vấn đề với cross-platform

- Không có nhu cầu thực tế: người dùng duy nhất dùng Windows
- Tăng complexity: path separator (`\` vs `/`), binary packaging, CI matrix
- Vendor binaries (FFmpeg, aria2c) cần build riêng cho mỗi OS

---

## Decision

**Chọn Windows native (Python 3.12+ trên Windows host).**

Cụ thể:
- Target: **Windows 10 version 1903+** và **Windows 11** (64-bit)
- Python: **3.12+** (bắt buộc cho LMDeploy GPU fast — RTF 0.05×)
- Vendor binaries: FFmpeg 7.0+ và aria2c được đặt trong `vendor/` với absolute path
- Không hỗ trợ Linux hoặc macOS
- Không dùng WSL, không dùng Docker
- Path handling: dùng `pathlib.Path` xuyên suốt, tránh hardcode `/`

---

## Consequences

### Tích cực

- Chrome extension kết nối `127.0.0.1:8101` và `127.0.0.1:9223` không cần cấu hình thêm
- `browser-cookie3` đọc Chrome profile trực tiếp từ `%LOCALAPPDATA%\Google\Chrome\`
- FFmpeg subprocess path đơn giản, không cross-boundary
- Playwright Chromium cài một lần, không conflict với Chrome thật
- Setup cho người dùng mới: clone repo → `pip install -e .` → chạy ngay, không cần WSL setup
- Vendor binaries ship cùng repo, zero-dependency cho end user

### Tiêu cực / Trade-offs

- **Không hỗ trợ Linux/macOS**: developer hoặc người dùng khác muốn dùng trên Mac/Linux phải tự adapt
- **Windows-specific paths**: code phải dùng `pathlib.Path` nhất quán, không dùng string concatenation với `/`
- **Vendor binary size**: `vendor/` thêm ~80MB vào repo (FFmpeg ~70MB + aria2c ~5MB) — xem ADR-005
- **Python 3.12 requirement**: một số máy cũ có thể cần upgrade Python

### Không ảnh hưởng

- UI (Phase 5) dùng React + Vite — chạy trong Node.js, cross-platform tự nhiên
- Extension code là vanilla JS — chạy trong Chrome bất kể OS

---

## Alternatives considered

| Option | Lý do loại |
|--------|-----------|
| WSL | Chrome extension không kết nối được `127.0.0.1` trong WSL; `browser-cookie3` không đọc được Chrome profile Windows |
| Docker | Không thể access Chrome extension từ container; volume mount phức tạp cho `storage/` |
| Cross-platform | Không có nhu cầu; tăng complexity không cần thiết |

---

## References

- [spec 00 — folder structure](../00-folder-structure.md) — vendor/ directory
- [spec 01 — config](../01-config-spec.md) — Windows path handling
- [ADR-005](./ADR-005-ship-binary.md) — vendor binary decision
