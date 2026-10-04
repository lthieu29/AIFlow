// Run: node --experimental-vm-modules --test extension/tests/bridge.test.mjs
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';
import { createContext, SourceTextModule } from 'node:vm';
import { createHash, webcrypto } from 'node:crypto';
import { File } from 'node:buffer';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const nextTurn = () => new Promise((done) => setImmediate(done));

async function uiFixture({ refs = false, draft = '', challenge = false, badModel = false, xhr = false, lateComposer = false, referenceMode = false, firstFrame = false, frameNeedsConfirm = false, frameBusy = false, endAttached = false, activeSelection = false, replaceSelectedOption = false, replacePicker = false, delayedConfirm = false, delayedPreview = false, wrongPreview = false, confirmMissing = false, confirmDoesNotClose = false, missingAttachment = false, uploadProcessingMs = 0, silentInitial = false, silentMissing = false, silentUnknown = false, silentDisabled = false, gridInitiallyOpen = false } = {}) {
  const project = '12345678-1234-4234-8234-123456789abc';
  const media = '22345678-1234-4234-8234-123456789abc';
  const prompt = 'A quiet river at dawn';
  const location = { hostname: 'flow.google.com', pathname: `/project/${project}`, origin: 'https://flow.google.com', href: `https://flow.google.com/project/${project}` };
  let clicks = 0, requests = 0, pickerOpen = false, uploaded = false, referenceImages = 0, uploadCount = 0, confirmClicks = 0;
  let gridOpen = gridInitiallyOpen, silentChecked = silentInitial, silentClicks = 0, gridClicks = 0;
  let fakeNow = 0, uploadStarted = 0;
  const bytes = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10, 1]);
  const digest = createHash('sha256').update(bytes).digest('hex');
  const reference = { base64: bytes.toString('base64'), sha256: digest, name: `aiflow-reference-${digest}.png` };
  const visible = { getClientRects: () => [{}] };
  const generate = { ...visible, disabled: true, click: () => {
    assert.equal(gridOpen, false, 'Settings popover must close before generation');
    clicks++;
    const url = 'https://flow.google.com/_/AiSandboxAngularFrontend/data/batchexecute?rpcids=YhhmEf';
    if (xhr) { const request = new FakeXHR(); request.open('POST', url); request.responseText = responseText; request.listener(); }
    else void window.fetch(url);
  } };
  const add = { ...visible, getAttribute: () => String(pickerOpen), click: () => { pickerOpen = true; } };
  const start = { ...visible, textContent: 'Bắt đầu', click: () => { pickerOpen = true; } };
  const end = { ...visible, textContent: 'Kết thúc' };
  const frameImage = { complete: true, naturalWidth: 1280 };
  const frameSlots = [0, 1].map(index => ({ ...visible,
    querySelector: selector => {
      const attached = index === 0 ? referenceImages === 1 : endAttached && selected;
      if (selector === 'button.empty-chip') return attached ? null : index === 0 ? start : end;
      if (selector === 'img,video' || selector === 'img.chip-image') return attached ? { ...frameImage,
        complete: !uploadProcessingMs || fakeNow - uploadStarted >= uploadProcessingMs,
        naturalWidth: !uploadProcessingMs || fakeNow - uploadStarted >= uploadProcessingMs ? 1280 : 0 } : null;
      if (selector === 'flow-image-ingredient-chip button.chip-container') return attached ? {
        getAttribute: name => name === 'aria-busy' ? String(frameBusy) : 'Thành phần tạo hình ảnh' } : null;
      return null;
    }, querySelectorAll: () => index === 0 && referenceImages === 1 ? [frameImage] : [] }));
  const box = { querySelectorAll: selector => selector === '.frame-trigger' ? firstFrame ? frameSlots : [] : selector === 'img' ? Array(referenceImages + (endAttached && selected ? 1 : 0)).fill({}) : refs ? [{ ...visible }] : [{ ...visible }, { ...visible }], querySelector: () => null };
  const editor = { ...visible, textContent: draft, closest: () => box, click() {}, focus() {} };
  const settings = { ...visible, textContent: 'Video · 720p · 8 giây crop_16_9 x1', click() {} };
  const gridSettings = { ...visible, click: () => { gridOpen = !gridOpen; gridClicks++; } };
  const silentControl = { ...visible, disabled: silentDisabled,
    getAttribute: name => name === 'aria-checked' ? silentUnknown ? 'mixed' : String(silentChecked) : null,
    click: () => { silentChecked = !silentChecked; silentClicks++; } };
  const unrelatedSwitch = { ...visible, click: () => assert.fail('Other grid settings must remain unchanged') };
  const radios = ['Video', 'Khung hình', 'Thành phần', '16:9', '9:16', 'x1'].map(label => {
    let checked = label !== '9:16';
    const icon = { Video: 'videocam', 'Khung hình': 'crop_free', '16:9': 'crop_16_9', '9:16': 'crop_9_16' }[label] || '';
    return { ...visible, textContent: icon + label, querySelector: selector => selector === '.toggle-text' ? { textContent: label } : null,
      getAttribute: () => String(checked), click: () => { checked = true; } };
  });
  const model = { ...visible, textContent: badModel ? 'Veo 3.1 - Fast' : 'Veo 3.1 - Lite', click() {} };
  let selected = false, fileInput = null, confirmLookups = 0, previewLookups = 0;
  class FakeInput { get value() { return this.current; } set value(value) { this.current = value; } dispatchEvent() {} }
  const search = new FakeInput();
  const option = { ...visible, querySelector: () => ({ textContent: reference.name }),
    getAttribute: () => String(selected && !replaceSelectedOption && !activeSelection), classList: { contains: name => selected && !replaceSelectedOption && activeSelection && name === 'asset-item-active' },
    click: () => { selected = true; if (firstFrame && !frameNeedsConfirm) { referenceImages = missingAttachment ? 0 : 1; pickerOpen = confirmDoesNotClose; } } };
  const replacementOption = { ...visible, querySelector: () => ({ textContent: reference.name }),
    getAttribute: () => 'false', classList: { contains: name => selected && name === 'asset-item-active' },
    click: () => assert.fail('Selection should be observed on the replacement without another click') };
  const wrongOption = { ...visible, querySelector: () => ({ textContent: 'linh-ivory-ao-dai.png' }), click: () => assert.fail('Must not choose the default unrelated reference') };
  const upload = { click: () => { fileInput = { accept: '.png,.jpg', dispatchEvent: () => {
    assert.equal(fileInput.files[0].name, reference.name);
    assert.equal(fileInput.files[0].type, 'image/png');
    uploaded = true; uploadCount++; fileInput = null;
    uploadStarted = fakeNow;
  } }; } };
  const picker = { getClientRects: () => pickerOpen && !(selected && replacePicker) ? [{}] : [],
    querySelectorAll: () => selected && replacePicker ? [] : uploaded ? [wrongOption, selected && replaceSelectedOption ? replacementOption : option] : [wrongOption],
    querySelector: selector => {
      if (selector.includes('Tìm kiếm')) return search;
      if (selector.includes('sidebar-upload')) return upload;
      if (selector === 'img.detail-preview-image') {
        previewLookups++;
        return { getAttribute: () => `Bản xem trước của ${wrongPreview || delayedPreview && previewLookups === 1 ? 'unrelated.png' : reference.name}`,
          complete: !uploadProcessingMs || fakeNow - uploadStarted >= uploadProcessingMs,
          naturalWidth: !uploadProcessingMs || fakeNow - uploadStarted >= uploadProcessingMs ? 1280 : 0 };
      }
      if (selector.includes('detail-add')) {
        if (firstFrame && !frameNeedsConfirm) return null;
        if (confirmMissing) return null;
        confirmLookups++;
        const disabled = !!(delayedConfirm && confirmLookups === 1 || uploadProcessingMs && fakeNow - uploadStarted < uploadProcessingMs - 2000);
        return { ...visible, disabled, click: () => {
          confirmClicks++;
          assert.equal(disabled, false, 'Must wait for confirmation to become enabled');
          if (delayedPreview) assert.ok(previewLookups > 1, 'Must wait for the exact reference preview');
          assert.equal(wrongPreview, false, 'Must never add an unrelated detail preview');
          referenceImages = missingAttachment ? 0 : 1; pickerOpen = confirmDoesNotClose;
        } };
      }
      return null;
    },
  };
  const replacementPicker = { getClientRects: () => pickerOpen && selected && replacePicker ? [{}] : [],
    querySelectorAll: () => [wrongOption, replacementOption], querySelector: selector => picker.querySelector(selector) };
  let composerLookups = 0;
  const document = {
    querySelectorAll: selector => {
      if (selector === 'iframe') return challenge ? [{ ...visible, src: 'https://www.google.com/recaptcha/api2/bframe' }] : [];
      if (selector.includes('ProseMirror')) return lateComposer && composerLookups++ === 0 ? [] : [editor];
      if (selector.includes('generate-icon-button')) return [generate];
      if (selector.includes('settings-trigger-button')) return [settings];
      if (selector === 'button[aria-label="Cài đặt lưới ô"]') return [gridSettings];
      if (selector === 'button[role="switch"][name="return-silent-videos"]') return gridOpen && !silentMissing ? [silentControl] : [];
      if (selector.includes('[role="switch"]')) return gridOpen ? [unrelatedSwitch] : [];
      if (selector === 'button[role="radio"]') return radios;
      if (selector.includes('Chọn nhóm mô hình')) return [model];
      if (selector.includes('add-menu-trigger')) return referenceMode ? [add] : [];
      if (selector === 'flow-add-menu-popover-content') return referenceMode ? [selected && replacePicker ? replacementPicker : picker] : [];
      if (selector === 'input[type="file"]') return fileInput ? [fileInput] : [];
      return [];
    },
    createRange: () => ({ selectNodeContents() {}, collapse() {} }),
    execCommand: (command, ui, text) => { assert.equal(command, 'insertText'); editor.textContent = text; generate.disabled = false; return true; },
  };
  const metadata = [null, prompt];
  const data = [null, 1030, [], [[media, project, null, null, null, metadata]]];
  const responseText = `)]}'\n\n${JSON.stringify([['wrb.fr', 'YhhmEf', JSON.stringify(data)]])}`;
  class FakeXHR {
    open() { requests++; }
    addEventListener(name, listener) { assert.equal(name, 'loadend'); this.listener = listener; }
  }
  const fetch = async () => { requests++; return { clone: () => ({ text: async () => responseText }) }; };
  const window = { fetch, getSelection: () => ({ removeAllRanges() {}, addRange() {} }) };
  Object.defineProperty(window, 'grecaptcha', { get: () => assert.fail('DOM generation must never access captcha internals') });
  class DataTransfer { constructor() { this.files = []; this.items = { add: file => this.files.push(file) }; } }
  const fakeClock = referenceMode ? {
    Date: class extends Date { static now() { return fakeNow; } },
    setTimeout: (fn, ms) => { fakeNow += ms; return setImmediate(fn); },
  } : {};
  const bridge = await loadBridge('modules/flow_ui.js', { window, document, location, XMLHttpRequest: FakeXHR,
    crypto: webcrypto, atob, Uint8Array, File, DataTransfer, HTMLInputElement: FakeInput, Event, ...fakeClock });
  return { bridge, project, media, prompt, reference, editor, window, fetch, FakeXHR, counts: () => ({ clicks, requests }), uploads: () => uploadCount, confirms: () => confirmClicks,
    silent: () => ({ checked: silentChecked, clicks: silentClicks, gridClicks }) };
}

