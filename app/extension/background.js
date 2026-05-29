/**
 * AIFlow Bridge — background.js
 * Chrome Extension Service Worker — orchestrator.
 *
 * Responsibilities:
 *  1. WS lifecycle: connect, reconnect, heartbeat
 *  2. Message routing: dispatch to Module A (flow_proxy) or Module B (cookie_sniffer — Phase 4.5)
 *  3. State persistence: chrome.storage.local
 *  4. Popup state broadcast: send updates to popup when open
 */

import { connectAgent, sendWs, getPopupState, discoverAgent } from './modules/shared.js';
import {
  initFlowProxy,
  handleFlowMessage,
  fetchAndPushUserInfo,
  getCachedUserInfo,
  clearCachedUserInfo,
  captureTokenFromFlowTab,
  openFlowTab,
  getRequestLog,
} from './modules/flow_proxy.js';
import {
  initCookieSniffer,
  handleCookieMessage,
  getCookieStatus,
} from './modules/cookie_sniffer.js';

// ─── Shared State ────────────────────────────────────────────

const state = {
  ws:             null,
  connected:      false,
  callbackSecret: null,
  flow: {
    token:       null,
    capturedAt:  null,
  },
  // cookie_sniffer state — Phase 4.5
  cookies: {
    bilibili: null,  // { value, capturedAt, source } | null
    douyin:   null,
    tiktok:   null,
  },
  metrics: {
    tokenCapturedAt: null,
    requestCount:    0,
    successCount:    0,
    failedCount:     0,
    lastError:       null,
  },
  _dispatch: null,
};

// ─── Startup ─────────────────────────────────────────────────

chrome.runtime.onInstalled.addListener(init);
chrome.runtime.onStartup.addListener(init);

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'reconnect') {
    connectAgent(state, dispatchMessage).catch((e) =>
      console.error('[AIFlow] Reconnect failed:', e)
    );
  }
  if (alarm.name === 'keepAlive') keepAlive();
});

async function init() {
  const data = await chrome.storage.local.get(['flowKey', 'flowCapturedAt', 'metrics', 'callbackSecret']);
  if (data.flowKey)        state.flow.token      = data.flowKey;
  if (data.flowCapturedAt) state.flow.capturedAt = data.flowCapturedAt;
  if (data.metrics)        Object.assign(state.metrics, data.metrics);
  if (data.callbackSecret) state.callbackSecret  = data.callbackSecret;

  initFlowProxy(state);
  initCookieSniffer(state);  // Module B — Phase 4.5

  await connectAgent(state, dispatchMessage);

  // Keep service worker alive — MV3 idles after ~5 min
  chrome.alarms.create('keepAlive', { periodInMinutes: 0.4 }); // ~24s
}

// ─── Message Dispatcher ──────────────────────────────────────

async function dispatchMessage(msg) {
  switch (msg.type) {
    case 'callback_secret':
      state.callbackSecret = msg.secret;
      chrome.storage.local.set({ callbackSecret: msg.secret });
      console.log('[AIFlow] Received callback secret');
      sendWs(state, {
        type:    'extension_ready',
        version: chrome.runtime.getManifest().version,
        modules: ['flow_proxy', 'cookie_sniffer'],
      });
      // Replay token if we already have one
      if (state.flow.token) {
        sendWs(state, { type: 'token_captured', flowKey: state.flow.token });
      }
      // Replay cached userinfo
      const cached = getCachedUserInfo();
      if (cached) {
        sendWs(state, { type: 'user_info', userInfo: cached });
      } else if (state.flow.token) {
        fetchAndPushUserInfo(state, state.flow.token);
      }
      break;

    case 'pong':
      // keepalive response — no-op
      break;

    case 'ping':
      sendWs(state, { type: 'pong' });
      break;

    case 'api_request':
    case 'get_captcha':
    case 'please_resend_userinfo':
    case 'logout':
      await handleFlowMessage(msg, state);
      break;

    case 'read_cookie':
    case 'get_cookies':
      await handleCookieMessage(msg, state);
      break;

    default:
      // Check method field (flowboard protocol uses msg.method)
      if (msg.method === 'api_request' || msg.method === 'trpc_request' || msg.method === 'get_status') {
        if (msg.method === 'get_status') {
          sendWs(state, {
            id:     msg.id,
            result: {
              connected:       state.connected,
              flowKeyPresent:  !!state.flow.token,
              tokenAge:        state.flow.capturedAt ? Date.now() - state.flow.capturedAt : null,
              metrics:         state.metrics,
            },
          });
        } else {
          await handleFlowMessage(msg, state);
        }
      }
      break;
  }

  broadcastStatus();
}

