# 04 — Extension Bridge Spec

> **Status**: Draft for review
> **Depends on**: 03-api-contract
> **Used by**: server (consumer of Veo3 + cookies)

## Mục đích

Spec cho 1 Chrome MV3 extension duy nhất (`AIFlow Bridge`) có 2 module:
- **Module A (`flow_proxy`)** — proxy Veo3 / Imagen API qua session đã đăng nhập của user trên `labs.google/fx/tools/flow` (LIFT từ flowboard).
- **Module B (`cookie_sniffer`)** — capture cookies từ `bilibili.com`, `douyin.com`, `tiktok.com` (LIFT từ Douyin_TikTok_Download_API/chrome-cookie-sniffer).

Quyết định gộp đã ghi nhận trong ADR-0003.

## Tại sao gộp

| Vấn đề nếu tách 2 extension | Giải pháp gộp |
|------------------------------|----------------|
| User phải cài 2 ext, bật/tắt 2 chỗ | Cài 1 lần, popup duy nhất |
| 2 service worker chạy song song → tốn RAM | 1 service worker, share state |
| 2 WS connection tới agent → port quản lý phức tạp | 1 WS connection, multiplex messages |
| Permission chồng chéo (`storage`, `cookies`, `webRequest`) | Khai báo 1 lần |
| Branding lộn xộn | 1 logo, 1 popup |

## Stack

- **Chrome Manifest V3** (Edge cũng hỗ trợ MV3)
- Vanilla JS, không build tool. Lý do:
  - Extension nhỏ (~30-50 KB), không cần bundler
  - Reload nhanh khi develop (`chrome://extensions` → reload)
  - Lift code từ flowboard và chrome-cookie-sniffer đều vanilla JS
- Service worker (background.js) là entry chính
- Content scripts inject vào các trang target

## File structure

```
extension/
├── manifest.json
├── background.js              ← Service worker — orchestrator
├── content.js                 ← Inject vào labs.google/fx/tools/flow
├── injected.js                ← MAIN world cho window.grecaptcha
├── modules/
│   ├── shared.js              ← WS connect, auth secret, common utils
│   ├── flow_proxy.js          ← Module A: Veo3 token + API proxy
│   └── cookie_sniffer.js      ← Module B: Bilibili/Douyin cookie capture
├── popup/
│   ├── popup.html
│   ├── popup.js
│   └── popup.css
├── rules.json                 ← declarativeNetRequest CORS rules
└── icons/
    ├── icon16.png
    ├── icon48.png
    └── icon128.png
```

## manifest.json (đầy đủ)

```json
{
  "manifest_version": 3,
  "name": "AIFlow Bridge",
  "version": "0.1.0",
  "description": "Bridge between AIFlow agent and authenticated browser sessions (Google Flow + Bilibili + Douyin).",
  
  "permissions": [
    "storage",
    "alarms",
    "tabs",
    "webRequest",
    "scripting",
    "declarativeNetRequest",
    "cookies"
  ],
  
  "host_permissions": [
    "https://aisandbox-pa.googleapis.com/*",
    "https://labs.google/*",
    "https://www.bilibili.com/*",
    "https://api.bilibili.com/*",
    "https://*.douyin.com/*",
    "https://*.tiktok.com/*",
    "http://127.0.0.1:8101/*",
    "http://localhost:8101/*"
  ],
  
  "background": {
    "service_worker": "background.js",
    "type": "module"
  },
  
  "action": {
    "default_title": "AIFlow Bridge",
    "default_popup": "popup/popup.html",
    "default_icon": {
      "16":  "icons/icon16.png",
      "48":  "icons/icon48.png",
      "128": "icons/icon128.png"
    }
  },
  
  "content_scripts": [
    {
      "matches": [
        "https://labs.google/fx/tools/flow*",
        "https://labs.google/fx/*/tools/flow*"
      ],
      "js": ["content.js"],
      "run_at": "document_start"
    }
  ],
  
  "web_accessible_resources": [
    {
      "resources": ["injected.js"],
      "matches": ["https://labs.google/*"]
    }
  ],
  
  "declarative_net_request": {
    "rule_resources": [
      {
        "id": "aiflow_rules",
        "enabled": true,
        "path": "rules.json"
      }
    ]
  }
}
```