test('first-frame exact SHA option autoattaches to start and leaves end empty without ingredient confirmation', async () => {
  const f = await uiFixture({ referenceMode: true, firstFrame: true, uploadProcessingMs: 10000 });
  const result = await f.bridge.api.executeFlowUi(f.project, f.prompt, '16:9', false, f.reference, true, 'first_frame');
  assert.equal(result.data?.mediaId, f.media, result.error);
  assert.equal(f.uploads(), 1);
  assert.equal(f.confirms(), 0);
  assert.deepEqual(f.counts(), { clicks: 1, requests: 1 });
});

test('pending first-frame upload confirms only its selected exact loaded preview once', async () => {
  const f = await uiFixture({ referenceMode: true, firstFrame: true, frameNeedsConfirm: true, activeSelection: true, replacePicker: true, uploadProcessingMs: 10000 });
  const result = await f.bridge.api.executeFlowUi(f.project, f.prompt, '16:9', false, f.reference, true, 'first_frame');
  assert.equal(result.data?.mediaId, f.media, result.error);
  assert.equal(f.uploads(), 1);
  assert.equal(f.confirms(), 1);
  assert.deepEqual(f.counts(), { clicks: 1, requests: 1 });
});

for (const options of [{ wrongPreview: true }, { confirmMissing: true }, { uploadProcessingMs: 46000 }]) {
  test(`pending first-frame confirmation rejects ${Object.keys(options).join(',')} before generation`, async () => {
    const f = await uiFixture({ referenceMode: true, firstFrame: true, frameNeedsConfirm: true, activeSelection: true, ...options });
    const result = await f.bridge.api.executeFlowUi(f.project, f.prompt, '16:9', false, f.reference, false, 'first_frame');
    assert.equal(result.error, 'FLOW_UI_REFERENCE_SELECTION_FAILED');
    assert.equal(result.uiStage, 'first-frame-attachment');
    assert.equal(f.confirms(), 0);
    assert.equal(result.requestSent, false);
    assert.deepEqual(f.counts(), { clicks: 0, requests: 0 });
  });
}

