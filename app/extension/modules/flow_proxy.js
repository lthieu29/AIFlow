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
import { FLOW_RPC_IDS, executeFlowRpc } from './flow_rpc.js';
import { executeFlowUi } from './flow_ui.js';

const FLOW_URL  = 'https://flow.google.com/';
const FLOW_URLS = ['https://flow.google.com/*', 'https://labs.google/fx/tools/flow*', 'https://labs.google/fx/*/tools/flow*'];

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
    { urls: ['https://aisandbox-pa.googleapis.com/*', 'https://labs.google/*', 'https://flow.google.com/*'] },
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
  if (msg.method === 'flow_ui_request' || msg.type === 'flow_ui_request') {
    const { projectId, prompt, aspect, preflightOnly, reference, allow_silent_video = false, reference_mode = 'ingredients' } = msg.params || {};
    if (typeof allow_silent_video !== 'boolean' || !['ingredients', 'first_frame'].includes(reference_mode)
        || (reference_mode === 'first_frame' && !reference)) {
      sendToAgent(state, { id: msg.id, error: 'INVALID_FLOW_UI_REQUEST', requestSent: false });
      return;
    }
    const tabs = await chrome.tabs.query({ url: ['https://flow.google.com/*'] });
    const tab = tabs.find(candidate => flowProjectIdFromUrl(candidate.url) === projectId);
    if (!tab) {
      sendToAgent(state, { id: msg.id, error: 'FLOW_PROJECT_TAB_REQUIRED', requestSent: false });
      return;
    }
    try {
      const results = await chrome.scripting.executeScript({
        target: { tabId: tab.id }, world: 'MAIN', func: executeFlowUi,
        args: [projectId, prompt || '', aspect || '16:9', preflightOnly === true, reference || null, allow_silent_video, reference_mode],
      });
      sendToAgent(state, { id: msg.id, ...(results?.[0]?.result || { error: 'FLOW_UI_NO_RESULT' }) });
    } catch {
      sendToAgent(state, { id: msg.id, error: 'FLOW_UI_TAB_UNAVAILABLE' });
    }
    return;
  }
  if (msg.method === 'open_flow_project' || msg.type === 'open_flow_project') {
    const result = await openFlowProject(msg.params?.url);
    sendToAgent(state, { id: msg.id, ...result });
    return;
  }
  if (msg.method === 'flow_rpc_request' || msg.type === 'flow_rpc_request') {
    const { rpcId, request, projectId, captchaAction, preflightOnly } = msg.params || {};
    if (!FLOW_RPC_IDS.includes(rpcId) || !Array.isArray(request)) {
      sendToAgent(state, { id: msg.id, status: 400, error: 'INVALID_FLOW_RPC' });
      return;
    }
    const tabs = await chrome.tabs.query({ url: ['https://flow.google.com/*'] });
    const tab = tabs.find((candidate) => flowProjectIdFromUrl(candidate.url) === projectId);
    if (!tab) {
      sendToAgent(state, { id: msg.id, status: 404, error: 'FLOW_PROJECT_TAB_REQUIRED' });
      return;
    }
    try {
      const results = await chrome.scripting.executeScript({
        target: { tabId: tab.id }, world: 'MAIN', func: executeFlowRpc,
        args: [rpcId, request, captchaAction || null, '6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV', preflightOnly === true],
      });
      const result = results?.[0]?.result || { error: 'FLOW_RPC_NO_RESULT' };
      if (!result.error && result.status === 200) {
        state.flow.rpcReady = true;
        onTokenCaptured(state);
      }
      sendToAgent(state, { id: msg.id, ...result });
    } catch {
      sendToAgent(state, { id: msg.id, error: 'FLOW_RPC_TAB_UNAVAILABLE' });
    }
    return;
  }
  if (msg.method === 'get_flow_project' || msg.type === 'get_flow_project') {
    const tabs = await chrome.tabs.query({ url: FLOW_URLS });
    tabs.sort((a, b) => Number(!!b.active) - Number(!!a.active) || (b.lastAccessed || 0) - (a.lastAccessed || 0));
    const projectId = tabs.map((tab) => flowProjectIdFromUrl(tab.url)).find(Boolean);
    sendToAgent(state, projectId
      ? { id: msg.id, status: 200, data: { projectId } }
      : { id: msg.id, status: 404, error: 'FLOW_PROJECT_REQUIRED: Open a Google Flow project in Chrome.' });
    return;
  }
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

export function flowProjectIdFromUrl(value) {
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:') return null;
    const match = url.hostname === 'flow.google.com'
      ? url.pathname.match(/^\/project\/([^/]+)(?:\/|$)/)
      : url.hostname === 'labs.google'
        ? url.pathname.match(/^\/fx\/(?:[^/]+\/)?tools\/flow\/project\/([^/]+)(?:\/|$)/)
        : null;
    const id = match?.[1];
    return id && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id) ? id : null;
  } catch {
    return null;
  }
}

