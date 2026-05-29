/**
 * AIFlow Bridge — popup.js
 *
 * Polls background state every 1s via chrome.runtime.sendMessage({type:'GET_STATE'}).
 * Renders 4 distinct statuses per spec 04 / REVIEW-02 #5:
 *
 *   status='connecting'        (discoverAttempts < 5)  → 🟡 Connecting...
 *   status='agent_not_running' (discoverAttempts >= 5) → 🔴 Agent not running
 *   status='token_missing'     (WS connected, no tok)  → 🟡 Connected — token missing
 *   status='connected'         (full)                  → 🟢 Connected
 */

function formatTokenAge(ms) {
  if (ms === null || ms === undefined) return 'none';
  const s = Math.floor(ms / 1000);
  if (s < 60)   return `captured ${s}s ago`;
  if (s < 3600) return `captured ${Math.floor(s / 60)}m ago`;
  return `captured ${Math.floor(s / 3600)}h ago`;
}

function render(state) {
  if (!state) return;

  // Set extension version
  const manifest = chrome.runtime.getManifest();
  document.getElementById('ext-version').textContent = `v${manifest.version}`;

  // ── Agent status ──────────────────────────────────────────
  const statusEl = document.getElementById('agent-status');
  const hintEl   = document.getElementById('hint-row');

  switch (state.status) {
    case 'connected':
      statusEl.className   = 'section-value status-connected';
      statusEl.textContent = '🟢 Connected';
      hintEl.style.display = 'none';
      break;

    case 'token_missing':
      statusEl.className   = 'section-value status-token-missing';
      statusEl.textContent = '🟡 Connected — token missing';
      hintEl.style.display = 'block';
      hintEl.textContent   = 'Open: labs.google/fx/tools/flow';
      break;

    case 'agent_not_running':
      statusEl.className   = 'section-value status-agent-not-running';
      statusEl.textContent = '🔴 Agent not running';
      hintEl.style.display = 'block';
      hintEl.textContent   = 'Run: python -m server.main\n(default port 8101)';
      break;

    case 'connecting':
    default:
      statusEl.className   = 'section-value status-connecting';
      statusEl.textContent = `○ Connecting... (${state.attemptCount || 0})`;
      hintEl.style.display = 'none';
      break;
  }

  // ── Token ─────────────────────────────────────────────────
  document.getElementById('token-row').textContent =
    state.flowKeyPresent ? formatTokenAge(state.tokenAge) : 'none';

  // ── Account ───────────────────────────────────────────────
  const accountSection = document.getElementById('account-section');
  const accountRow     = document.getElementById('account-row');
  if (state.userInfo?.email) {
    accountSection.style.display = 'flex';
    accountRow.textContent = state.userInfo.email;
  } else {
    accountSection.style.display = 'none';
  }

  // ── Stats ─────────────────────────────────────────────────
  const m = state.metrics || {};
  document.getElementById('stats-row').textContent =
    `${m.requestCount || 0} · ✓ ${m.successCount || 0} · ✗ ${m.failedCount || 0}`;

  // ── Error ─────────────────────────────────────────────────
  const errSection = document.getElementById('error-section');
  const errRow     = document.getElementById('error-row');
  if (m.lastError) {
    errSection.style.display = 'flex';
    errRow.textContent = m.lastError;
  } else {
    errSection.style.display = 'none';
  }
}

function fetchState() {
  chrome.runtime.sendMessage({ type: 'GET_STATE' }, (reply) => {
    if (chrome.runtime.lastError) return;
    render(reply);
  });
}

// Initial fetch + poll every 1s
fetchState();
setInterval(fetchState, 1000);

// Re-render on push from background
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === 'STATUS_PUSH') fetchState();
});

// Buttons
document.getElementById('btn-flow-tab').addEventListener('click', () => {
  chrome.runtime.sendMessage({ type: 'OPEN_FLOW_TAB' });
});

document.getElementById('btn-refresh').addEventListener('click', () => {
  chrome.runtime.sendMessage({ type: 'REFRESH_TOKEN' });
});