for (const options of [{ frameBusy: true }, { endAttached: true }, { missingAttachment: true }, { confirmDoesNotClose: true }, { uploadProcessingMs: 46000 }]) {
  test(`first-frame attachment rejects ${Object.keys(options).join(',')} before generation`, async () => {
    const f = await uiFixture({ referenceMode: true, firstFrame: true, ...options });
    const result = await f.bridge.api.executeFlowUi(f.project, f.prompt, '16:9', false, f.reference, false, 'first_frame');
    assert.equal(result.error, 'FLOW_UI_REFERENCE_SELECTION_FAILED');
    assert.equal(result.uiStage, 'first-frame-attachment');
    assert.equal(result.requestSent, false);
    assert.deepEqual(f.counts(), { clicks: 0, requests: 0 });
  });
}

for (const mode of ['frames', 'first_frame']) {
  test(`reference mode ${mode} cannot submit without its required image`, async () => {
    const f = await uiFixture();
    const result = await f.bridge.api.executeFlowUi(f.project, f.prompt, '16:9', false, null, false, mode);
    assert.equal(result.error, 'INVALID_FLOW_UI_REQUEST');
    assert.deepEqual(f.counts(), { clicks: 0, requests: 0 });
  });
}

test('fresh reference upload waits for ten-second processing and loaded exact preview before confirming', async () => {
  const f = await uiFixture({ referenceMode: true, activeSelection: true, uploadProcessingMs: 10000 });
  const result = await f.bridge.api.executeFlowUi(f.project, f.prompt, '16:9', false, f.reference);
  assert.equal(result.data?.mediaId, f.media, result.error);
  assert.equal(f.uploads(), 1);
  assert.deepEqual(f.counts(), { clicks: 1, requests: 1 });
});

test('fresh reference processing beyond the shared 45-second upload budget fails before generation', async () => {
  const f = await uiFixture({ referenceMode: true, activeSelection: true, uploadProcessingMs: 46000 });
  const result = await f.bridge.api.executeFlowUi(f.project, f.prompt, '16:9', false, f.reference);
  assert.equal(result.error, 'FLOW_UI_REFERENCE_SELECTION_FAILED');
  assert.equal(result.uiStage, 'reference-confirm-ready');
  assert.equal(result.requestSent, false);
  assert.deepEqual(f.counts(), { clicks: 0, requests: 0 });
});

test('DOM capability reads composer without touching prompt, captcha or generation', async () => {
  const f = await uiFixture();
  const result = await f.bridge.api.executeFlowUi(f.project, '', '16:9', true);
  assert.equal(result.status, 200);
  assert.equal(result.data.transport, 'dom_ui');
  assert.equal(result.requestSent, false);
  assert.equal(f.editor.textContent, '');
  assert.deepEqual(f.counts(), { clicks: 0, requests: 0 });
});

test('DOM capability waits for Angular composer after tab navigation completes', async () => {
  const f = await uiFixture({ lateComposer: true });
  const result = await f.bridge.api.executeFlowUi(f.project, '', '16:9', true);
  assert.equal(result.status, 200);
  assert.deepEqual(f.counts(), { clicks: 0, requests: 0 });
});

test('reference upload uses SHA-bound PNG and explicitly selects its asset, never the default Linh item', async () => {
  const f = await uiFixture({ referenceMode: true });
  const result = await f.bridge.api.executeFlowUi(f.project, f.prompt, '16:9', false, f.reference);
  assert.equal(result.data.mediaId, f.media);
  assert.equal(f.uploads(), 1);
  assert.deepEqual(f.counts(), { clicks: 1, requests: 1 });
});

test('current picker active class confirms the exact SHA asset despite aria-selected staying false', async () => {
  const f = await uiFixture({ referenceMode: true, activeSelection: true });
  const result = await f.bridge.api.executeFlowUi(f.project, f.prompt, '16:9', false, f.reference);
  assert.equal(result.data.mediaId, f.media);
  assert.equal(f.uploads(), 1);
  assert.deepEqual(f.counts(), { clicks: 1, requests: 1 });
});

