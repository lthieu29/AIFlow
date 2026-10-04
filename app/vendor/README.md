# Vendor — Binary Dependencies

This folder contains Windows-native binaries shipped with AIFlow.
See [ADR-005](../docs/adr/ADR-005-ship-binary.md) for the rationale.

## Binaries

| Binary | Version | Purpose | License |
|--------|---------|---------|---------|
| `ffmpeg.exe` | 8.1.3 (GPL build, 330caae0c1) | Video/audio processing: merge DASH, burn subtitles, encode output, Ken Burns, overlay | GPL v2+ |
| `ffprobe.exe` | 8.1.3 (GPL build, 330caae0c1) | Media file inspection: probe duration, stream info | GPL v2+ |
| `aria2c.exe` | 1.37.0 | Parallel download for Bilibili/Douyin CDN segments | GPL v2+ |

## How to Download

Run the download script from the `app/` directory:

```bash
python scripts/download_vendor.py
```

The script is PATH-aware: if a binary is already available on your system
PATH (or already present in `vendor/`), it is **skipped** — the runtime
resolver falls back to PATH automatically, so there is no need for a second
copy. Use `--force` to download a pinned copy into `vendor/` regardless.

Options:

```bash
python scripts/download_vendor.py --force    # re-download even if present
python scripts/download_vendor.py --ffmpeg   # FFmpeg only
python scripts/download_vendor.py --aria2c   # aria2c only
```

The script will:
1. Check PATH / `vendor/` and skip anything already available
2. Download the official release zip from GitHub for what's missing
3. Verify the FFmpeg archive against the pinned upstream SHA256 before extraction
4. Extract the binary to `vendor/`
5. Verify the binary works (`-version` for FFmpeg, `--version` for aria2c)
6. Print the SHA256 checksum for pinning

## Download Sources

- **FFmpeg**: [BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds/releases) — GPL Windows x64 build
  - URL: `https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-10-01-13-06/ffmpeg-n8.1.3-14-g330caae0c1-win64-gpl-8.1.zip`
  - SHA256: `6aca87b75999c4793871754c5c2e211129a56a160c1654a7d1c9c518a7eda9c0`
  - Checksum source: [upstream checksums.sha256](https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-10-01-13-06/checksums.sha256), also matches the GitHub release asset digest.
  - The former `n7.1-latest` URL returns 404. Dated assets are pinned, but upstream may eventually remove old builds; keep the verified vendor binaries for offline use.
- **aria2c**: [aria2/aria2](https://github.com/aria2/aria2/releases) — Windows x64 release
  - URL: `https://github.com/aria2/aria2/releases/download/release-1.37.0/aria2-1.37.0-win-64bit-build1.zip`

## SHA256 Checksums

The archive checksum above is checked before extraction. Individual executable
checksums below identify the installed vendor files.

```
ffmpeg.exe   SHA256: 8e11e7ad62d949783eda7cdf904bb3a82355655bc9be512e60b320924fc02a58
ffprobe.exe  SHA256: 3739dfd1f2c1e7a52e482a94e5d957d0fda99d628c2ddd6a5cded9b6b6f41683
aria2c.exe   SHA256: be2099c214f63a3cb4954b09a0becd6e2e34660b886d4c898d260febfe9d70c2
```

To verify manually:

```powershell
Get-FileHash vendor\ffmpeg.exe  -Algorithm SHA256
Get-FileHash vendor\ffprobe.exe -Algorithm SHA256
Get-FileHash vendor\aria2c.exe  -Algorithm SHA256
```

## Path Resolution

Code resolves binary paths via `server/render/ffmpeg_utils.py`:

```python
from server.render.ffmpeg_utils import get_ffmpeg_path, get_ffprobe_path, get_aria2c_path

ffmpeg  = get_ffmpeg_path()   # vendor/ffmpeg.exe  → PATH fallback
ffprobe = get_ffprobe_path()  # vendor/ffprobe.exe → PATH fallback
aria2c  = get_aria2c_path()   # vendor/aria2c.exe  → PATH fallback
```

Search order: `vendor/{binary}.exe` first, then `shutil.which` (PATH).

## License Notes

- **FFmpeg** (GPL v2+): The BtbN build is a GPL build, meaning it includes GPL-licensed components (libx264, etc.). For personal use this is fine. If distributing AIFlow publicly, either use an LGPL build or comply with GPL requirements (provide source, etc.). See [FFmpeg License](https://ffmpeg.org/legal.html).
- **aria2c** (GPL v2+): aria2 is licensed under GPL v2 with OpenSSL exception. See [aria2 License](https://github.com/aria2/aria2/blob/master/COPYING).
- Both licenses are noted in `LICENSE_NOTICES.md`.

## Git Policy

Per ADR-005, `vendor/*.exe` binaries are **committed to the repository** (not gitignored). This ensures:
- Zero-dependency setup: clone → `pip install -e .` → run
- Version pinning: all developers use the same binary version
- No internet required after clone

The `vendor/` directory is excluded from `.gitignore` intentionally.

## Updating Binaries

To upgrade to a newer FFmpeg or aria2c version:

1. Update `FFMPEG_VERSION` / `ARIA2C_VERSION` in `scripts/download_vendor.py`
2. Update the download URLs accordingly
3. Run `python scripts/download_vendor.py --force`
4. Update the SHA256 checksums in this README
5. Commit the new binaries

## Phase Status

- **Phase 0**: Empty (binaries not needed yet)
- **Phase 3+**: `ffmpeg.exe` + `ffprobe.exe` required (audio compose, subtitle burn-in)
- **Phase 4.5+**: `aria2c.exe` required (Bilibili/Douyin parallel download)