// ─── Keep Alive ──────────────────────────────────────────────

function keepAlive() {
  if (state.ws?.readyState === WebSocket.OPEN) {
    sendWs(state, { type: 'ping' });
  } else {
    connectAgent(state, dispatchMessage).catch(() => {});
  }
}

// ─── Badge / Status ──────────────────────────────────────────

function broadcastStatus() {
  const ps = getPopupState();
  const badges = {
    connected:        '●',
    token_missing:    '◑',
    connecting:       '○',
    agent_not_running:'✕',
  };
  const colors = {
    connected:        '#22c55e',
    token_missing:    '#f5b301',
    connecting:       '#6b7280',
    agent_not_running:'#ef4444',
  };
  const badge = badges[ps.status] || '○';
  const color = colors[ps.status] || '#6b7280';
  chrome.action.setBadgeText({ text: badge });
  chrome.action.setBadgeBackgroundColor({ color });
  chrome.runtime.sendMessage({ type: 'STATUS_PUSH' }).catch(() => {});
}

// ─── Popup Message Handlers ──────────────────────────────────

chrome.runtime.onMessage.addListener((msg, _, reply) => {
  if (msg.type === 'GET_STATE') {
    const ps = getPopupState();
    reply({
      ...ps,
      connected:      state.connected,
      flowKeyPresent: !!state.flow.token,
      tokenAge:       state.flow.capturedAt ? Date.now() - state.flow.capturedAt : null,
      metrics:        { ...state.metrics },
      userInfo:       getCachedUserInfo(),
      cookieStatus:   getCookieStatus(state),
    });
    return true;
  }

  // Legacy STATUS message (compat with flowboard popup.js)
  if (msg.type === 'STATUS') {
    reply({
      connected:       state.connected,
      flowKeyPresent:  !!state.flow.token,
      manualDisconnect: false,
      tokenAge:        state.flow.capturedAt ? Date.now() - state.flow.capturedAt : null,
      metrics:         { ...state.metrics },
      state:           state.connected ? 'idle' : 'off',
    });
    return true;
  }

  if (msg.type === 'REQUEST_LOG') {
    reply({ log: getRequestLog() });
    return true;
  }

  if (msg.type === 'OPEN_FLOW_TAB') {
    openFlowTab()
      .then((result) => reply(result))
      .catch((e) => reply({ error: e.message }));
    return true;
  }

  if (msg.type === 'REFRESH_TOKEN') {
    captureTokenFromFlowTab()
      .then(() => reply({ ok: true }))
      .catch((e) => reply({ error: e.message }));
    return true;
  }

  if (msg.type === 'DISCONNECT') {
    state.ws?.close();
    reply({ ok: true });
    return true;
  }

  if (msg.type === 'RECONNECT') {
    connectAgent(state, dispatchMessage)
      .then(() => reply({ ok: true }))
      .catch((e) => reply({ error: e.message }));
    return true;
  }

  if (msg.type === 'REFRESH_COOKIES') {
    // Trigger an immediate poll for all platforms
    handleCookieMessage({ type: 'get_cookies', platform: 'all' }, state)
      .then(() => reply({ ok: true }))
      .catch((e) => reply({ error: e.message }));
    return true;
  }

  return true;
});

console.log('[AIFlow] Extension loaded — AIFlow Bridge v' + chrome.runtime.getManifest().version);