for (const options of [
  { replaceSelectedOption: true },
  { delayedConfirm: true },
  { replaceSelectedOption: true, delayedConfirm: true },
  { replacePicker: true },
  { replacePicker: true, delayedConfirm: true },
  { replacePicker: true, delayedPreview: true },
]) {
  test(`first-upload selection survives ${Object.keys(options).join(' and ')}`, async () => {
    const f = await uiFixture({ referenceMode: true, activeSelection: true, ...options });
    const result = await f.bridge.api.executeFlowUi(f.project, f.prompt, '16:9', false, f.reference);
    assert.equal(result.data?.mediaId, f.media, result.error);
    assert.equal(f.uploads(), 1);
    assert.deepEqual(f.counts(), { clicks: 1, requests: 1 });
  });
}

for (const [options, stage] of [
  [{ confirmMissing: true }, 'reference-confirm-ready'],
  [{ wrongPreview: true }, 'reference-confirm-ready'],
  [{ confirmDoesNotClose: true }, 'reference-picker-close'],
  [{ missingAttachment: true }, 'reference-attachment'],
]) {
  test(`reference failure reports ${stage} without a generation request`, async () => {
    const f = await uiFixture({ referenceMode: true, activeSelection: true, ...options });
    const result = await f.bridge.api.executeFlowUi(f.project, f.prompt, '16:9', false, f.reference);
    assert.equal(result.error, 'FLOW_UI_REFERENCE_SELECTION_FAILED');
    assert.equal(result.uiStage, stage);
    assert.equal(result.requestSent, false);
    assert.deepEqual(f.counts(), { clicks: 0, requests: 0 });
  });
}

test('a changed reference payload is rejected before upload or native generation', async () => {
  const f = await uiFixture({ referenceMode: true });
  const result = await f.bridge.api.executeFlowUi(f.project, f.prompt, '16:9', false, { ...f.reference, base64: f.reference.base64.slice(0, -4) + 'Ag==' });
  assert.equal(result.error, 'INVALID_FLOW_REFERENCE');
  assert.equal(result.requestSent, false);
  assert.equal(f.uploads(), 0);
  assert.deepEqual(f.counts(), { clicks: 0, requests: 0 });
});

for (const [initial, requested, toggleClicks] of [[false, true, 1], [true, false, 1], [false, false, 0], [true, true, 0]]) {
  test(`silent-video option explicitly sets ${initial} to ${requested} before native generation`, async () => {
    const f = await uiFixture({ silentInitial: initial });
    const result = await f.bridge.api.executeFlowUi(f.project, f.prompt, '16:9', false, null, requested);
    assert.equal(result.data.mediaId, f.media);
    assert.deepEqual(f.silent(), { checked: requested, clicks: toggleClicks, gridClicks: 2 });
    assert.deepEqual(f.counts(), { clicks: 1, requests: 1 });
  });
}

test('silent-video option closes an already open grid popover and preserves unrelated settings', async () => {
  const f = await uiFixture({ gridInitiallyOpen: true });
  const result = await f.bridge.api.executeFlowUi(f.project, f.prompt, '16:9', false, null, true);
  assert.equal(result.data.mediaId, f.media);
  assert.deepEqual(f.silent(), { checked: true, clicks: 1, gridClicks: 1 });
});

test('silent-video option defaults to false even when the page setting was enabled', async () => {
  const f = await uiFixture({ silentInitial: true });
  const result = await f.bridge.api.executeFlowUi(f.project, f.prompt, '16:9');
  assert.equal(result.data.mediaId, f.media);
  assert.equal(f.silent().checked, false);
});

for (const options of [{ silentMissing: true }, { silentUnknown: true }, { silentDisabled: true }]) {
  test(`silent-video setting fails closed for ${Object.keys(options)[0]}`, async () => {
    const f = await uiFixture(options);
    const result = await f.bridge.api.executeFlowUi(f.project, f.prompt, '16:9', false, null, true);
    assert.equal(result.error, 'FLOW_UI_SILENT_VIDEO_SETTING_REQUIRED');
    assert.equal(result.requestSent, false);
    assert.deepEqual(f.counts(), { clicks: 0, requests: 0 });
  });
}

for (const xhr of [false, true]) test(`normal DOM generation binds native ${xhr ? 'XHR' : 'fetch'} result to prompt/project and restores observer`, async () => {
  const f = await uiFixture({ xhr });
  const originalOpen = f.FakeXHR.prototype.open;
  const result = await f.bridge.api.executeFlowUi(f.project, f.prompt, '16:9');
  assert.equal(result.data.mediaId, f.media);
  assert.equal(result.data.projectId, f.project);
  assert.equal(result.requestSent, true);
  assert.deepEqual(f.counts(), { clicks: 1, requests: 1 });
  assert.equal(f.window.fetch, f.fetch);
  assert.equal(f.FakeXHR.prototype.open, originalOpen);
  assert.equal(f.window.__aiflowUiBusy, false);
});

for (const [options, error] of [
  [{ refs: true }, 'FLOW_UI_REFERENCES_PRESENT'],
  [{ draft: 'Unsent user prompt' }, 'FLOW_UI_DRAFT_PRESENT'],
  [{ challenge: true }, 'FLOW_HUMAN_VERIFICATION_REQUIRED'],
]) test(`DOM guard ${error} never submits or overwrites a draft`, async () => {
  const f = await uiFixture(options);
  const result = await f.bridge.api.executeFlowUi(f.project, f.prompt, '16:9');
  assert.equal(result.error, error);
  assert.equal(result.requestSent, false);
  assert.equal(f.editor.textContent, options.draft || '');
  assert.deepEqual(f.counts(), { clicks: 0, requests: 0 });
});

