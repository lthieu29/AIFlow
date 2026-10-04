# AIFlow Bridge — Chrome Extension

Chrome MV3 extension that combines:
1. **Veo3 proxy** — uses the signed-in flow.google.com page, with legacy Bearer support for labs.google
2. **Cookie sniffer** — captures cookies for Bilibili/Douyin (Phase 4.5)

## Installation

1. Open Chrome → `chrome://extensions`
2. Enable "Developer mode" (top right)
3. Click "Load unpacked"
4. Select this folder: `D:\Project\AIFlow\app\extension`

## Usage

1. Start AIFlow agent: `python -m server.main`
2. Open the intended project at [flow.google.com](https://flow.google.com/)
3. Click "Check Flow session" in the extension popup; it checks the session with read-only GetModels.
   Session readiness and the normal Flow composer capability are checked separately.

## Architecture

- `background.js` — Service worker entry point
- `modules/flow_proxy.js` — Veo3 token capture + WS bridge
- `modules/flow_rpc.js` — current Flow cookie RPCs in page MAIN world; CSRF and captcha remain in the page
- `modules/flow_ui.js` — normal Angular composer controls and observation of their native generation result
- `modules/cookie_sniffer.js` — Cookie capture (Phase 4.5)
- `modules/shared.js` — WS connection + auth secret
- `content.js` — Injected into flow.google.com and legacy labs.google Flow pages
- `injected.js` — MAIN world for reCAPTCHA access
- `popup/` — Extension popup UI

The video pipeline reads the remote project UUID from an open Flow project tab.
Keep the intended project open; a local AIFlow project number is not a Google Flow project ID.
Text-to-video now uses the normal Flow composer: select Veo 3.1 Lite, 8 seconds, 720p,
landscape or portrait and one result, enter the approved prompt, then click the normal button.
The observer binds the native response to the exact prompt and project before returning its media ID.
An approved project PNG can be sent from Production Studio as an ingredient reference
(maximum 5 MiB). The extension verifies its SHA, uploads through the normal asset picker,
and selects the exact SHA filename; it never accepts the picker's default unrelated asset.
Ingredient reference generation was also verified through Client → backend → extension
on 2026-10-04: approved reference #4, scene #9, operation
`446460fc-9951-4e5d-915c-5744ac4a1456` produced media #5, an 8-second
1280×720, 24 fps H.264/AAC MP4. Review of four frames found the same actor,
cream shirt, olive overshirt and brown bag; each later clip still requires review.
The live asset picker uses `asset-item-active` while `aria-selected` can remain false.
Selection confirmation accepts that class only on the explicitly clicked exact SHA asset.
Existing drafts or composer references stop submission. Visible human verification stops automation;
the user must handle it. A click without a confirmed response remains ambiguous and is not retried.
The Vietnamese Angular UI route was verified through Client → backend → extension → Flow Lite,
including native submission, polling and MP4 download (8 seconds, 1280×720, 24 fps).
The separate RPC generation path retains its captcha guard and does not unwrap or bypass it.
Session RPCs run in the browser page without exporting its CSRF or captcha credentials.
The older REST image/video proxy remains available for sessions that supply a Bearer token.

## Tests

From `app`: `node --experimental-vm-modules --test extension/tests/bridge.test.mjs`

## Phase Status

- **Phase 0.2**: Skeleton + load test ✅
- **Phase 0.4**: WS connection (in progress)
- **Phase 4.5**: Cookie sniffer (not started)
