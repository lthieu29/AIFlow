/**
 * AIFlow Bridge — cookie_sniffer.js  (Module B)
 *
 * Lifted from Douyin_TikTok_Download_API/chrome-cookie-sniffer/background.js
 * and extended for Bilibili + TikTok.
 *
 * Responsibilities:
 *  - Watch cookie changes via chrome.cookies.onChanged for 3 platforms
 *  - Periodic poll (every 5 min) for all 3 platforms
 *  - Dedupe: only emit when cookie content changes
 *  - Send cookie_captured via WS with platform + cookie string
 *  - Handle read_cookie message from agent
 */

import { sendWs } from './shared.js';

// ─── Platform Config ─────────────────────────────────────────

/**
 * PLATFORM_PATTERNS — URL patterns for chrome.cookies.getAll()
 * Keyed by platform name.
 */
export const PLATFORM_PATTERNS = {
  bilibili: '*.bilibili.com',
  douyin:   '*.douyin.com',
  tiktok:   '*.tiktok.com',
};

/**
 * Full platform config with cookie key hints and validation rules.
 * Lifted from spec 04-extension-spec.md § Module B.
 */
const PLATFORMS = {
  bilibili: {
    name:            'bilibili',
    domains:         ['bilibili.com'],
    cookieDomain:    '.bilibili.com',
    // Critical keys — used for status display in popup
    keys:            ['SESSDATA', 'bili_jct', 'DedeUserID', 'buvid3', 'buvid4'],
    minRequiredKeys: ['SESSDATA'],
    urlPatterns:     ['https://www.bilibili.com/*', 'https://api.bilibili.com/*'],
  },
  douyin: {
    name:            'douyin',
    domains:         ['douyin.com'],
    cookieDomain:    '.douyin.com',
    keys:            ['msToken', 'ttwid', 'sessionid', 'sessionid_ss', 'odin_tt', 'passport_csrf_token'],
    minRequiredKeys: ['ttwid'],
    urlPatterns:     ['https://*.douyin.com/*'],
  },
  tiktok: {
    name:            'tiktok',
    domains:         ['tiktok.com'],
    cookieDomain:    '.tiktok.com',
    keys:            ['tt_chain_token', 'msToken', 'sessionid', 'sid_tt'],
    minRequiredKeys: ['msToken'],
    urlPatterns:     ['https://*.tiktok.com/*'],
  },
};

// ─── CookieSniffer ───────────────────────────────────────────

/**
 * CookieSniffer — captures and formats cookies for 3 platforms.
 *
 * Usage:
 *   const sniffer = new CookieSniffer();
 *   const header = await sniffer.getCookieHeader('bilibili');
 *   const all    = await sniffer.getAllPlatformCookies();
 */
export class CookieSniffer {
  /**
   * Get all cookies for a platform using chrome.cookies.getAll().
   * @param {string} platform - 'bilibili' | 'douyin' | 'tiktok'
   * @returns {Promise<chrome.cookies.Cookie[]>}
   */
  async sniffCookies(platform) {
    const config = PLATFORMS[platform];
    if (!config) {
      console.warn(`[CookieSniffer] Unknown platform: ${platform}`);
      return [];
    }
    return new Promise((resolve) => {
      chrome.cookies.getAll({ domain: config.cookieDomain }, (cookies) => {
        if (chrome.runtime.lastError) {
          console.warn(`[CookieSniffer] getAll error for ${platform}:`, chrome.runtime.lastError.message);
          resolve([]);
          return;
        }
        resolve(cookies || []);
      });
    });
  }

  /**
   * Format a cookie array as a "key=value; key2=value2" string.
   * @param {chrome.cookies.Cookie[]} cookies
   * @returns {string}
   */
  formatCookies(cookies) {
    if (!cookies || !cookies.length) return '';
    return cookies.map((c) => `${c.name}=${c.value}`).join('; ');
  }

  /**
   * Get formatted cookie header string for a platform.
   * @param {string} platform - 'bilibili' | 'douyin' | 'tiktok'
   * @returns {Promise<string>} Cookie header string, e.g. "SESSDATA=abc; bili_jct=xyz"
   */
  async getCookieHeader(platform) {
    const cookies = await this.sniffCookies(platform);
    return this.formatCookies(cookies);
  }

  /**
   * Get cookies for all 3 platforms.
   * @returns {Promise<{bilibili: string, douyin: string, tiktok: string}>}
   */
  async getAllPlatformCookies() {
    const [bilibili, douyin, tiktok] = await Promise.all([
      this.getCookieHeader('bilibili'),
      this.getCookieHeader('douyin'),
      this.getCookieHeader('tiktok'),
    ]);
    return { bilibili, douyin, tiktok };
  }
}

// ─── Module-level sniffer instance ──────────────────────────

const sniffer = new CookieSniffer();

// ─── Cookie change deduplication ────────────────────────────

// In-memory cache of last emitted cookie string per platform
// (not persisted — per spec: cookies short-lived in extension)
const _lastEmitted = {
  bilibili: null,
  douyin:   null,
  tiktok:   null,
};

/**
 * Check if cookie content has changed since last emit.
 * @param {string} platform
 * @param {string} cookieStr
 * @returns {boolean}
 */
function hasChanged(platform, cookieStr) {
  return _lastEmitted[platform] !== cookieStr;
}