async function loadBridge(file, overrides = {}) {
  const sockets = [], alarms = [], errors = [], requests = [], tabQueries = [];
  const listeners = () => ({ addListener() {} });
  class FakeSocket {
    static CONNECTING = 0;
    static OPEN = 1;
    constructor(url) { this.url = url; this.readyState = 0; this.sent = []; sockets.push(this); }
    send(message) { this.sent.push(JSON.parse(message)); }
  }
  const chrome = {
    runtime: {
      onInstalled: listeners(), onStartup: listeners(), onMessage: listeners(),
      sendMessage: async () => {}, getManifest: () => ({ version: '0.1.0' }),
    },
    storage: { local: { get: async () => ({}), set: async () => {} } },
    alarms: { onAlarm: listeners(), create: (name) => alarms.push(name) },
    action: { setBadgeText() {}, setBadgeBackgroundColor() {} },
    cookies: { onChanged: listeners(), getAll: (_, reply) => reply([]) },
    webRequest: { onBeforeSendHeaders: listeners() },
    tabs: {
      query: async (query) => { tabQueries.push(query); return [{ id: 1, url: 'https://flow.google.com/project/test' }]; },
      sendMessage: async () => ({ token: 'fake-captcha' }),
      update: async () => {},
    },
    scripting: { executeScript: async () => {} },
  };
  const context = createContext({
    chrome, WebSocket: FakeSocket, URL, URLSearchParams,
    console: { log() {}, warn() {}, error: (...args) => errors.push(args.join(' ')) },
    setTimeout: (fn, ms) => { const timer = setTimeout(fn, ms); timer.unref(); return timer; }, clearTimeout,
    fetch: async (url, options) => {
      requests.push({ url, options });
      return { ok: true, status: 200, json: async () => ({ ws_url: 'ws://127.0.0.1:9223' }) };
    },
    ...overrides,
  });
  const modules = new Map();
  async function load(path) {
    if (modules.has(path)) return modules.get(path);
    const module = new SourceTextModule(await readFile(path, 'utf8'), { context, identifier: path });
    modules.set(path, module);
    await module.link((specifier, ref) => load(resolve(dirname(ref.identifier), specifier)));
    return module;
  }
  const module = await load(resolve(root, file));
  await module.evaluate();
  return { api: module.namespace, chrome, sockets, alarms, errors, requests, tabQueries, context };
}

for (const requested of [undefined, false, true]) {
  test(`UI proxy forwards strict silent-video flag ${requested ?? 'default false'} to MAIN world`, async () => {
    const bridge = await loadBridge('modules/flow_proxy.js');
    const projectId = '12345678-1234-4234-8234-123456789abc';
    bridge.chrome.tabs.query = async () => [{ id: 1, url: `https://flow.google.com/project/${projectId}` }];
    let injected;
    bridge.chrome.scripting.executeScript = async input => { injected = input; return [{ result: { status: 200 } }]; };
    const params = { projectId, prompt: 'Silent pottery scene' };
    if (requested !== undefined) params.allow_silent_video = requested;
    await bridge.api.handleFlowMessage({ id: 'silent-request', method: 'flow_ui_request', params }, {});
    assert.equal(injected.world, 'MAIN');
    assert.equal(injected.args[5], requested ?? false);
    assert.equal(injected.args[6], 'ingredients');
  });
}

test('UI proxy forwards first-frame mode and its reference to MAIN world', async () => {
  const bridge = await loadBridge('modules/flow_proxy.js');
  const projectId = '12345678-1234-4234-8234-123456789abc';
  bridge.chrome.tabs.query = async () => [{ id: 1, url: `https://flow.google.com/project/${projectId}` }];
  let injected;
  bridge.chrome.scripting.executeScript = async input => { injected = input; return [{ result: { status: 200 } }]; };
  await bridge.api.handleFlowMessage({ id: 'frame', method: 'flow_ui_request', params: { projectId, prompt: 'Pottery', reference_mode: 'first_frame', reference: { name: 'fixture.png' } } }, {});
  assert.equal(injected.args[6], 'first_frame');
  assert.equal(injected.args[4].name, 'fixture.png');
});

for (const mode of ['frames', 'first_frame']) {
  test(`UI proxy rejects ${mode} without a valid reference before accessing tabs`, async () => {
    const bridge = await loadBridge('modules/flow_proxy.js');
    await bridge.api.handleFlowMessage({ id: 'frame-invalid', method: 'flow_ui_request', params: { reference_mode: mode } }, {});
    assert.equal(bridge.tabQueries.length, 0);
    assert.equal(JSON.parse(bridge.requests[0].options.body).error, 'INVALID_FLOW_UI_REQUEST');
  });
}

test('UI proxy rejects a nonboolean silent-video flag before accessing the page', async () => {
  const bridge = await loadBridge('modules/flow_proxy.js');
  let injections = 0;
  bridge.chrome.scripting.executeScript = async () => { injections++; };
  await bridge.api.handleFlowMessage({ id: 'invalid-silent', method: 'flow_ui_request', params: { allow_silent_video: 'true' } }, {});
  await nextTurn();
  assert.equal(injections, 0);
  assert.equal(bridge.tabQueries.length, 0);
  assert.equal(JSON.parse(bridge.requests[0].options.body).error, 'INVALID_FLOW_UI_REQUEST');
});

test('MV3 worker initializes on an ordinary wake without installed/startup events', async () => {
  const bridge = await loadBridge('background.js');
  await nextTurn();
  assert.deepEqual(bridge.errors, []);
  assert.equal(bridge.sockets.length, 1);
  assert.ok(bridge.alarms.includes('keepAlive'));
});

