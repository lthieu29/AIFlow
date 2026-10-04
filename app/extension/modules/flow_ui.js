/** Normal Flow composer controls; observe only the resulting generation response. */
// Self-contained because Chrome serializes this function into the page's MAIN world.
export async function executeFlowUi(projectId, prompt, aspect = '16:9', preflightOnly = false, reference = null, allowSilentVideo = false, referenceMode = 'ingredients') {
  let requestSent = false;
  let cleanup = () => {};
  let locked = false;
  const failure = (error, uiStage) => ({ error, requestSent, phase: 'session', ...(uiStage ? { uiStage } : {}) });
  try {
    if (location.hostname !== 'flow.google.com' || location.pathname !== `/project/${projectId}`) return failure('FLOW_PROJECT_TAB_REQUIRED');
    const visible = (el) => !!el && el.getClientRects().length > 0;
    const find = (selector) => [...document.querySelectorAll(selector)].find(visible);
    const pause = () => new Promise(resolve => setTimeout(resolve, 100));
    const waitFor = async (lookup, timeout = 4000) => {
      const deadline = Date.now() + timeout;
      do { const value = lookup(); if (value) return value; await pause(); } while (Date.now() < deadline);
      return null;
    };
    // Chrome tab completion can precede Angular's composer render after navigation.
    if (preflightOnly) await waitFor(() => find('flow-rich-text-editor.prompt-input .ProseMirror[contenteditable="true"]')
      && find('button.generate-icon-button[aria-label="Bắt đầu tạo"]') && find('button.settings-trigger-button'), 6500);
    let editor = find('flow-rich-text-editor.prompt-input .ProseMirror[contenteditable="true"]');
    let box = editor?.closest('.base-prompt-box');
    let generate = find('button.generate-icon-button[aria-label="Bắt đầu tạo"]');
    let settings = find('button.settings-trigger-button');
    const humanCheck = () => [...document.querySelectorAll('iframe')].some(el => visible(el) && /recaptcha.*(?:bframe|challenge)|(?:bframe|challenge).*recaptcha/i.test(el.src || ''));
    if (humanCheck()) return failure('FLOW_HUMAN_VERIFICATION_REQUIRED');
    if (!editor || !box || !generate || !settings) return failure('FLOW_UI_COMPOSER_REQUIRED');
    // Empty reference controls are observed in the new Angular composer. Never reuse attachments.
    const emptyReferences = [...box.querySelectorAll('button.empty-chip')].filter(visible);
    const emptyIngredients = emptyReferences.length === 0 && box.querySelector('button.add-menu-trigger');
    if ((!emptyIngredients && emptyReferences.length !== 2) || box.querySelector('img,video')) return failure('FLOW_UI_REFERENCES_PRESENT');
    if (window.__aiflowUiBusy) return failure('FLOW_UI_BUSY');
    if (preflightOnly) return { status: 200, data: { transport: 'dom_ui' }, requestSent };
    if (typeof prompt !== 'string' || !prompt.trim() || prompt.length > 12000 || !['16:9', '9:16'].includes(aspect) || typeof allowSilentVideo !== 'boolean'
        || !['ingredients', 'first_frame'].includes(referenceMode) || (referenceMode === 'first_frame' && !reference)) return failure('INVALID_FLOW_UI_REQUEST');
    window.__aiflowUiBusy = true;
    locked = true;
    let referenceBytes = null;
    if (reference) {
      if (!/^[0-9a-f]{64}$/.test(reference.sha256 || '') || reference.name !== `aiflow-reference-${reference.sha256}.png`
          || typeof reference.base64 !== 'string' || reference.base64.length > 7 * 1024**2) return failure('INVALID_FLOW_REFERENCE');
      referenceBytes = Uint8Array.from(atob(reference.base64), char => char.charCodeAt(0));
      const signature = [137, 80, 78, 71, 13, 10, 26, 10];
      if (referenceBytes.length > 5 * 1024**2 || signature.some((value, index) => referenceBytes[index] !== value)) return failure('INVALID_FLOW_REFERENCE');
      const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', referenceBytes))].map(value => value.toString(16).padStart(2, '0')).join('');
      if (digest !== reference.sha256) return failure('INVALID_FLOW_REFERENCE');
    }
    // Preserve unsent user work instead of replacing a different prompt.
    if (editor.textContent.trim() && (reference || editor.textContent.trim() !== prompt.trim())) return failure('FLOW_UI_DRAFT_PRESENT');
    const agent = find('button.agent-mode-chip');
    if (agent?.getAttribute('aria-pressed') === 'true') {
      agent.click();
      if (!await waitFor(() => agent.getAttribute('aria-pressed') === 'false')) return failure('FLOW_UI_COMPOSER_REQUIRED');
    }
    const radio = (label) => [...document.querySelectorAll('button[role="radio"]')].find(el => visible(el) && el.querySelector('.toggle-text')?.textContent.trim() === label);
    if (!radio('Video')) settings.click();
    if (!await waitFor(() => radio('Video'))) return failure('FLOW_UI_SETTINGS_REQUIRED');
    for (const label of ['Video', reference && referenceMode === 'ingredients' ? 'Thành phần' : 'Khung hình', aspect, 'x1']) {
      const control = radio(label);
      if (!control) return failure('FLOW_UI_SETTINGS_REQUIRED');
      if (control.getAttribute('aria-checked') !== 'true') {
        control.click();
        if (!await waitFor(() => radio(label)?.getAttribute('aria-checked') === 'true')) return failure('FLOW_UI_SETTINGS_REQUIRED');
      }
    }
    const model = find('button[aria-label="Chọn nhóm mô hình"]');
    if (!model) return failure('FLOW_UI_LITE_MODEL_REQUIRED');
    if (!/Veo\s*3\.1\s*-\s*Lite/.test(model.textContent)) {
      model.click();
      const lite = await waitFor(() => [...document.querySelectorAll('[role="menuitem"]')].find(el => visible(el) && /^Veo\s*3\.1\s*-\s*Lite$/.test(el.textContent.trim())));
      if (!lite) return failure('FLOW_UI_LITE_MODEL_REQUIRED');
      lite.click();
      if (!await waitFor(() => /Veo\s*3\.1\s*-\s*Lite/.test(model.textContent))) return failure('FLOW_UI_LITE_MODEL_REQUIRED');
    }
    if (!/720p/.test(settings.textContent) || !/8\s*giây/.test(settings.textContent)) return failure('FLOW_UI_EIGHT_SECONDS_REQUIRED');
    // Dismiss the settings popover through a normal outside click.
    editor = find('flow-rich-text-editor.prompt-input .ProseMirror[contenteditable="true"]');
    box = editor?.closest('.base-prompt-box');
    generate = find('button.generate-icon-button[aria-label="Bắt đầu tạo"]');
    if (!editor || !box || !generate) return failure('FLOW_UI_COMPOSER_REQUIRED');
    editor.click();
    if (reference) {
      const frameSlots = () => [...box.querySelectorAll('.frame-trigger')].filter(visible);
      const emptyFrame = (slot, label) => {
        const button = slot?.querySelector('button.empty-chip');
        return visible(button) && button.textContent.trim() === label && !slot.querySelector('img,video') ? button : null;
      };
      const slots = referenceMode === 'first_frame' ? frameSlots() : null;
      if (slots && (slots.length !== 2 || !emptyFrame(slots[0], 'Bắt đầu') || !emptyFrame(slots[1], 'Kết thúc'))) return failure('FLOW_UI_REFERENCE_SELECTION_FAILED', 'first-frame-slots');
      const add = slots ? emptyFrame(slots[0], 'Bắt đầu') : find('button.add-menu-trigger');
      if (!add) return failure('FLOW_UI_REFERENCE_PICKER_REQUIRED');
      if (slots || add.getAttribute('aria-expanded') !== 'true') add.click();
      const livePicker = () => find('flow-add-menu-popover-content');
      const picker = await waitFor(livePicker);
      if (!picker) return failure('FLOW_UI_REFERENCE_PICKER_REQUIRED');
      const search = picker.querySelector('input[aria-label="Tìm kiếm thành phần"]');
      if (!search) return failure('FLOW_UI_REFERENCE_PICKER_REQUIRED');
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
      setter.call(search, reference.name);
      search.dispatchEvent(new Event('input', { bubbles: true }));
      const matches = () => [...(livePicker()?.querySelectorAll('[role="option"]') || [])].filter(el => visible(el) && el.querySelector('.asset-title')?.textContent.trim() === reference.name);
      let uploadDeadline = 0;
      let options = await waitFor(() => matches().length ? matches() : null, 1500);
      if (!options) {
        const upload = livePicker()?.querySelector('button.sidebar-upload-btn');
        const input = () => {
          const files = [...document.querySelectorAll('input[type="file"]')].filter(el => el.accept.includes('.png'));
          return files.length === 1 ? files[0] : null;
        };
        if (!input()) {
          if (!upload) return failure('FLOW_UI_REFERENCE_UPLOAD_REQUIRED');
          upload.click();
        }
        const fileInput = await waitFor(input);
        if (!fileInput) return failure('FLOW_UI_REFERENCE_UPLOAD_REQUIRED');
        const transfer = new DataTransfer();
        transfer.items.add(new File([referenceBytes], reference.name, { type: 'image/png' }));
        fileInput.files = transfer.files;
        uploadDeadline = Date.now() + 45000;
        fileInput.dispatchEvent(new Event('change', { bubbles: true }));
        options = await waitFor(() => matches().length ? matches() : null, Math.max(0, uploadDeadline - Date.now()));
      }
      // Never accept the picker's automatically selected unrelated asset.
      if (!options || options.length !== 1) return failure('FLOW_UI_REFERENCE_UPLOAD_UNCONFIRMED');
      options[0].click();
      // First-upload rendering can replace the picker and option before selection settles.
      const selectedReference = () => {
        const current = matches();
        return current.length === 1 && (current[0].getAttribute('aria-selected') === 'true'
          || current[0].classList.contains('asset-item-active')) ? current[0] : null;
      };
      const confirmReady = () => {
        const currentPicker = livePicker();
        const button = currentPicker?.querySelector('button.detail-add-to-prompt-btn');
        const preview = currentPicker?.querySelector('img.detail-preview-image');
        return selectedReference() && preview?.getAttribute('alt') === `Bản xem trước của ${reference.name}`
          && preview.complete && preview.naturalWidth > 0
          && visible(button) && !button.disabled ? button : null;
      };
      if (referenceMode === 'first_frame') {
        // Cached frames attach on the option click. A pending fresh upload requires its exact loaded preview confirmation.
        const attached = () => {
          editor = find('flow-rich-text-editor.prompt-input .ProseMirror[contenteditable="true"]');
          box = editor?.closest('.base-prompt-box');
          if (!box || livePicker()) return null;
          const current = frameSlots();
          const chip = current[0]?.querySelector('flow-image-ingredient-chip button.chip-container');
          const image = current[0]?.querySelector('img.chip-image');
          return current.length === 2 && chip?.getAttribute('aria-busy') === 'false'
            && chip.getAttribute('aria-label') === 'Thành phần tạo hình ảnh'
            && image?.complete && image.naturalWidth > 0 && current[0].querySelectorAll('img').length === 1
            && emptyFrame(current[1], 'Kết thúc') && box.querySelectorAll('img').length === 1;
        };
        const ready = await waitFor(() => attached() ? true : confirmReady(), uploadDeadline ? Math.max(0, uploadDeadline - Date.now()) : 4000);
        if (!ready) return failure('FLOW_UI_REFERENCE_SELECTION_FAILED', 'first-frame-attachment');
        if (ready !== true) {
          ready.click();
          if (!await waitFor(attached, uploadDeadline ? Math.max(0, uploadDeadline - Date.now()) : 4000)) return failure('FLOW_UI_REFERENCE_SELECTION_FAILED', 'first-frame-attachment');
        }
      } else {
      // The current picker marks the chosen exact asset active while aria-selected stays false.
      if (!await waitFor(selectedReference)) return failure('FLOW_UI_REFERENCE_SELECTION_FAILED', 'reference-selection');
      const confirm = await waitFor(confirmReady, uploadDeadline ? Math.max(0, uploadDeadline - Date.now()) : 4000);
      if (!confirm) return failure('FLOW_UI_REFERENCE_SELECTION_FAILED', 'reference-confirm-ready');
      confirm.click();
      if (!await waitFor(() => !livePicker())) return failure('FLOW_UI_REFERENCE_SELECTION_FAILED', 'reference-picker-close');
      // Adding an ingredient can insert an inline node. Append speech-safe prompt text;
      // do not select all and erase the actual image reference.
      editor = find('flow-rich-text-editor.prompt-input .ProseMirror[contenteditable="true"]');
      if (!editor) return failure('FLOW_UI_COMPOSER_REQUIRED');
      box = editor.closest('.base-prompt-box');
      if (!await waitFor(() => box.querySelectorAll('img').length === 1)) return failure('FLOW_UI_REFERENCE_SELECTION_FAILED', 'reference-attachment');
      }
    }
    editor.focus();
    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(editor);
    if (reference) range.collapse(false);
    selection.removeAllRanges();
    selection.addRange(range);
    if (!document.execCommand('insertText', false, prompt)) return failure('FLOW_UI_PROMPT_INPUT_FAILED');
    if (!await waitFor(() => (reference ? editor.textContent.trim().endsWith(prompt.trim()) : editor.textContent.trim() === prompt.trim()) && !generate.disabled)) return failure('FLOW_UI_PROMPT_INPUT_FAILED');
    if (humanCheck()) return failure('FLOW_HUMAN_VERIFICATION_REQUIRED');
    const gridSettings = find('button[aria-label="Cài đặt lưới ô"]');
    const silentSwitch = () => find('button[role="switch"][name="return-silent-videos"]');
    if (!gridSettings) return failure('FLOW_UI_SILENT_VIDEO_SETTING_REQUIRED');
    if (!silentSwitch()) gridSettings.click();
    const silentControl = await waitFor(silentSwitch);
    const desiredSilent = String(allowSilentVideo);
    if (!silentControl || !['true', 'false'].includes(silentControl.getAttribute('aria-checked'))) return failure('FLOW_UI_SILENT_VIDEO_SETTING_REQUIRED');
    if (silentControl.getAttribute('aria-checked') !== desiredSilent) {
      if (silentControl.disabled || silentControl.getAttribute('aria-disabled') === 'true') return failure('FLOW_UI_SILENT_VIDEO_SETTING_REQUIRED');
      silentControl.click();
      if (!await waitFor(() => silentSwitch()?.getAttribute('aria-checked') === desiredSilent)) return failure('FLOW_UI_SILENT_VIDEO_SETTING_REQUIRED');
    }
    if (silentSwitch()?.getAttribute('aria-checked') !== desiredSilent) return failure('FLOW_UI_SILENT_VIDEO_SETTING_REQUIRED');
    gridSettings.click();
    if (!await waitFor(() => !silentSwitch())) return failure('FLOW_UI_SILENT_VIDEO_SETTING_REQUIRED');
    let observed = null;
    const decode = (text) => {
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
          for (const row of JSON.parse(text.slice(start, i + 1))) {
            if (row?.[0] !== 'wrb.fr' || (!reference && row[1] !== 'YhhmEf')) continue;
            if (typeof row[2] === 'string') {
              const data = JSON.parse(row[2]);
              const media = data?.[3]?.find(entry => entry?.[1] === projectId && entry?.[5]?.[1] === prompt);
              if (media?.[0]) observed = { status: 200, data: { mediaId: media[0], projectId }, requestSent: true };
            } else if (['YhhmEf', 'eb1hJf'].includes(row[1]) && Number.isInteger(row[5]?.[0])) observed = failure(`FLOW_RPC_STATUS_${row[5][0]}`);
          }
          start = -1;
        }
      }
    };
    const isGeneration = (value) => {
      try { const url = new URL(value, location.href); return url.origin === location.origin && url.pathname.endsWith('/data/batchexecute') && (reference || url.searchParams.get('rpcids')?.split(',').includes('YhhmEf')); } catch { return false; }
    };
    const originalFetch = window.fetch;
    const originalOpen = XMLHttpRequest.prototype.open;
    const watchedFetch = async function (...args) {
      const response = await originalFetch.apply(this, args);
      if (isGeneration(args[0]?.url || args[0])) {
        response.clone().text().then(decode).catch(() => {});
      }
      return response;
    };
    const watchedOpen = function (method, url, ...args) {
      if (isGeneration(url)) this.addEventListener('loadend', () => {
        try { decode(this.responseText); } catch { /* binary/unrelated payload */ }
      }, { once: true });
      return originalOpen.call(this, method, url, ...args);
    };
    window.fetch = watchedFetch;
    XMLHttpRequest.prototype.open = watchedOpen;
    cleanup = () => {
      if (window.fetch === watchedFetch) window.fetch = originalFetch;
      if (XMLHttpRequest.prototype.open === watchedOpen) XMLHttpRequest.prototype.open = originalOpen;
    };
    // Do not access grecaptcha or the site's anti-bot guard. Flow handles its own normal click.
    requestSent = true; // A click is ambiguous until its native response has been observed.
    generate.click();
    const deadline = Date.now() + 90000;
    while (Date.now() < deadline) {
      if (observed) return observed;
      if (humanCheck()) return failure('FLOW_HUMAN_VERIFICATION_REQUIRED');
      await pause();
    }
    return failure('FLOW_UI_SUBMISSION_UNCONFIRMED');
  } catch {
    return failure('FLOW_UI_ACTION_FAILED');
  } finally {
    cleanup();
    if (locked) window.__aiflowUiBusy = false;
  }
}