// ─── Emit helper ─────────────────────────────────────────────

/**
 * Emit cookie_captured to agent if content changed.
 * @param {object} state - shared extension state
 * @param {string} platform
 * @param {string} cookieStr
 * @param {string} source - 'poll' | 'onChanged'
 */
function emitIfChanged(state, platform, cookieStr, source = 'poll') {
  if (!cookieStr) return;
  if (!hasChanged(platform, cookieStr)) return;

  _lastEmitted[platform] = cookieStr;

  // Update shared state
  if (state.cookies) {
    state.cookies[platform] = {
      value:       cookieStr,
      capturedAt:  Date.now(),
      source,
    };
  }

  const config = PLATFORMS[platform];
  const presentKeys = config.keys.filter((k) => cookieStr.includes(`${k}=`));
  const missingRequired = config.minRequiredKeys.filter((k) => !cookieStr.includes(`${k}=`));
  const partial = missingRequired.length > 0;

  console.log(
    `[CookieSniffer] ${platform} cookie captured (${source}) — ` +
    `${presentKeys.length}/${config.keys.length} keys, partial=${partial}`
  );

  sendWs(state, {
    type:     'cookie_captured',
    platform,
    cookie:   cookieStr,
    partial,
    keys:     presentKeys,
    source,
  });
}

// ─── Module init ─────────────────────────────────────────────

/**
 * Initialize Module B.
 * - Registers chrome.cookies.onChanged listener for all 3 platforms
 * - Schedules periodic poll alarm
 * @param {object} state - shared extension state
 */
export function initCookieSniffer(state) {
  // Watch cookie changes for all 3 platforms
  chrome.cookies.onChanged.addListener(async (changeInfo) => {
    if (changeInfo.removed) return;

    const { cookie } = changeInfo;
    const platform = getPlatformFromDomain(cookie.domain);
    if (!platform) return;

    // Re-fetch full cookie string for the platform (not just the changed key)
    const cookieStr = await sniffer.getCookieHeader(platform);
    emitIfChanged(state, platform, cookieStr, 'onChanged');
  });

  // Periodic poll every 5 minutes
  chrome.alarms.create('cookiePoll', { periodInMinutes: 5 });
  chrome.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name === 'cookiePoll') {
      pollAllPlatforms(state);
    }
  });

  // Initial poll on startup
  pollAllPlatforms(state);

  console.log('[CookieSniffer] Module B initialized — watching Bilibili, Douyin, TikTok');
}

/**
 * Poll all 3 platforms and emit if changed.
 * @param {object} state
 */
async function pollAllPlatforms(state) {
  for (const platform of Object.keys(PLATFORMS)) {
    try {
      const cookieStr = await sniffer.getCookieHeader(platform);
      emitIfChanged(state, platform, cookieStr, 'poll');
    } catch (e) {
      console.warn(`[CookieSniffer] Poll failed for ${platform}:`, e?.message || e);
    }
  }
}

/**
 * Determine platform from a cookie domain string.
 * @param {string} domain - e.g. ".bilibili.com", ".douyin.com"
 * @returns {string|null} platform name or null
 */
function getPlatformFromDomain(domain) {
  if (!domain) return null;
  const d = domain.replace(/^\./, '');
  for (const [platform, config] of Object.entries(PLATFORMS)) {
    if (config.domains.some((pd) => d === pd || d.endsWith(`.${pd}`))) {
      return platform;
    }
  }
  return null;
}

// ─── Message handler ─────────────────────────────────────────

/**
 * Handle messages from agent that belong to Module B.
 * Supported message types:
 *   - read_cookie  { platform: 'bilibili'|'douyin'|'tiktok'|'all' }
 *   - get_cookies  { platform: ... }  (alias)
 *
 * @param {object} msg
 * @param {object} state
 */
export async function handleCookieMessage(msg, state) {
  const type     = msg.type || msg.method;
  const platform = msg.platform || msg.params?.platform || 'all';

  if (type === 'read_cookie' || type === 'get_cookies') {
    if (platform === 'all') {
      const all = await sniffer.getAllPlatformCookies();
      sendWs(state, {
        id:      msg.id,
        type:    'cookie_result',
        cookies: all,
      });
    } else {
      const cookieStr = await sniffer.getCookieHeader(platform);
      sendWs(state, {
        id:      msg.id,
        type:    'cookie_result',
        platform,
        cookie:  cookieStr,
      });
    }
    return;
  }

  console.warn('[CookieSniffer] Unknown message type:', type);
}

// ─── Popup state helper ──────────────────────────────────────

/**
 * Get cookie status for popup display.
 * @param {object} state - shared extension state
 * @returns {object} status per platform
 */
export function getCookieStatus(state) {
  const result = {};
  for (const platform of Object.keys(PLATFORMS)) {
    const entry = state.cookies?.[platform];
    if (!entry || !entry.value) {
      result[platform] = { status: 'not_captured' };
      continue;
    }
    const config = PLATFORMS[platform];
    const presentKeys    = config.keys.filter((k) => entry.value.includes(`${k}=`));
    const missingRequired = config.minRequiredKeys.filter((k) => !entry.value.includes(`${k}=`));
    result[platform] = {
      status:      missingRequired.length > 0 ? 'partial' : 'valid',
      capturedAt:  entry.capturedAt,
      presentKeys,
      missingRequired,
    };
  }
  return result;
}