test('manifest injects captcha bridge into new and legacy Flow pages', async () => {
  const manifest = JSON.parse(await readFile(resolve(root, 'manifest.json'), 'utf8'));
  assert.ok(manifest.host_permissions.includes('https://flow.google.com/*'));
  assert.ok(manifest.content_scripts[0].matches.includes('https://flow.google.com/*'));
  assert.ok(manifest.content_scripts[0].matches.includes('https://labs.google/fx/tools/flow*'));
  assert.ok(manifest.web_accessible_resources[0].matches.includes('https://flow.google.com/*'));
  const rules = JSON.parse(await readFile(resolve(root, 'rules.json'), 'utf8'));
  assert.deepEqual(rules[0].condition.excludedInitiatorDomains, ['labs.google', 'flow.google.com']);
});

test('Open Flow reuses a tab on the current domain', async () => {
  const bridge = await loadBridge('modules/flow_proxy.js');
  const result = await bridge.api.openFlowTab();
  assert.equal(result.tabId, 1);
  assert.ok(bridge.tabQueries[0].url.includes('https://flow.google.com/*'));
});

test('Refresh token reports failure when a signed-in Flow page emits no API token', async () => {
  const bridge = await loadBridge('modules/flow_proxy.js');
  const result = await bridge.api.captureTokenFromFlowTab({ flow: { token: null, capturedAt: null } });
  assert.equal(result.ok, false);
  assert.match(result.error, /FLOW_TOKEN_MISSING/);
});

test('Refresh token does not claim an unchanged cached token was refreshed', async () => {
  const bridge = await loadBridge('modules/flow_proxy.js');
  const result = await bridge.api.captureTokenFromFlowTab({ flow: { token: 'fake-old-token', capturedAt: 1 } });
  assert.equal(result.ok, false);
});

test('Refresh token succeeds only when a new token capture is observed', async () => {
  const bridge = await loadBridge('modules/flow_proxy.js');
  const state = { flow: { token: null, capturedAt: null } };
  bridge.chrome.scripting.executeScript = async () => {
    state.flow.token = 'fake-new-token';
    state.flow.capturedAt = 2;
  };
  assert.equal((await bridge.api.captureTokenFromFlowTab(state)).ok, true);
});

test('remote Flow project parser accepts current and legacy routes and rejects local IDs', async () => {
  const { api } = await loadBridge('modules/flow_proxy.js');
  const id = 'dafc6eda-c82e-4864-ba19-2140a20e2f9e';
  for (const url of [
    `https://flow.google.com/project/${id}`,
    `https://labs.google/fx/tools/flow/project/${id}`,
    `https://labs.google/fx/vi/tools/flow/project/${id}`,
  ]) assert.equal(api.flowProjectIdFromUrl(url), id);
  for (const url of [
    'https://flow.google.com/project/1', `https://evil.example/project/${id}`,
    `https://flow.google.com.evil.example/project/${id}`, 'https://flow.google.com/',
  ]) assert.equal(api.flowProjectIdFromUrl(url), null);
});

test('project RPC prefers the active project tab and returns only its UUID', async () => {
  const bridge = await loadBridge('modules/flow_proxy.js');
  const id = 'dafc6eda-c82e-4864-ba19-2140a20e2f9e';
  bridge.chrome.tabs.query = async () => [
    { id: 1, active: false, url: 'https://flow.google.com/project/12345678-1234-1234-1234-123456789abc' },
    { id: 2, active: true, url: `https://flow.google.com/project/${id}` },
  ];
  await bridge.api.handleFlowMessage({ id: 'project-request', method: 'get_flow_project' }, {});
  await nextTurn();
  const payload = JSON.parse(bridge.requests[0].options.body);
  assert.deepEqual(payload, { id: 'project-request', status: 200, data: { projectId: id } });
});

test('project RPC fails clearly when only Flow landing page is open', async () => {
  const bridge = await loadBridge('modules/flow_proxy.js');
  bridge.chrome.tabs.query = async () => [{ id: 1, url: 'https://flow.google.com/' }];
  await bridge.api.handleFlowMessage({ id: 'request', method: 'get_flow_project' }, {});
  await nextTurn();
  const payload = JSON.parse(bridge.requests[0].options.body);
  assert.equal(payload.status, 404);
  assert.match(payload.error, /FLOW_PROJECT_REQUIRED/);
});

test('opening an existing project rejects untrusted URLs before accessing tabs', async () => {
  const bridge = await loadBridge('modules/flow_proxy.js');
  const id = 'dafc6eda-c82e-4864-ba19-2140a20e2f9e';
  for (const url of [
    `http://flow.google.com/project/${id}`, `https://evil.example/project/${id}`,
    `https://flow.google.com.evil.example/project/${id}`, `https://user@flow.google.com/project/${id}`,
    `https://flow.google.com:9443/project/${id}`, `https://flow.google.com/project/${id}?token=anything`,
    `https://flow.google.com/project/${id}/other`, 'https://flow.google.com/project/5',
  ]) {
    assert.equal((await bridge.api.openFlowProject(url)).status, 400);
  }
  assert.equal(bridge.tabQueries.length, 0);
});

test('opening an already loaded project activates it without reloading or executing scripts', async () => {
  const bridge = await loadBridge('modules/flow_proxy.js');
  const id = 'dafc6eda-c82e-4864-ba19-2140a20e2f9e';
  const url = `https://flow.google.com/project/${id}`;
  const updates = [];
  bridge.chrome.tabs.query = async () => [{ id: 7, url, status: 'complete' }];
  bridge.chrome.tabs.update = async (tabId, options) => { updates.push({ tabId, options: { ...options } }); return { id: tabId }; };
  bridge.chrome.tabs.get = async () => ({ id: 7, url, status: 'complete' });
  bridge.chrome.scripting.executeScript = async () => { throw new Error('opening a project must not execute generation'); };
  assert.equal((await bridge.api.openFlowProject(url)).status, 200);
  assert.deepEqual(updates, [{ tabId: 7, options: { active: true } }]);
});

