/**
 * AIFlow Bridge — flow_proxy.js  (Module A)
 *
 * Lifted from flowboard/extension/background.js and refactored into a module.
 *
 * Responsibilities:
 *  - Listen webRequest.onBeforeSendHeaders → catch Bearer ya29.* from Flow
 *  - Send token_captured to agent via WS
 *  - Handle api_request from agent: fetch() in user session, POST response via callback
 *  - Forward get_captcha → content.js → injected.js (MAIN world) → grecaptcha
 *  - Periodic fetchAndPushUserInfo for account/plan/credits
 */

import { sendToAgent, sendWs, onTokenCaptured } from './shared.js';

const FLOW_URL  = 'https://labs.google/fx/tools/flow';
const FLOW_URLS = ['https://labs.google/fx/tools/flow*', 'https://labs.google/fx/*/tools/flow*'];

// ─── URL Classifier ──────────────────────────────────────────

export function classifyUrl(url) {
  if (url.includes('batchGenerateImages'))     return 'GEN_IMG';
  if (url.includes('batchAsyncGenerateVideo')) return 'GEN_VID';
  if (url.includes('batchCheckAsync'))         return 'POLL';
  return 'API';
}

// ─── Request Log (last 50 entries) ──────────────────────────

let requestLog = [];

function addRequestLog(entry) {
  requestLog.unshift(entry);
  if (requestLog.length > 50) requestLog.pop();
  broadcastRequestLog();
}

function updateRequestLog(id, updates) {
  const entry = requestLog.find((e) => e.id === id);
  if (entry) Object.assign(entry, updates);
  broadcastRequestLog();
}

function broadcastRequestLog() {
  chrome.runtime.sendMessage({ type: 'REQUEST_LOG_UPDATE', log: requestLog }).catch(() => {});
}

export function getRequestLog() {
  return requestLog;
}

// ─── Module init ─────────────────────────────────────────────

/**
 * @param {object} state - shared extension state
 */
export function initFlowProxy(state) {
  // Token capture via webRequest
  chrome.webRequest.onBeforeSendHeaders.addListener(
    (details) => {
      if (!details?.requestHeaders?.length) return;
      const authHeader = details.requestHeaders.find(
        (h) => h.name?.toLowerCase() === 'authorization',
      );
      const value = authHeader?.value || '';
      if (!value.startsWith('Bearer ya29.')) return;

      const token = value.replace(/^Bearer\s+/i, '').trim();
      if (!token) return;

      const tokenChanged = state.flow.token !== token;
      state.flow.token       = token;
      state.flow.capturedAt  = Date.now();
      chrome.storage.local.set({ flowKey: token, flowCapturedAt: state.flow.capturedAt });

      if (tokenChanged) {
        console.log('[AIFlow] Bearer token captured');
        onTokenCaptured(state);
        sendWs(state, { type: 'token_captured', flowKey: token });
        fetchAndPushUserInfo(state, token);
      }
    },
    { urls: ['https://aisandbox-pa.googleapis.com/*', 'https://labs.google/*'] },
    ['requestHeaders', 'extraHeaders'],
  );
}

// ─── User Info ───────────────────────────────────────────────

let cachedUserInfo = null;

export async function fetchAndPushUserInfo(state, token) {
  try {
    const resp = await fetch(
      'https://www.googleapis.com/oauth2/v2/userinfo',
      { headers: { authorization: `Bearer ${token}` } },
    );
    if (!resp.ok) {
      console.warn('[AIFlow] userinfo fetch returned', resp.status);
      return;
    }
    const info = await resp.json();
    // In-memory only — DO NOT persist to chrome.storage.local (PII)
    cachedUserInfo = info;
    console.log('[AIFlow] userinfo captured for', info?.email || '<no email>');
    sendWs(state, { type: 'user_info', userInfo: info });
  } catch (e) {
    console.warn('[AIFlow] userinfo fetch failed:', e?.message || e);
  }
}

export function getCachedUserInfo() {
  return cachedUserInfo;
}

export function clearCachedUserInfo() {
  cachedUserInfo = null;
}

// ─── Message handler ─────────────────────────────────────────

/**
 * Handle messages from agent that belong to Module A.
 * @param {object} msg
 * @param {object} state
 */
export async function handleFlowMessage(msg, state) {
  if (msg.method === 'api_request' || msg.type === 'api_request') {
    return handleApiRequest(msg, state);
  }
  if (msg.method === 'trpc_request' || msg.type === 'trpc_request') {
    return handleTrpcRequest(msg, state);
  }
  if (msg.type === 'please_resend_userinfo') {
    if (cachedUserInfo) {
      sendWs(state, { type: 'user_info', userInfo: cachedUserInfo });
    } else if (state.flow?.token) {
      fetchAndPushUserInfo(state, state.flow.token);
    }
    return;
  }
  if (msg.type === 'logout') {
    console.log('[AIFlow] logout requested by agent');
    cachedUserInfo = null;
    state.flow.token = null;
    return;
  }
}

