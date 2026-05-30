# ADR-005 — Ship Vendor Binaries (FFmpeg, aria2c)

**Status**: Accepted  
**Date**: 2026-05-27  
**Deciders**: AIFlow project owner

---

## Context

AIFlow cần 2 external binary tools:

1. **FFmpeg** — xử lý video/audio: merge DASH streams, burn subtitle, encode output, probe duration, Ken Burns motion, overlay compositor
2. **aria2c** — parallel download: tải video segments từ Bilibili/Douyin CDN nhanh hơn (multi-connection)

Câu hỏi: **bundle binary vào repo hay yêu cầu user tự cài?**

### Các lựa chọn

#### Option 1: Yêu cầu user tự cài (rely on PATH)

User cài FFmpeg và aria2c thủ công, đặt vào PATH.

**Vấn đề**:
- **Version inconsistency**: FFmpeg 4.x, 5.x, 6.x, 7.x có API khác nhau. Một số filter (`-vf scale`, `-filter_complex`) thay đổi behavior giữa versions
- **PATH issues trên Windows**: nhiều user không biết cách thêm vào PATH; Windows không có package manager mặc định
- **Chocolatey/Scoop/winget**: không phải ai cũng có; version được cài có thể không phải 7.0+
- **Setup friction**: user mới phải làm thêm 2-3 bước trước khi chạy được AIFlow
- **CI/CD**: test environment cần cài FFmpeg riêng
- **Conflict**: user có thể đã có FFmpeg cũ trong PATH từ project khác

#### Option 2: Bundle binary trong `vendor/`

Download FFmpeg và aria2c vào `vendor/` directory, code dùng absolute path.

**Vấn đề**:
- **Repo size**: FFmpeg Windows binary ~70MB, aria2c ~5MB → tổng ~75MB thêm vào repo
- **Git LFS**: cần Git LFS nếu push lên GitHub (file >50MB)
- **Binary update**: khi cần update FFmpeg, phải download lại và commit binary mới

#### Option 3: Download on first run (lazy install)

Script tự download FFmpeg/aria2c khi chạy lần đầu, lưu vào `vendor/`.

**Vấn đề**:
- Cần internet connection khi setup
- Download URL có thể thay đổi
- Phức tạp hơn: cần verify checksum, handle download failure
- Vẫn cần logic "check if exists, download if not" mỗi lần start

#### Option 4: Dùng `moviepy` / Python bindings

Dùng Python library thay vì FFmpeg subprocess trực tiếp.

**Vấn đề**:
- `moviepy` vẫn cần FFmpeg binary bên dưới
- Python bindings thường lag sau FFmpeg features mới
- Không đủ control cho complex filter graphs (overlay, Ken Burns, DASH merge)

---

## Decision

**Bundle FFmpeg 7.0+ và aria2c vào `vendor/` directory. Code dùng absolute path tới binary.**

Cụ thể:
- **FFmpeg**: `vendor/ffmpeg.exe` + `vendor/ffprobe.exe` — version 7.0+ (pinned)
- **aria2c**: `vendor/aria2c.exe` — version 1.37+ (pinned)
- **Source**: download từ official releases (ffmpeg.org, aria2.github.io)
- **Path resolution**: `server/render/ffmpeg_utils.py` resolve path từ `settings.vendor_dir / "ffmpeg.exe"`
- **Git**: commit binary vào repo (không dùng Git LFS cho personal project)
- **gitignore**: `vendor/*.exe` KHÔNG bị ignore — ship theo project
- **Version pin**: ghi version trong `vendor/README.md`

### Path resolution pattern

```python
# server/render/ffmpeg_utils.py
from pathlib import Path
from server.config import get_settings

def get_ffmpeg_path() -> Path:
    settings = get_settings()
    ffmpeg = settings.vendor_dir / "ffmpeg.exe"
    if not ffmpeg.exists():
        raise RuntimeError(
            f"FFmpeg not found at {ffmpeg}. "
            "Run: python scripts/download_vendor.py"
        )
    return ffmpeg
```

### Download script (cho setup lần đầu hoặc update)

```bash
python scripts/download_vendor.py
# Downloads FFmpeg 7.0 + aria2c 1.37 to vendor/
# Verifies SHA256 checksums
```

---

## Consequences

### Tích cực

- **Zero-dependency setup**: user clone repo → `pip install -e .` → chạy ngay, không cần cài FFmpeg/aria2c
- **Version pinned**: mọi developer và user đều dùng cùng version, không có "works on my machine"
- **Windows native**: binary được build cho Windows x64, không cần WSL hay Cygwin
- **Absolute path**: không bao giờ bị ảnh hưởng bởi PATH của user
- **Reproducible**: CI/CD test với cùng binary version
- **aria2c parallel**: tải Bilibili DASH segments nhanh hơn 3-5× so với single-connection

### Tiêu cực / Trade-offs

- **Repo size**: +75MB cho `vendor/` — đáng kể cho personal project nhưng chấp nhận được
- **Git clone time**: clone lần đầu chậm hơn ~30-60 giây tùy internet
- **Binary update**: khi FFmpeg release version mới với bug fix quan trọng, phải download lại và commit. Không tự động
- **License**: FFmpeg là LGPL/GPL — ship binary cần comply với license. FFmpeg static build thường là GPL. Ghi rõ trong `LICENSE_NOTICES.md`
- **Antivirus**: một số antivirus có thể flag binary lạ trong repo. Mitigation: download từ official source, verify checksum

### FFmpeg license note

FFmpeg có thể được build với GPL hoặc LGPL tùy configuration. Build từ gpl.yannis.lu hoặc BtbN/FFmpeg-Builds thường là GPL. Cho personal use không có vấn đề. Nếu distribute, cần dùng LGPL build hoặc comply với GPL.

---

## Alternatives considered

| Option | Lý do loại |
|--------|-----------|
| Rely on PATH | Version inconsistency; setup friction; Windows PATH issues |
| Lazy download on first run | Phức tạp hơn; cần internet khi setup; URL có thể thay đổi |
| Python bindings (moviepy) | Vẫn cần FFmpeg; không đủ control cho complex filters |
| Chocolatey/Scoop install script | Không phải ai cũng có; version không guaranteed |
| Docker với FFmpeg | Overkill; không phù hợp với Windows native approach (ADR-001) |

---

## References

- [ADR-001](./ADR-001-native-windows.md) — Windows native decision
- [spec 00 — folder structure](../00-folder-structure.md) — vendor/ directory
- [spec 03 — api contract](../03-api-contract.md) — render pipeline
- PLAN.md Risk #3 — FFmpeg/moviepy Windows path + sync drift
- `vendor/README.md` — version pins và download instructions
- FFmpeg official: https://ffmpeg.org/download.html
- aria2 official: https://github.com/aria2/aria2/releases