test('project open RPC navigates a landing tab and acknowledges the correct loaded UUID', async () => {
  const bridge = await loadBridge('modules/flow_proxy.js');
  const id = 'dafc6eda-c82e-4864-ba19-2140a20e2f9e';
  const url = `https://flow.google.com/project/${id}`;
  const updates = [];
  bridge.chrome.tabs.query = async () => [
    { id: 3, url: 'https://flow.google.com/project/12345678-1234-1234-1234-123456789abc' },
    { id: 8, url: 'https://flow.google.com/' },
  ];
  bridge.chrome.tabs.update = async (tabId, options) => { updates.push({ tabId, options: { ...options } }); return { id: tabId }; };
  bridge.chrome.tabs.get = async () => ({ id: 8, url, status: 'complete' });
  await bridge.api.handleFlowMessage({ id: 'open-request', method: 'open_flow_project', params: { url } }, {});
  await nextTurn();
  assert.deepEqual(updates, [{ tabId: 8, options: { active: true, url } }]);
  assert.deepEqual(JSON.parse(bridge.requests[0].options.body), {
    id: 'open-request', status: 200, data: { projectId: id },
  });
});

test('opening a project creates a tab instead of replacing another project', async () => {
  const bridge = await loadBridge('modules/flow_proxy.js');
  const id = 'dafc6eda-c82e-4864-ba19-2140a20e2f9e';
  const url = `https://flow.google.com/project/${id}`;
  const creates = [];
  bridge.chrome.tabs.query = async () => [{ id: 3, url: 'https://flow.google.com/project/12345678-1234-1234-1234-123456789abc' }];
  bridge.chrome.tabs.update = async () => { throw new Error('must preserve the other project'); };
  bridge.chrome.tabs.create = async options => { creates.push({ ...options }); return { id: 9 }; };
  bridge.chrome.tabs.get = async () => ({ id: 9, url, status: 'complete' });
  assert.equal((await bridge.api.openFlowProject(url)).status, 200);
  assert.equal(creates.length, 1);
  assert.equal(creates[0].url, url);
  assert.equal(creates[0].active, true);
});

test('opening a project reports an unavailable tab without leaking a Chrome error', async () => {
  const bridge = await loadBridge('modules/flow_proxy.js');
  bridge.chrome.tabs.query = async () => { throw new Error('private-browser-error'); };
  const result = await bridge.api.openFlowProject('https://flow.google.com/project/dafc6eda-c82e-4864-ba19-2140a20e2f9e');
  assert.equal(result.status, 503);
  assert.equal(result.error, 'FLOW_PROJECT_TAB_UNAVAILABLE');
});

test('captcha retries another Flow tab after a content error response', async () => {
  const bridge = await loadBridge('modules/flow_proxy.js');
  const calls = [];
  bridge.chrome.tabs.query = async () => [{ id: 1 }, { id: 2 }];
  bridge.chrome.tabs.sendMessage = async (id) => {
    calls.push(id);
    return id === 1 ? { error: 'grecaptcha not available' } : { token: 'working-captcha' };
  };
  assert.equal((await bridge.api.solveCaptcha('request', 'VIDEO_GENERATION')).token, 'working-captcha');
  assert.deepEqual(calls, [1, 2]);
});

test('concurrent reconnect calls create one socket and one discovery request', async () => {
  const bridge = await loadBridge('modules/shared.js');
  const state = { flow: {} };
  await Promise.all([
    bridge.api.connectAgent(state, () => {}), bridge.api.connectAgent(state, () => {}),
  ]);
  assert.equal(bridge.sockets.length, 1);
  assert.equal(bridge.requests.length, 1);
  await bridge.api.connectAgent(state, () => {});
  assert.equal(bridge.sockets.length, 1);
});

test('an obsolete socket close event cannot disconnect its replacement', async () => {
  const bridge = await loadBridge('modules/shared.js');
  const state = { flow: {}, connected: true };
  await bridge.api.connectAgent(state, () => {});
  const oldSocket = state.ws;
  oldSocket.readyState = 3;
  await bridge.api.connectAgent(state, () => {});
  state.ws.onopen();
  oldSocket.onclose();
  assert.equal(state.connected, true);
  assert.deepEqual(bridge.alarms, []);
});

test('HTTP callback rejection falls back to the active WebSocket', async () => {
  const bridge = await loadBridge('modules/shared.js', {
    fetch: async () => ({ ok: false, status: 401 }),
  });
  const sent = [];
  const state = { ws: { readyState: 1, send: (raw) => sent.push(JSON.parse(raw)) } };
  bridge.api.sendToAgent(state, { id: 'request', status: 200, data: {} });
  await nextTurn();
  assert.equal(sent[0].id, 'request');
});

test('HTTP callback success sends no duplicate WebSocket response', async () => {
  const bridge = await loadBridge('modules/shared.js');
  let count = 0;
  const state = { ws: { readyState: 1, send: () => count++ } };
  bridge.api.sendToAgent(state, { id: 'request', status: 200 });
  await nextTurn();
  assert.equal(count, 0);
});

test('current Flow RPC runs with page CSRF and returns only parsed payload', async () => {
  let options;
  const page = {
    location: { hostname: 'flow.google.com', origin: 'https://flow.google.com', pathname: '/project/test' },
    WIZ_global_data: { SNlM0e: 'fake-page-csrf' },
    grecaptcha: { enterprise: { execute: async () => 'fake-page-captcha' } },
  };
  const data = [null, 10, [['media-id']]];
  const text = `)]}'\n\n999\n${JSON.stringify([['wrb.fr', 'YhhmEf', JSON.stringify(data), null]])}\n`;
  const bridge = await loadBridge('modules/flow_rpc.js', { window: page,
    fetch: async (_, opts) => { options = opts; return { ok: true, status: 200, text: async () => text }; },
  });
  const request = [[], [null, 22], []];
  const result = await bridge.api.executeFlowRpc('YhhmEf', request, 'VIDEO_GENERATION', 'public-key');
  assert.equal(JSON.stringify(result), JSON.stringify({ status: 200, data, requestSent: true }));
  const form = new URLSearchParams(options.body);
  assert.equal(form.get('at'), 'fake-page-csrf');
  const payload = JSON.parse(JSON.parse(form.get('f.req'))[0][0][1]);
  assert.equal(payload[1][10][0], 'fake-page-captcha');
  assert.equal(request[1].length, 2);
  assert.ok(!JSON.stringify(result).includes('fake-page-'));
});

