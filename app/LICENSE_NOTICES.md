# Third-Party License Notices

This file tracks all lifted/ported code from reference projects.

## Phase 0 — No third-party code yet

Phase 0 is skeleton only. Third-party components will be added in later phases:

- **Phase 0.4-0.5**: flowboard extension + flow_client + flow_sdk (MIT license)
- **Phase 3**: MoneyPrinterTurbo TTS + Whisper (MIT license)
- **Phase 4.1**: daihuo-jianshou prompts (MIT license)
- **Phase 4.5**: Douyin_TikTok_Download_API crawlers (GPL v3 — see note below)
- **Phase 7**: VectCutAPI pyJianYingDraft (MIT license)

## GPL v3 Components (Phase 4.5+)

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