## Permissions justification

| Permission | Tại sao cần |
|------------|-------------|
| `storage` | Lưu callbackSecret, captured tokens, cache cookies |
| `alarms` | Reconnect WS sau disconnect, keep service worker alive |
| `tabs` | Open Flow tab nếu user click "Start" mà chưa có |
| `webRequest` | Capture Authorization Bearer header từ Flow API calls |
| `scripting` | Future use — hiện chưa dùng nhưng cần khi inject thêm |
| `declarativeNetRequest` | Override CORS để extension fetch CDN URL |
| `cookies` | Module B đọc cookies Bilibili/Douyin/TikTok |
| `host_permissions` cụ thể | Tránh `<all_urls>` (security best practice) |

## background.js — Service Worker

### Responsibilities

1. **WS lifecycle**: connect, reconnect, heartbeat
2. **Message routing**: dispatch tới module A hoặc B
3. **Token capture**: webRequest listener cho `Bearer ya29.*`
4. **Cookie capture**: cookie listener cho 3 platform
5. **State persistence**: chrome.storage.local
6. **Popup state broadcast**: send updates tới popup khi mở

### Pseudo-code structure

```javascript
// background.js
import { connectAgent, send, onMessage } from "./modules/shared.js";
import { initFlowProxy, handleFlowMessage } from "./modules/flow_proxy.js";
import { initCookieSniffer, handleCookieMessage } from "./modules/cookie_sniffer.js";

const state = {
  ws: null,
  callbackSecret: null,
  flow: { token: null, capturedAt: null, userInfo: null },
  cookies: { bilibili: null, douyin: null, tiktok: null },
};

chrome.runtime.onInstalled.addListener(init);
chrome.runtime.onStartup.addListener(init);

async function init() {
  await loadState();
  initFlowProxy(state);
  initCookieSniffer(state);
  await connectAgent(state, dispatchMessage);
  scheduleKeepAlive();
}

async function dispatchMessage(msg) {
  switch (msg.type) {
    case "callback_secret":
      state.callbackSecret = msg.secret;
      await persistState();
      send({ type: "extension_ready", version: "0.1.0", modules: ["flow_proxy", "cookie_sniffer"] });
      break;
      
    case "api_request":
    case "get_captcha":
      return handleFlowMessage(msg, state);
      
    case "read_cookie":
      return handleCookieMessage(msg, state);
      
    case "ping":
      send({ type: "pong" });
      break;
  }
}

// ... etc
```

### Module A — flow_proxy.js

**Lift gần như nguyên** từ `flowboard/extension/background.js` (lines liên quan token capture + api_request handler).

Responsibilities:
- Listen `webRequest.onBeforeSendHeaders` → catch `Bearer ya29.*` từ Flow → send `token_captured` lên agent
- Handle `api_request` từ agent: thực hiện `fetch()` trong session user, post response qua HTTP callback `/api/ext/callback`
- Forward `get_captcha` xuống content.js → injected.js (MAIN world) → `window.grecaptcha.enterprise.execute()`
- Periodic fetch user info từ `/v1/credits` để cập nhật plan + credits

Code lift checklist:
- ✅ `classifyUrl(url)` — phân loại GEN_IMG / GEN_VID / POLL
- ✅ Token capture filter `Bearer ya29.`
- ✅ `requestLog` (last 50 entries cho popup)
- ✅ `fetchAndPushUserInfo(token)` — gọi userinfo + paygate tier
- ✅ `dispatchApiRequest(msg)` — fetch + callback POST

### Module B — cookie_sniffer.js

**Lift** từ `Douyin_TikTok_Download_API/chrome-cookie-sniffer/background.js`, mở rộng cho Bilibili + TikTok.

Responsibilities:
- Watch cookie changes via `chrome.cookies.onChanged`
- Periodic poll cookies (mỗi 5 phút) cho 3 platform
- Dedupe: chỉ emit khi cookie content thay đổi
- Send `cookie_captured` qua WS với platform + cookie string