// ─── API Request Proxy ───────────────────────────────────────

async function handleApiRequest(msg, state) {
  const { id, params } = msg;
  const { url, method, headers, body, captchaAction } = params || {};

  if (!url || !url.startsWith('https://aisandbox-pa.googleapis.com/')) {
    sendToAgent(state, { id, status: 400, error: 'INVALID_URL' });
    return;
  }

  const hasCaptcha = !!captchaAction;
  if (hasCaptcha) state.metrics.requestCount++;

  addRequestLog({
    id,
    type:   classifyUrl(url),
    time:   new Date().toISOString(),
    status: 'processing',
    url,
  });

  try {
    if (!state.flow.token) {
      sendToAgent(state, { id, status: 503, error: 'NO_FLOW_KEY' });
      if (hasCaptcha) { state.metrics.failedCount++; state.metrics.lastError = 'NO_FLOW_KEY'; }
      chrome.storage.local.set({ metrics: state.metrics });
      updateRequestLog(id, { status: 'failed', error: 'NO_FLOW_KEY' });
      return;
    }

    // Step 1: Solve captcha if needed
    let captchaToken = null;
    if (captchaAction) {
      const captchaResult = await solveCaptcha(id, captchaAction);
      captchaToken = captchaResult?.token || null;
      if (!captchaToken) {
        const err = captchaResult?.error || 'CAPTCHA_FAILED';
        console.error(`[AIFlow] Captcha failed for ${captchaAction}: ${err}`);
        sendToAgent(state, { id, status: 403, error: `CAPTCHA_FAILED: ${err}` });
        if (hasCaptcha) { state.metrics.failedCount++; state.metrics.lastError = `CAPTCHA_FAILED: ${err}`; }
        chrome.storage.local.set({ metrics: state.metrics });
        updateRequestLog(id, { status: 'failed', error: `CAPTCHA_FAILED: ${err}` });
        return;
      }
    }

    // Step 2: Inject captcha token into body clone if present
    let finalBody = body;
    if (captchaToken && finalBody) {
      finalBody = JSON.parse(JSON.stringify(finalBody));
      if (finalBody.clientContext?.recaptchaContext) {
        finalBody.clientContext.recaptchaContext.token = captchaToken;
      }
      if (finalBody.requests && Array.isArray(finalBody.requests)) {
        for (const req of finalBody.requests) {
          if (req.clientContext?.recaptchaContext) {
            req.clientContext.recaptchaContext.token = captchaToken;
          }
        }
      }
    }

    const fetchHeaders = { ...(headers || {}), authorization: `Bearer ${state.flow.token}` };

    const response = await fetch(url, {
      method:      method || 'POST',
      headers:     fetchHeaders,
      credentials: 'include',
      body:        method === 'GET' ? undefined : JSON.stringify(finalBody),
    });

    const responseText = await response.text();
    let responseData;
    try {
      responseData = JSON.parse(responseText);
    } catch {
      responseData = responseText;
    }

    sendToAgent(state, { id, status: response.status, data: responseData });

    if (response.ok) {
      if (hasCaptcha) { state.metrics.successCount++; state.metrics.lastError = null; }
      updateRequestLog(id, { status: 'success', httpStatus: response.status });
    } else {
      if (hasCaptcha) { state.metrics.failedCount++; state.metrics.lastError = `API_${response.status}`; }
      updateRequestLog(id, { status: 'failed', httpStatus: response.status, error: `API_${response.status}` });
    }
  } catch (e) {
    sendToAgent(state, { id, status: 500, error: e.message || 'API_REQUEST_FAILED' });
    if (hasCaptcha) { state.metrics.failedCount++; state.metrics.lastError = e.message || 'API_REQUEST_FAILED'; }
    updateRequestLog(id, { status: 'failed', error: e.message || 'API_REQUEST_FAILED' });
  }

  chrome.storage.local.set({ metrics: state.metrics });
}

// ─── TRPC Request Proxy ──────────────────────────────────────

async function handleTrpcRequest(msg, state) {
  const { id, params } = msg;
  const { url, method = 'POST', headers = {}, body } = params || {};

  if (!url || !url.startsWith('https://labs.google/fx/api/trpc/')) {
    sendToAgent(state, { id, error: 'INVALID_TRPC_URL' });
    return;
  }

  const fetchHeaders = { 'Content-Type': 'application/json', ...headers };
  if (state.flow?.token) {
    fetchHeaders['authorization'] = `Bearer ${state.flow.token}`;
  }

  try {
    const resp = await fetch(url, {
      method,
      headers:     fetchHeaders,
      body:        body ? JSON.stringify(body) : undefined,
      credentials: 'include',
    });
    const data = await resp.json();
    sendToAgent(state, { id, status: resp.status, data });
  } catch (e) {
    console.error('[AIFlow] tRPC request failed:', e);
    sendToAgent(state, { id, error: e.message || 'TRPC_FETCH_FAILED' });
  }
}

