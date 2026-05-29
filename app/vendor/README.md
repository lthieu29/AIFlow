# Vendor — Binary Dependencies

This folder contains Windows native binaries shipped with AIFlow.

## Required Binaries (Phase 3+)

- `ffmpeg.exe` — video/audio processing (version 7.0+)
- `ffprobe.exe` — media file inspection
- `aria2c.exe` — parallel download for Bilibili/Douyin (Phase 4.5)

## Why Ship Binaries?

1. **Version pinning** — avoid PATH conflicts
2. **Windows native** — no WSL dependency
3. **User convenience** — no manual installation

## Download Sources

- FFmpeg: [ffmpeg.org/download.html](https://ffmpeg.org/download.html) (GPL build)
- aria2: [github.com/aria2/aria2/releases](https://github.com/aria2/aria2/releases)

## Phase Status

- **Phase 0**: Empty (not needed yet)
- **Phase 3**: Add ffmpeg.exe + ffprobe.exe
- **Phase 4.5**: Add aria2c.exe