Service config (đã mở rộng):
```javascript
const PLATFORMS = {
  bilibili: {
    name: 'bilibili',
    domains: ['bilibili.com'],
    cookieDomain: '.bilibili.com',
    keys: ['SESSDATA', 'bili_jct', 'DedeUserID', 'buvid3', 'buvid4'],  // Critical keys
    minRequiredKeys: ['SESSDATA'],  // Tối thiểu phải có
  },
  douyin: {
    name: 'douyin',
    domains: ['douyin.com'],
    cookieDomain: '.douyin.com',
    keys: ['msToken', 'ttwid', 'sessionid', 'sessionid_ss', 'odin_tt', 'passport_csrf_token'],
    minRequiredKeys: ['ttwid'],
  },
  tiktok: {
    name: 'tiktok',
    domains: ['tiktok.com'],
    cookieDomain: '.tiktok.com',
    keys: ['tt_chain_token', 'msToken', 'sessionid', 'sid_tt'],
    minRequiredKeys: ['msToken'],
  },
};
```

### shared.js — WS + auth

```javascript
// HTTP port cố định — extension phải biết 1 endpoint để hỏi (REVIEW-01 #2)
// Nếu user đổi AIFLOW_PORT, phải edit dòng này 1 lần.
const AGENT_BASE  = 'http://127.0.0.1:8101';
const DISCOVERY   = `${AGENT_BASE}/api/ext/discovery`;
const CALLBACK_URL = `${AGENT_BASE}/api/ext/callback`;

// REVIEW-02 #5 — Track attempts để hiện UX message hữu ích
let dynamicConfig = null;
let discoverAttempts = 0;
const MAX_QUIET_ATTEMPTS = 5;  // 5 × 3s = 15s trước khi hiện hint

// State exposed cho popup.js
const popupState = {
  status: 'connecting',          // 'connecting' | 'agent_not_running' | 'connected' | 'token_missing'
  agentUrl: AGENT_BASE,
  attemptCount: 0,
};

export function getPopupState() {
  return { ...popupState, attemptCount: discoverAttempts };
}

export async function discoverAgent() {
  /**
   * REVIEW-02 #5 — Retry vô hạn (đúng) nhưng update popupState mỗi attempt
   * để UI hiển thị 4 trạng thái distinct:
   *
   *   discoverAttempts < 5  →  "Connecting..." (spinner nhỏ)
   *   discoverAttempts >= 5 →  "Agent not running. Run: python -m server.main"
   *   WS connected          →  "Connected" (xanh)
   *   WS connected, no tok  →  "Connected — token missing. Open labs.google/fx/tools/flow"
   *
   * Service worker MV3 idle ~5 phút sẽ sleep — alarm wake mỗi 24s ping lại.
   */
  while (true) {
    try {
      const resp = await fetch(DISCOVERY, { cache: 'no-store' });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      
      // Success → reset counter + state
      discoverAttempts = 0;
      popupState.status = 'connecting';  // sẽ chuyển 'connected' sau WS handshake
      
      dynamicConfig = await resp.json();
      console.log('[AIFlow] Agent discovered:', dynamicConfig);
      
      if (compareVersion(chrome.runtime.getManifest().version, dynamicConfig.min_extension_version) < 0) {
        console.warn('[AIFlow] Extension older than agent expects — please update');
      }
      return dynamicConfig;
      
    } catch (e) {
      discoverAttempts++;
      
      if (discoverAttempts >= MAX_QUIET_ATTEMPTS) {
        popupState.status = 'agent_not_running';
        console.log(
          `[AIFlow] Agent not reachable after ${discoverAttempts} attempts. ` +
          `Run: python -m server.main`
        );
      } else {
        popupState.status = 'connecting';
        console.log(`[AIFlow] Agent not ready (attempt ${discoverAttempts}), retry in 3s`);
      }
      
      await sleep(3000);
    }
  }
}

export async function connectAgent(state, dispatch) {
  if (!dynamicConfig) await discoverAgent();
  
  state.ws = new WebSocket(dynamicConfig.ws_url);
  
  state.ws.onopen = () => {
    state.connected = true;
    // Trạng thái 'connected' nhưng chưa có token — popup vẫn show hint
    popupState.status = state.flow?.token ? 'connected' : 'token_missing';
  };
  
  state.ws.onmessage = (e) => dispatch(JSON.parse(e.data));
  
  state.ws.onclose = () => {
    state.connected = false;
    popupState.status = 'connecting';
    // Có thể agent restart đổi port — re-discover trước khi reconnect
    dynamicConfig = null;
    scheduleReconnect(state, dispatch);
  };
}

// Sau khi capture token, gọi hàm này để update popup
export function onTokenCaptured(state) {
  state.flow.token = '<captured>';  // không log raw
  if (popupState.status === 'token_missing') {
    popupState.status = 'connected';
  }
}

export function send(msg) {
  if (state.ws?.readyState === WebSocket.OPEN) {
    state.ws.send(JSON.stringify(msg));
  }
}

export async function postCallback(state, payload) {
  return fetch(CALLBACK_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Callback-Secret': state.callbackSecret,
    },
    body: JSON.stringify(payload),
  });
}

function compareVersion(a, b) {
  const pa = a.split('.').map(Number);
  const pb = b.split('.').map(Number);
  for (let i = 0; i < 3; i++) {
    if (pa[i] !== pb[i]) return pa[i] - pb[i];
  }
  return 0;
}

const sleep = (ms) => new Promise(r => setTimeout(r, ms));
```