// ─── reCAPTCHA Solving ───────────────────────────────────────

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let _openingFlowTab = false;

async function openFlowTabResilient(active = false) {
  try {
    return await chrome.tabs.create({ url: FLOW_URL, active });
  } catch (e) {
    const msg = e?.message || '';
    if (!msg.includes('No current window')) throw e;
    console.log('[AIFlow] No Chrome window — spawning a fresh one for Flow');
    const win = await chrome.windows.create({
      url:     FLOW_URL,
      focused: false,
      state:   'minimized',
    });
    return win.tabs?.[0] ?? null;
  }
}

async function reviveTabIfNeeded(tab) {
  if (!tab?.discarded) return tab;
  try {
    await chrome.tabs.reload(tab.id);
    await sleep(2500);
    return await chrome.tabs.get(tab.id);
  } catch {
    return null;
  }
}

async function requestCaptchaFromTab(tabId, requestId, pageAction) {
  try {
    return await chrome.tabs.sendMessage(tabId, {
      type: 'GET_CAPTCHA',
      requestId,
      pageAction,
    });
  } catch (error) {
    const msg = error?.message || '';
    const shouldInject =
      msg.includes('Receiving end does not exist') ||
      msg.includes('Could not establish connection');
    if (!shouldInject) throw error;

    await chrome.scripting.executeScript({ target: { tabId }, files: ['content.js'] });
    await sleep(200);
    return await chrome.tabs.sendMessage(tabId, { type: 'GET_CAPTCHA', requestId, pageAction });
  }
}

export async function solveCaptcha(requestId, captchaAction) {
  const tabs = await chrome.tabs.query({ url: FLOW_URLS });

  if (!tabs.length) {
    try {
      await openFlowTabResilient(false);
      await sleep(3000);
    } catch (e) {
      return { error: e.message || 'NO_FLOW_TAB' };
    }
  }

  const candidates = await chrome.tabs.query({ url: FLOW_URLS });
  const errors = [];
  for (const tab of candidates) {
    const live = await reviveTabIfNeeded(tab);
    if (!live) continue;
    try {
      const resp = await Promise.race([
        requestCaptchaFromTab(live.id, requestId, captchaAction),
        new Promise((_, rej) => setTimeout(() => rej(new Error('CAPTCHA_TIMEOUT')), 30000)),
      ]);
      return resp;
    } catch (e) {
      const msg = e?.message || '';
      errors.push(msg);
      if (
        msg.includes('No current window') ||
        msg.includes('No tab with id') ||
        msg.includes('Receiving end does not exist')
      ) {
        continue;
      }
      return { error: msg };
    }
  }

  // Last-ditch: spawn fresh Flow tab
  try {
    await openFlowTabResilient(false);
    await sleep(3000);
    const fresh  = await chrome.tabs.query({ url: FLOW_URLS });
    const target = fresh.find((t) => !t.discarded) || fresh[0];
    if (!target) return { error: 'NO_FLOW_TAB' };
    const resp = await Promise.race([
      requestCaptchaFromTab(target.id, requestId, captchaAction),
      new Promise((_, rej) => setTimeout(() => rej(new Error('CAPTCHA_TIMEOUT')), 30000)),
    ]);
    return resp;
  } catch (e) {
    return { error: e.message || (errors[0] ?? 'NO_FLOW_TAB') };
  }
}

// ─── Popup helpers ───────────────────────────────────────────

export function openFlowTab() {
  return chrome.tabs.query({ url: FLOW_URLS }).then(async (tabs) => {
    if (tabs.length) {
      await chrome.tabs.update(tabs[0].id, { active: true });
      return { ok: true, tabId: tabs[0].id };
    }
    const tab = await openFlowTabResilient(true);
    return { ok: true, tabId: tab?.id };
  });
}

export async function captureTokenFromFlowTab() {
  const tabs = await chrome.tabs.query({ url: FLOW_URLS });
  if (!tabs.length) {
    if (_openingFlowTab) return;
    _openingFlowTab = true;
    try {
      await openFlowTabResilient(false);
    } catch (e) {
      console.error('[AIFlow] Failed to open Flow tab:', e);
    } finally {
      _openingFlowTab = false;
    }
    return;
  }
  try {
    await chrome.scripting.executeScript({
      target: { tabId: tabs[0].id },
      func:   () => fetch('/fx/tools/flow', { credentials: 'include' }),
    });
    console.log('[AIFlow] Token refresh triggered on Flow tab');
  } catch (e) {
    console.error('[AIFlow] Token refresh failed:', e);
  }
}
