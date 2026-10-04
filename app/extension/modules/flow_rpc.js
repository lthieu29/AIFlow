/** Cookie-authenticated Flow RPCs. CSRF and captcha values stay in the page. */
export const FLOW_RPC_IDS = ['YhhmEf', 'eb1hJf', 'maseQ', 'jwpduf', 'as29s', 'HTrJv'];

// Passed directly to chrome.scripting.executeScript; it must be self-contained.
export async function executeFlowRpc(rpcId, request, captchaAction, siteKey, preflightOnly = false) {
  let phase = 'session';
  let requestSent = false;
  try {
    if (window.location.hostname !== 'flow.google.com') return { error: 'FLOW_RPC_DOMAIN_REQUIRED', requestSent, phase };
    const csrf = window.WIZ_global_data?.SNlM0e;
    if (!csrf) return { error: 'FLOW_RPC_SESSION_MISSING: Sign in to Google Flow.', requestSent, phase };
    if (captchaAction) {
      const execute = window.grecaptcha?.enterprise?.execute;
      if (typeof execute !== 'function') return { error: 'FLOW_RPC_CAPTCHA_NOT_READY', requestSent, phase: 'captcha' };
      // Respect Flow's native generation requirement; do not unwrap its captcha guard.
      if (Function.prototype.toString.call(execute).includes('extension_hijack_detected')) {
        return { error: 'FLOW_UI_GENERATION_REQUIRED', requestSent, phase: 'captcha' };
      }
    }
    if (preflightOnly) return { status: 200, data: [], requestSent };
    const payload = JSON.parse(JSON.stringify(request));
    if (captchaAction) {
      phase = 'captcha';
      const token = await window.grecaptcha.enterprise.execute(siteKey, { action: captchaAction });
      const context = rpcId === 'maseQ' ? payload[0] : payload[1];
      if (!Array.isArray(context)) return { error: 'FLOW_RPC_CONTEXT_REQUIRED' };
      context[10] = [token, 1];
    }
    const url = new URL('/_/AiSandboxAngularFrontend/data/batchexecute', window.location.origin);
    url.searchParams.set('rpcids', rpcId);
    url.searchParams.set('source-path', window.location.pathname);
    url.searchParams.set('rt', 'c');
    const body = new URLSearchParams();
    body.set('f.req', JSON.stringify([[[rpcId, JSON.stringify(payload), null, 'generic']]]));
    body.set('at', csrf);
    phase = 'fetch';
    requestSent = true;
    const response = await fetch(url.href, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8', 'X-Same-Domain': '1' },
      body: body.toString(),
    });
    if (!response.ok) return { status: response.status, error: `FLOW_RPC_HTTP_${response.status}`, requestSent };
    phase = 'decode';
    const text = await response.text();
    // Google frames JSON arrays with an XSSI prefix and decimal frame lengths.
    // Scan balanced arrays instead of relying on byte lengths after UTF-8 decoding.
    let start = -1, depth = 0, quoted = false, escaped = false;
    for (let i = 0; i < text.length; i++) {
      const char = text[i];
      if (start < 0) { if (char !== '[') continue; start = i; depth = 1; continue; }
      if (quoted) {
        if (escaped) escaped = false;
        else if (char === '\\') escaped = true;
        else if (char === '"') quoted = false;
      } else if (char === '"') quoted = true;
      else if (char === '[') depth++;
      else if (char === ']' && --depth === 0) {
        const frame = JSON.parse(text.slice(start, i + 1));
        for (const row of frame) {
          if (row?.[0] === 'wrb.fr' && row[1] === rpcId) {
            if (typeof row[2] === 'string') return { status: response.status, data: JSON.parse(row[2]), requestSent };
            if (Number.isInteger(row[5]?.[0])) {
              return { status: response.status, error: `FLOW_RPC_STATUS_${row[5][0]}`, rpcStatus: row[5][0], requestSent, phase };
            }
          }
        }
        start = -1;
      }
    }
    return { status: response.status, error: 'FLOW_RPC_RESPONSE_MISSING', requestSent };
  } catch (error) {
    // Do not return exception text: a browser error may contain credential-bearing URLs.
    const errorType = ['TypeError', 'ReferenceError', 'SyntaxError', 'Error'].includes(error?.name) ? error.name : 'Error';
    return { error: 'FLOW_RPC_REQUEST_FAILED', phase, requestSent, errorType };
  }
}
