/**
 * AIFlow Bridge — shared.js
 * WS connection, agent discovery, auth secret, common utils.
 *
 * AGENT_DISCOVERY_URL is hardcoded per spec 04 (REVIEW-01 #2).
 * If the user changes AIFLOW_PORT they edit this one line.
 */

const AGENT_BASE      = 'http://127.0.0.1:8101';
const DISCOVERY_URL   = `${AGENT_BASE}/api/ext/discovery`;
const CALLBACK_URL    = `${AGENT_BASE}/api/ext/callback`;

// discoverAttempts UX thresholds (spec 04 / REVIEW-02 #5)
// 0-4 attempts  → "Connecting..."
// 5+  attempts  → "Agent not running" hint
const MAX_QUIET_ATTEMPTS = 5;

let dynamicConfig    = null;
let discoverAttempts = 0;

// Popup-visible state — 4 distinct statuses
// 'connecting'       : discovery in progress (< 5 attempts)
// 'agent_not_running': discovery failed >= 5 times
// 'token_missing'    : WS connected but no Bearer token yet
// 'connected'        : WS connected + token captured
export const popupState = {
  status:       'connecting',
  agentUrl:     AGENT_BASE,
  attemptCount: 0,
};

export function getPopupState() {
  return { ...popupState, attemptCount: discoverAttempts };
}

// ─── Agent Discovery ────────────────────────────────────────

/**
 * Retry forever until the agent HTTP endpoint responds.
 * Updates popupState so the popup can show meaningful UX.
 */
export async function discoverAgent() {
  while (true) {
    try {
      const resp = await fetch(DISCOVERY_URL, { cache: 'no-store' });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

      // Success — reset counter
      discoverAttempts = 0;
      popupState.status       = 'connecting'; // will flip to 'connected' after WS handshake
      popupState.attemptCount = 0;

      dynamicConfig = await resp.json();
      console.log('[AIFlow] Agent discovered:', dynamicConfig);

      const manifest = chrome.runtime.getManifest();
      if (
        dynamicConfig.min_extension_version &&
        compareVersion(manifest.version, dynamicConfig.min_extension_version) < 0
      ) {
        console.warn('[AIFlow] Extension older than agent expects — please update');
      }

      return dynamicConfig;

    } catch (e) {
      discoverAttempts++;
      popupState.attemptCount = discoverAttempts;

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

// ─── WebSocket Connection ────────────────────────────────────

/**
 * Connect to agent WS. Calls discoverAgent() first if needed.
 * @param {object} state  - shared extension state object
 * @param {function} dispatch - message handler
 */
export async function connectAgent(state, dispatch) {
  if (!dynamicConfig) await discoverAgent();

  const wsUrl = dynamicConfig.ws_url || `ws://127.0.0.1:${dynamicConfig.ws_port || 9223}`;
  state.ws = new WebSocket(wsUrl);

  state.ws.onopen = () => {
    state.connected = true;
    popupState.status = state.flow?.token ? 'connected' : 'token_missing';
    console.log('[AIFlow] WS connected to agent');
  };

  state.ws.onmessage = (e) => {
    try {
      dispatch(JSON.parse(e.data));
    } catch (err) {
      console.error('[AIFlow] WS message parse error:', err);
    }
  };

  state.ws.onclose = () => {
    state.connected = false;
    popupState.status = 'connecting';
    // Re-discover before reconnect — agent may have restarted on a different port
    dynamicConfig = null;
    scheduleReconnect(state, dispatch);
  };

  state.ws.onerror = (e) => {
    console.error('[AIFlow] WS error:', e);
  };
}

function scheduleReconnect(state, dispatch) {
  chrome.alarms.create('reconnect', { delayInMinutes: 0.083 }); // ~5s
  // Store dispatch ref for alarm handler
  state._dispatch = dispatch;
}

// ─── Send helpers ────────────────────────────────────────────

export function sendWs(state, msg) {
  if (state.ws?.readyState === WebSocket.OPEN) {
    state.ws.send(JSON.stringify(msg));
  }
}

export async function postCallback(state, payload) {
  return fetch(CALLBACK_URL, {
    method:  'POST',
    headers: {
      'Content-Type':      'application/json',
      'X-Callback-Secret': state.callbackSecret || '',
    },
    body: JSON.stringify(payload),
  });
}

/**
 * Route a response message to the agent.
 * Responses (msg.id present) go via HTTP callback — immune to WS drops.
 * Falls back to WS on HTTP failure.
 */
export function sendToAgent(state, msg) {
  if (msg.id) {
    postCallback(state, msg).catch(() => {
      sendWs(state, msg);
    });
    return;
  }
  sendWs(state, msg);
}

// ─── Token capture notification ──────────────────────────────

export function onTokenCaptured(state) {
  if (popupState.status === 'token_missing') {
    popupState.status = 'connected';
  }
}

// ─── Utilities ───────────────────────────────────────────────

export function compareVersion(a, b) {
  const pa = a.split('.').map(Number);
  const pb = b.split('.').map(Number);
  for (let i = 0; i < 3; i++) {
    if ((pa[i] || 0) !== (pb[i] || 0)) return (pa[i] || 0) - (pb[i] || 0);
  }
  return 0;
}

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