test('RPC decoder handles framed unicode and nested quoted brackets', async () => {
  const data = ['Cảnh [nắng] "sáng"'];
  const text = `)]}'\n15\n${JSON.stringify([['di', 2]])}\n100\n${JSON.stringify([['wrb.fr', 'as29s', JSON.stringify(data)]])}`;
  const bridge = await loadBridge('modules/flow_rpc.js', {
    window: { location: { hostname: 'flow.google.com', origin: 'https://flow.google.com' }, WIZ_global_data: { SNlM0e: 'fake-csrf' } },
    fetch: async () => ({ ok: true, status: 200, text: async () => text }),
  });
  assert.equal(JSON.stringify((await bridge.api.executeFlowRpc('as29s', [], null)).data), JSON.stringify(data));
});

test('RPC does not claim success for a login error or an empty wrapper response', async () => {
  const bridge = await loadBridge('modules/flow_rpc.js', {
    window: { location: { hostname: 'flow.google.com', origin: 'https://flow.google.com' }, WIZ_global_data: {} },
  });
  assert.match((await bridge.api.executeFlowRpc('as29s', [], null)).error, /SESSION_MISSING/);
  bridge.context.window.WIZ_global_data.SNlM0e = 'fake-csrf';
  bridge.context.fetch = async () => ({ ok: true, status: 200, text: async () => `)]}'\n[["wrb.fr","as29s",null]]` });
  assert.match((await bridge.api.executeFlowRpc('as29s', [], null)).error, /RESPONSE_MISSING/);
});

test('Flow session check uses read-only GetModels and needs no legacy Bearer', async () => {
  const bridge = await loadBridge('modules/flow_proxy.js');
  const id = 'dafc6eda-c82e-4864-ba19-2140a20e2f9e';
  bridge.chrome.tabs.query = async () => [{ id: 1, url: `https://flow.google.com/project/${id}` }];
  let options;
  bridge.chrome.scripting.executeScript = async (input) => {
    options = input;
    return [{ result: { status: 200, data: [null, null, []] } }];
  };
  const state = { connected: true, flow: { token: null } };
  assert.equal((await bridge.api.refreshFlowSession(state)).ok, true);
  assert.equal(options.world, 'MAIN');
  assert.equal(options.args[0], 'HTrJv');
  assert.equal(JSON.stringify(options.args[1]), '[]');
  assert.equal(options.args[2], null);
  assert.equal(state.flow.rpcReady, true);
});

test('Flow native captcha guard prevents preflight and submit without executing captcha or fetch', async () => {
  const execute = async () => { throw new Error('extension_hijack_detected'); };
  let fetchCount = 0;
  const bridge = await loadBridge('modules/flow_rpc.js', {
    window: { location: { hostname: 'flow.google.com' }, WIZ_global_data: { SNlM0e: 'fake-csrf' },
      grecaptcha: { enterprise: { execute } } },
    fetch: async () => fetchCount++,
  });
  for (const preflight of [true, false]) {
    const result = await bridge.api.executeFlowRpc('YhhmEf', [], 'VIDEO_GENERATION', 'public-key', preflight);
    assert.equal(result.error, 'FLOW_UI_GENERATION_REQUIRED');
    assert.equal(result.requestSent, false);
  }
  assert.equal(fetchCount, 0);
});

test('unguarded capability preflight does not execute captcha or make a request', async () => {
  let calls = 0;
  const bridge = await loadBridge('modules/flow_rpc.js', {
    window: { location: { hostname: 'flow.google.com' }, WIZ_global_data: { SNlM0e: 'fake-csrf' },
      grecaptcha: { enterprise: { execute: async () => calls++ } } },
    fetch: async () => calls++,
  });
  const result = await bridge.api.executeFlowRpc('YhhmEf', [], 'VIDEO_GENERATION', 'public-key', true);
  assert.equal(result.status, 200);
  assert.equal(result.requestSent, false);
  assert.equal(calls, 0);
});

test('RPC rejection frame returns numeric status without leaking payload or credentials', async () => {
  const bridge = await loadBridge('modules/flow_rpc.js', {
    window: { location: { hostname: 'flow.google.com', origin: 'https://flow.google.com' }, WIZ_global_data: { SNlM0e: 'fake-csrf' } },
    fetch: async () => ({ ok: true, status: 200,
      text: async () => `)]}'\n[["wrb.fr","jwpduf",null,null,null,[3,"secret-message"],"generic"]]` }),
  });
  const result = await bridge.api.executeFlowRpc('jwpduf', [], null);
  assert.equal(result.error, 'FLOW_RPC_STATUS_3');
  assert.equal(result.rpcStatus, 3);
  assert.equal(result.requestSent, true);
  assert.ok(!JSON.stringify(result).includes('secret-message'));
});

test('RPC proxy rejects arbitrary methods before executing page code', async () => {
  const bridge = await loadBridge('modules/flow_proxy.js');
  let count = 0;
  bridge.chrome.scripting.executeScript = async () => count++;
  await bridge.api.handleFlowMessage({ id: 'request', method: 'flow_rpc_request', params: { rpcId: 'unknown', request: [] } }, { flow: {} });
  await nextTurn();
  assert.equal(count, 0);
  assert.equal(JSON.parse(bridge.requests[0].options.body).error, 'INVALID_FLOW_RPC');
});
