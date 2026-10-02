# Third-Party License Notices

This file tracks all lifted/ported code from reference projects.

## Phase 0 — No third-party code yet

Phase 0 is skeleton only. Third-party components will be added in later phases:

- **Phase 0.4-0.5**: flowboard extension + flow_client + flow_sdk (MIT license)
- **Phase 3**: MoneyPrinterTurbo TTS + Whisper (MIT license)
- **Phase 4.1**: daihuo-jianshou prompts (MIT license)
- **Phase 4.5**: Douyin_TikTok_Download_API crawlers (GPL v3 — see note below)
- **Phase 7**: VectCutAPI pyJianYingDraft (MIT license)

## Signing components (Phase 4.5) — IMPLEMENTED

The anti-bot signing modules in `server/content/crawlers/signing/` are now real
implementations (previously stubs). They carry **different licenses** and are
isolated inside the `signing` package so the rest of AIFlow (personal use)
stays clean. See `signing/__init__.py` ISOLATION NOTE.

| Module | Origin | License | Notes |
|--------|--------|---------|-------|
| `a_bogus.py` | TikTokDownloader (JoeanAmier) via Douyin_TikTok_Download_API (Evil0ctal) | **GPL v3** | Pure-Python `ABogus` (SM3+RC4). Requires `gmssl`. Douyin signing. |
| `x_bogus.py` | Douyin_TikTok_Download_API (Evil0ctal) | **Apache 2.0** | `XBogus` (MD5+RC4), stdlib only. Douyin signing. |
| `wbi.py` | AIFlow | **Clean-room** (project license) | Bilibili WBI (`MIXIN_KEY_ENC_TAB` + MD5). Public algorithm, no third-party code copied. |
| `update_check.py` | AIFlow | project license | GitHub commit checker for the lifted modules. |

Upstream reference: <https://github.com/Evil0ctal/Douyin_TikTok_Download_API>
Original A-Bogus author: <https://github.com/JoeanAmier/TikTokDownloader>

**GPL v3 obligation (a_bogus.py only)**: Personal use does NOT trigger
source-disclosure. If AIFlow is ever distributed publicly or commercially,
`a_bogus.py` must be either:
1. Isolated into a separate subprocess/service, OR
2. Replaced with a clean-room implementation, OR
3. The whole project relicensed under GPL v3.

`x_bogus.py` (Apache 2.0) and `wbi.py` (clean-room) do NOT carry copyleft
obligations.

## GPL v3 Components (Phase 4.5+) — historical note

The following note predates the implementation above and is kept for context.

The following components from `Douyin_TikTok_Download_API` are licensed under GPL v3:
- `a_bogus.py` — Douyin anti-bot signing
- `x_bogus.py` — Douyin anti-bot signing
- `wbi.py` — Bilibili WBI signing

**Personal use exemption**: GPL v3 does not require source disclosure for personal use.

If this project is ever made public or commercial, these components must be:
1. Isolated into a separate subprocess/service, OR
2. Replaced with clean-room implementations, OR
3. The entire project relicensed under GPL v3

## Full Attribution

Detailed attribution will be added as components are lifted in each phase.

Last updated: 2026-05-27 (Phase 0.1)