## content.js + injected.js

**Lift nguyên** từ `flowboard/extension/`. Chức năng duy nhất: bridge `chrome.runtime.sendMessage({type:"GET_CAPTCHA"})` → MAIN world `window.dispatchEvent("GET_CAPTCHA")` → `window.grecaptcha.enterprise.execute()`.

## popup.html

UI minimal, 1 trang, hiển thị **4 trạng thái** dựa trên `getPopupState()` (REVIEW-02 #5):

```
┌─────────────────────────────────────────┐
│  AIFlow Bridge                          │
├─────────────────────────────────────────┤
│                                         │
│  Agent connection: [STATUS]             │
│                                         │
└─────────────────────────────────────────┘

[STATUS] ứng với 4 trạng thái:

  status='connecting' (< 5 attempts)
    🟡 Connecting... (15s)
       Đang dò agent tại 127.0.0.1:8101

  status='agent_not_running' (>= 5 attempts)
    🔴 Agent not running
       Run: python -m server.main
       (default port 8101)

  status='token_missing' (WS connected, chưa capture)
    🟡 Connected — token missing
       Open: labs.google/fx/tools/flow

  status='connected' (full)
    🟢 Connected
       Account: user@gmail.com (Pro)
       Credits: 37 / 100 today
```

Full popup khi `connected`:

```
┌─────────────────────────────────────────┐
│  AIFlow Bridge                          │
├─────────────────────────────────────────┤
│                                         │
│  Agent connection: 🟢 Connected         │
│  Agent: 127.0.0.1:8101                  │
│                                         │
├─ Module A: Google Flow ──────────────────┤
│                                         │
│  Status:    🟢 Active                   │
│  Account:   user@gmail.com (Pro)        │
│  Token:     captured 5min ago           │
│  Credits:   37 / 100 today              │
│  Requests:  142 success / 3 failed      │
│                                         │
│  [ Open Flow tab ]  [ Refresh user ]    │
│                                         │
├─ Module B: Cookie Sniffer ───────────────┤
│                                         │
│  Bilibili:  🟢 Valid (captured 2h ago)  │
│  Douyin:    🟡 ttwid only, no msToken   │
│  TikTok:    ⚪ Not captured             │
│                                         │
│  [ Refresh all ]  [ Open Bili ]         │
│                                         │
├─────────────────────────────────────────┤
│  Last log: api_request OK 200 (gen_vid) │
│  [ View full log ]                      │
└─────────────────────────────────────────┘
```

popup.js fetch state mỗi 1s từ background qua `chrome.runtime.sendMessage({type:'GET_STATE'})`,
background trả `getPopupState()`.

## rules.json

```json
[
  {
    "id": 1,
    "priority": 1,
    "action": {
      "type": "modifyHeaders",
      "responseHeaders": [
        { "header": "Access-Control-Allow-Origin", "operation": "set", "value": "*" }
      ]
    },
    "condition": {
      "urlFilter": "lh3.googleusercontent.com",
      "resourceTypes": ["xmlhttprequest", "image"]
    }
  },
  {
    "id": 2,
    "priority": 1,
    "action": {
      "type": "modifyHeaders",
      "responseHeaders": [
        { "header": "Access-Control-Allow-Origin", "operation": "set", "value": "*" }
      ]
    },
    "condition": {
      "urlFilter": "*.douyinpic.com",
      "resourceTypes": ["xmlhttprequest"]
    }
  }
]
```

(Lift từ flowboard rules.json + thêm douyin CDN nếu cần.)

## Security & privacy

### Cookies (sensitive PII)

- Cookies KHÔNG được persist trong `chrome.storage.local` quá 5 phút
- Mỗi lần đọc → push trực tiếp lên agent qua HTTPS-equivalent (localhost) → forget
- Agent persist trong `storage/cookies/{platform}.txt` (gitignored), file permission 600 (Windows: ACL chỉ user)
- Popup không hiển thị raw cookie string, chỉ hiện status + số key đã captured

### Token

- `flowKey` (Bearer ya29.*) chỉ lưu in-memory + chrome.storage.local
- KHÔNG log raw token bất kỳ đâu (background.js, popup.js, agent)
- Token rotate mỗi ~1 giờ, agent không persist > duration session

### Callback secret

- Generate runtime mỗi server start: `secrets.token_urlsafe(32)`
- Gửi cho extension qua WS lúc handshake
- Mọi POST tới `/api/ext/callback` phải có header `X-Callback-Secret`
- Server verify constant-time compare

### Permissions audit

- KHÔNG request `<all_urls>`
- KHÔNG request `tabs.captureVisibleTab` (capture screenshot)
- KHÔNG request `nativeMessaging`
- Manifest tách rõ `host_permissions` cho từng domain cần thiết

## Error handling

### WS disconnect

```
Connect attempt → fail → backoff 1s, 2s, 4s, 8s, 16s, 30s (max)
Service worker idle → alarm wake-up mỗi 24s ping
```

### Token expired

- Flow API trả 401 → extension emit `token_expired`
- Agent pause queue, send error tới UI: "Open Flow tab to refresh token"
- User active tab → webRequest re-capture mới → resume

### API_request timeout

- Server đợi callback max 180s
- Timeout → agent mark request `failed`, retry tối đa 2 lần
- Sau 2 fail → bubble lên user với code `EXTENSION_TIMEOUT`

### Cookie không có msToken

- Module B emit `cookie_captured` với `partial: true`
- Agent log warning, không reject — thử request, nếu fail bới error code mới biết

## Install + dev workflow

### User (production)

1. Tải `extension.zip` từ release
2. Extract
3. Chrome → `chrome://extensions` → Developer mode → Load unpacked → chọn folder
4. Mở Flow tab → token capture
5. Mở Bilibili / Douyin → cookie capture

### Dev

1. Code edit
2. Chrome → `chrome://extensions` → reload icon
3. Service worker tự restart
4. Test qua popup

## Acceptance criteria cho spec này

- [ ] Manifest V3 đầy đủ với justified permissions
- [ ] Module A và B isolated, có thể disable 1 module qua flag
- [ ] WS protocol thống nhất với spec 03 API contract
- [ ] Cookie sniffer hỗ trợ ≥ 3 platform (Bilibili, Douyin, TikTok)
- [ ] Popup hiển thị state cả 2 module
- [ ] Security: callback secret, no token logging, cookies short-lived in extension
- [ ] Phase 0 chỉ cần Module A working; Module B Phase 4.5

## Phase mapping

| Component | Phase |
|-----------|-------|
| manifest.json + background.js skeleton | 0 |
| Module A (flow_proxy) | 0 |
| Popup basic | 0-1 |
| Module B (cookie_sniffer) | 4.5 |
| rules.json mở rộng | 4.5 |
