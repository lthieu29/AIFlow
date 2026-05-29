# AIFlow Bridge — Chrome Extension

Chrome MV3 extension that combines:
1. **Veo3 proxy** — captures Bearer token from labs.google
2. **Cookie sniffer** — captures cookies for Bilibili/Douyin (Phase 4.5)

## Installation

1. Open Chrome → `chrome://extensions`
2. Enable "Developer mode" (top right)
3. Click "Load unpacked"
4. Select this folder: `D:\Project\AIFlow\app\extension`

## Usage

1. Start AIFlow agent: `python -m server.main`
2. Open Flow tab: [labs.google/fx/tools/flow](https://labs.google/fx/tools/flow)
3. Extension popup shows "Connected" when ready

## Architecture

- `background.js` — Service worker entry point
- `modules/flow_proxy.js` — Veo3 token capture + WS bridge
- `modules/cookie_sniffer.js` — Cookie capture (Phase 4.5)
- `modules/shared.js` — WS connection + auth secret
- `content.js` — Injected into labs.google
- `injected.js` — MAIN world for reCAPTCHA access
- `popup/` — Extension popup UI

## Phase Status

- **Phase 0.2**: Skeleton + load test ✅
- **Phase 0.4**: WS connection (in progress)
- **Phase 4.5**: Cookie sniffer (not started)