export async function openFlowProject(value) {
  let url, projectId;
  try {
    url = new URL(value);
    projectId = flowProjectIdFromUrl(value)?.toLowerCase();
    if (!projectId || url.hostname !== 'flow.google.com' || url.username || url.password
        || url.port || url.search || url.hash || !/^\/project\/[0-9a-f-]+\/?$/i.test(url.pathname)) {
      return { status: 400, error: 'INVALID_FLOW_PROJECT_URL' };
    }
  } catch {
    return { status: 400, error: 'INVALID_FLOW_PROJECT_URL' };
  }
  const targetUrl = `https://flow.google.com/project/${projectId}`;
  try {
    const tabs = await chrome.tabs.query({ url: FLOW_URLS });
    const existing = tabs.find(tab => flowProjectIdFromUrl(tab.url)?.toLowerCase() === projectId);
    const landing = tabs.find(tab => {
      try {
        const current = new URL(tab.url);
        return (current.hostname === 'flow.google.com' && current.pathname === '/')
          || (current.hostname === 'labs.google' && /^\/fx\/(?:[a-z]{2}(?:-[A-Za-z]{2})?\/)?tools\/flow\/?$/.test(current.pathname));
      } catch { return false; }
    });
    const reusable = existing || landing;
    const tab = reusable
      ? await chrome.tabs.update(reusable.id, { active: true, ...(reusable.url === targetUrl && !reusable.discarded ? {} : { url: targetUrl }) })
      : await openFlowTabResilient(true, targetUrl);
    if (!tab?.id) return { status: 503, error: 'FLOW_PROJECT_TAB_UNAVAILABLE' };
    for (let attempt = 0; attempt < 80; attempt++) {
      const current = await chrome.tabs.get(tab.id);
      if (current.status === 'complete' && flowProjectIdFromUrl(current.url)?.toLowerCase() === projectId) {
        return { status: 200, data: { projectId } };
      }
      await sleep(250);
    }
    return { status: 504, error: 'FLOW_PROJECT_OPEN_TIMEOUT' };
  } catch {
    return { status: 503, error: 'FLOW_PROJECT_TAB_UNAVAILABLE' };
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

async function openFlowTabResilient(active = false, url = FLOW_URL) {
  try {
    return await chrome.tabs.create({ url, active });
  } catch (e) {
    const msg = e?.message || '';
    if (!msg.includes('No current window')) throw e;
    console.log('[AIFlow] No Chrome window — spawning a fresh one for Flow');
    const win = await chrome.windows.create({
      url,
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
      if (resp?.token) return resp;
      errors.push(resp?.error || 'CAPTCHA_FAILED');
    } catch (e) {
      const msg = e?.message || '';
      errors.push(msg);
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

export async function captureTokenFromFlowTab(state) {
  const capturedAtBefore = state?.flow?.capturedAt;
  const tabs = await chrome.tabs.query({ url: FLOW_URLS });
  if (!tabs.length) {
    if (_openingFlowTab) return { ok: false, error: 'FLOW_TAB_OPENING' };
    _openingFlowTab = true;
    try {
      await openFlowTabResilient(false);
    } catch (e) {
      console.error('[AIFlow] Failed to open Flow tab:', e);
    } finally {
      _openingFlowTab = false;
    }
    return { ok: false, error: 'FLOW_TOKEN_MISSING: Open Flow and use a session supported by the API bridge.' };
  }
  try {
    await chrome.scripting.executeScript({
      target: { tabId: tabs[0].id },
      func:   () => fetch(window.location.href, { credentials: 'include' }),
    });
    if (state?.flow?.token && state.flow.capturedAt !== capturedAtBefore) return { ok: true };
    return { ok: false, error: 'FLOW_TOKEN_MISSING: This Flow session has not supplied an API token to the bridge.' };
  } catch (e) {
    console.error('[AIFlow] Token refresh failed:', e);
    return { ok: false, error: e.message || 'FLOW_TOKEN_REFRESH_FAILED' };
  }
}

export async function refreshFlowSession(state) {
  const tabs = await chrome.tabs.query({ url: ['https://flow.google.com/*'] });
  const tab = tabs.find((candidate) => flowProjectIdFromUrl(candidate.url));
  if (!tab) return captureTokenFromFlowTab(state);
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id }, world: 'MAIN', func: executeFlowRpc,
      args: ['HTrJv', [], null, '6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV'],
    });
    const result = results?.[0]?.result;
    if (result?.status === 200 && !result.error) {
      state.flow.rpcReady = true;
      onTokenCaptured(state);
      return { ok: true };
    }
    state.flow.rpcReady = false;
    onTokenCaptured(state);
    return { ok: false, error: result?.error || 'FLOW_RPC_SESSION_UNAVAILABLE' };
  } catch {
    state.flow.rpcReady = false;
    onTokenCaptured(state);
    return { ok: false, error: 'FLOW_RPC_TAB_UNAVAILABLE' };
  }
}
