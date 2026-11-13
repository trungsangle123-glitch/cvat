/* CVAT SAM 3 Segment — content script.
 *
 * Runs on the CVAT annotation page. It does NOT touch React state or cvat-core.
 * Workflow:
 *   1. current frame pixels come from #cvat_canvas_background (same resolution
 *      as the source frame: cvat-data sets renderWidth/Height from data meta)
 *   2. click / drag coordinates are mapped back to that canvas space
 *   3. the image goes to the SAM 3 function through the background worker
 *   4. returned masks are PATCHed into the job via the CVAT REST API using the
 *      page's own session cookie + CSRF token
 *   5. the mask is previewed on an overlay; the annotator is refreshed with
 *      ?frame=N on demand (or automatically, if enabled)
 */

(() => {
  'use strict';

  if (window.__cvatSam3Loaded) return;
  window.__cvatSam3Loaded = true;

  const HOST_ID = 'cvat-sam3-host';
  const DEFAULTS = {
    sam3Url: 'http://localhost:58218/',
    timeoutMs: 180000,
    mode: 'point',
    labelId: null,
    autoReload: false,
  };

  const state = {
    cfg: { ...DEFAULTS },
    jobId: null,
    labels: [],
    labelError: '',
    enabled: false,
    busy: false,
    added: 0,
    ui: null,
    drag: null,
    previews: [],
    raf: 0,
    poll: 0,
  };

  /* ------------------------------------------------------------------ *
   * DOM / CVAT helpers
   * ------------------------------------------------------------------ */

  const bgCanvas = () => document.getElementById('cvat_canvas_background');
  const wrapper = () => document.getElementById('cvat_canvas_wrapper');

  function currentJobId() {
    const m = location.pathname.match(/\/jobs\/(\d+)/);
    if (m) return Number(m[1]);
    const q = new URLSearchParams(location.search).get('job');
    return q ? Number(q) : null;
  }

  function currentFrame() {
    const input = document.querySelector('.cvat-player-frame-selector input');
    const v = input ? Number(input.value) : NaN;
    if (Number.isFinite(v)) return v;
    const q = Number(new URLSearchParams(location.search).get('frame'));
    return Number.isFinite(q) ? q : 0;
  }

  function csrfToken() {
    const m =
      document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/) ||
      document.cookie.match(/(?:^|;\s*)csrf=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }

  // client (CSS px) -> image pixel, using the on-screen size of the frame canvas
  function clientToImage(clientX, clientY) {
    const el = bgCanvas();
    if (!el || !el.width || !el.height) return null;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) return null;
    return {
      x: ((clientX - r.left) * el.width) / r.width,
      y: ((clientY - r.top) * el.height) / r.height,
      width: el.width,
      height: el.height,
    };
  }

  /* ------------------------------------------------------------------ *
   * Frame capture
   * ------------------------------------------------------------------ */

  async function captureImage() {
    const el = bgCanvas();
    if (!el) throw new Error('CVAT canvas not found — open a 2D job first.');

    try {
      return { dataUrl: el.toDataURL('image/jpeg', 0.95), width: el.width, height: el.height };
    } catch {
      // Canvas tainted (unusual): re-fetch the frame and draw it at canvas size
      return fetchFrameFallback(el.width, el.height);
    }
  }

  async function fetchFrameFallback(width, height) {
    const res = await fetch(
      `/api/jobs/${state.jobId}/data/?type=frame&number=${currentFrame()}&quality=original`,
      { credentials: 'include' },
    );
    if (!res.ok) throw new Error(`Cannot read frame ${currentFrame()} (HTTP ${res.status}).`);
    const bitmap = await createImageBitmap(await res.blob());

    const c = document.createElement('canvas');
    c.width = width;
    c.height = height;
    c.getContext('2d').drawImage(bitmap, 0, 0, width, height);
    return { dataUrl: c.toDataURL('image/jpeg', 0.95), width, height };
  }

  /* ------------------------------------------------------------------ *
   * SAM 3
   * ------------------------------------------------------------------ */

  function callSam3(payload) {
    return new Promise((resolve, reject) => {
      chrome.runtime.sendMessage(
        { type: 'sam3', url: state.cfg.sam3Url, timeoutMs: state.cfg.timeoutMs, payload },
        (res) => {
          if (chrome.runtime.lastError) {
            reject(new Error(chrome.runtime.lastError.message));
            return;
          }
          if (!res) {
            reject(new Error('No response from the extension background worker.'));
            return;
          }
          if (!res.ok) {
            reject(new Error(res.error));
            return;
          }
          resolve(res.data);
        },
      );
    });
  }

  function extractShapes(data) {
    if (!data) return [];
    if (Array.isArray(data)) return data;
    if (Array.isArray(data.shapes)) return data.shapes;
    if (Array.isArray(data.points)) return [data];
    return [];
  }

  async function segment({ pos = [], neg = [], box = null, prompt = '' }) {
    const { dataUrl, width, height } = await captureImage();
    const payload = {
      image: dataUrl.slice(dataUrl.indexOf(',') + 1),
      pos_points: pos,
      neg_points: neg,
      obj_bbox: box,
    };
    if (prompt) payload.prompt = prompt;

    const data = await callSam3(payload);
    const shapes = extractShapes(data);
    if (!shapes.length) {
      if (prompt) {
        throw new Error(
          'Model returned no shapes. Text prompts need a SAM 3 "concept" handler in the Nuclio function.',
        );
      }
      throw new Error('Model returned no shapes for that prompt.');
    }
    return { shapes, width, height };
  }

  /* ------------------------------------------------------------------ *
   * Labels
   * ------------------------------------------------------------------ */

  async function loadLabels() {
    if (!state.jobId) return;
    try {
      // Note: JobRead.labels is a URL to /api/labels?job_id=N, not an array.
      const res = await fetch(`/api/labels?job_id=${state.jobId}&page_size=1000`, {
        credentials: 'include',
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const all = Array.isArray(data) ? data : data.results || [];
      const maskable = all.filter((l) => ['any', 'mask'].includes(String(l.type || 'any')));
      state.labels = maskable.length ? maskable : all;
      state.labelError = maskable.length
        ? ''
        : 'No label accepts masks. Add a "mask" or "any" label in CVAT.';
    } catch (e) {
      state.labels = [];
      state.labelError = `Cannot read job labels: ${e.message}`;
    }
    renderLabelSelect();
    renderMeta();
  }

  function effectiveLabelId() {
    if (state.cfg.labelId && state.labels.some((l) => l.id === state.cfg.labelId)) {
      return state.cfg.labelId;
    }
    return state.labels.length ? state.labels[0].id : null;
  }

  function labelColor(id) {
    const l = state.labels.find((x) => x.id === id);
    const hex = (l?.color || '#3b82f6').replace('#', '');
    const full = hex.length === 3 ? hex.split('').map((c) => c + c).join('') : hex;
    return [
      parseInt(full.slice(0, 2), 16) || 59,
      parseInt(full.slice(2, 4), 16) || 130,
      parseInt(full.slice(4, 6), 16) || 246,
    ];
  }

  /* ------------------------------------------------------------------ *
   * Writing annotations back to CVAT
   * ------------------------------------------------------------------ */

  async function applyShapes(shapes, imgW, imgH) {
    if (!state.jobId) throw new Error('No job detected in the URL.');
    const labelId = effectiveLabelId();
    if (!labelId) throw new Error(state.labelError || 'No label selected.');

    const frame = currentFrame();
    const body = {
      shapes: shapes
        .filter((s) => Array.isArray(s.points) && s.points.length > 4)
        .map((s) => ({
          type: s.type || 'mask',
          frame,
          label_id: labelId,
          occluded: false,
          outside: false,
          z_order: 0,
          group: 0,
          rotation: 0,
          source: 'semi-auto',
          attributes: Array.isArray(s.attributes) ? s.attributes : [],
          points: s.points,
        })),
    };
    if (!body.shapes.length) throw new Error('Model returned no usable mask.');

    const res = await fetch(`/api/jobs/${state.jobId}/annotations/?action=create`, {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
      body: JSON.stringify(body),
    });

    const text = await res.text();
    if (!res.ok) {
      throw new Error(`CVAT rejected the update (HTTP ${res.status}): ${text.slice(0, 300)}`);
    }

    const color = labelColor(labelId);
    for (const s of body.shapes) drawMaskPreview(s.points, imgW, imgH, color);
    state.added += body.shapes.length;
    renderMeta();

    if (state.cfg.autoReload) scheduleReload();
  }

  // CVAT mask RLE: run lengths (starting with a background run) then the mask
  // bounding box as [left, top, right, bottom].
  function drawMaskPreview(points, fallbackW, fallbackH, color) {
    const ui = state.ui;
    if (!ui) return;

    const el = bgCanvas();
    const w = el ? el.width : fallbackW;
    const h = el ? el.height : fallbackH;
    if (!w || !h) return;

    const ov = ui.overlay;
    if (ov.width !== w || ov.height !== h) {
      ov.width = w;
      ov.height = h;
    }
    const ctx = ov.getContext('2d');

    const bbox = points.slice(-4);
    let left;
    let top;
    let right;
    let bottom;
    if (bbox.length === 4 && points.length > 4 && bbox[2] >= bbox[0] && bbox[3] >= bbox[1]) {
      [left, top, right, bottom] = bbox.map((n) => Math.round(n));
    } else {
      left = 0;
      top = 0;
      right = w - 1;
      bottom = h - 1;
    }

    const rle = points.slice(0, points.length - 4);
    const mw = right - left + 1;
    const mh = bottom - top + 1;
    if (mw <= 0 || mh <= 0) return;

    const total = mw * mh;
    const img = ctx.createImageData(mw, mh);
    const data = img.data;
    const [r, g, b] = color;

    let idx = 0;
    let on = 0;
    for (let i = 0; i < rle.length && idx < total; i += 1) {
      const count = Number(rle[i]);
      if (!Number.isFinite(count) || count <= 0) {
        on ^= 1;
        continue;
      }
      const end = Math.min(total, idx + count);
      if (on) {
        for (let p = idx; p < end; p += 1) {
          const o = p * 4;
          data[o] = r;
          data[o + 1] = g;
          data[o + 2] = b;
          data[o + 3] = 110;
        }
      }
      idx = end;
      on ^= 1;
    }

    ctx.putImageData(img, left, top);
    state.previews.push({ left, top, width: mw, height: mh });
    startSync();
  }

  /* ------------------------------------------------------------------ *
   * Overlay positioning
   * ------------------------------------------------------------------ */

  function syncOverlay() {
    const ov = state.ui?.overlay;
    const el = bgCanvas();
    if (!ov || !el) return;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) return;

    const style = ov.style;
    const left = `${r.left}px`;
    const top = `${r.top}px`;
    const width = `${r.width}px`;
    const height = `${r.height}px`;
    if (style.left !== left) style.left = left;
    if (style.top !== top) style.top = top;
    if (style.width !== width) style.width = width;
    if (style.height !== height) style.height = height;
  }

  function startSync() {
    if (state.raf) return;
    const tick = () => {
      state.raf = requestAnimationFrame(tick);
      syncOverlay();
    };
    state.raf = requestAnimationFrame(tick);
  }

  function stopSync() {
    if (!state.raf) return;
    cancelAnimationFrame(state.raf);
    state.raf = 0;
  }

  function clearPreview() {
    const ov = state.ui?.overlay;
    if (ov) ov.getContext('2d').clearRect(0, 0, ov.width, ov.height);
    state.previews = [];
    if (!state.enabled) stopSync();
  }

  /* ------------------------------------------------------------------ *
   * UI
   * ------------------------------------------------------------------ */

  const STYLE = `
    :host { all: initial; }
    * { box-sizing: border-box; }
    .ov {
      position: fixed; left: 0; top: 0; width: 0; height: 0;
      pointer-events: none; z-index: 0; image-rendering: auto;
    }
    .drag {
      position: fixed; display: none; pointer-events: none; z-index: 1;
      border: 1px solid #22d3ee; background: rgba(34, 211, 238, .15);
      box-shadow: 0 0 0 1px rgba(0,0,0,.5);
    }
    .card {
      position: fixed; left: 16px; bottom: 110px; width: 256px;
      z-index: 2; pointer-events: auto;
      background: #171a21; color: #e7e9ee;
      border: 1px solid #333a48; border-radius: 10px;
      box-shadow: 0 10px 30px rgba(0,0,0,.5);
      font: 12px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
      overflow: hidden;
    }
    .hdr {
      display: flex; align-items: center; gap: 8px;
      padding: 8px 10px; background: #1f232c; border-bottom: 1px solid #333a48;
      cursor: grab; user-select: none; touch-action: none;
    }
    .hdr.dragging { cursor: grabbing; }
    .hdr .title { font-weight: 600; letter-spacing: .2px; flex: 1; }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: #6b7280; }
    .dot.on { background: #22c55e; box-shadow: 0 0 6px #22c55e; }
    .dot.busy { background: #f59e0b; animation: pulse 1s infinite; }
    @keyframes pulse { 50% { opacity: .35; } }
    .sw { display: flex; align-items: center; gap: 5px; cursor: pointer; user-select: none; }
    .sw input { accent-color: #22c55e; margin: 0; }
    .body { padding: 9px 10px 10px; display: grid; gap: 7px; }
    .row { display: flex; gap: 6px; align-items: center; }
    .muted { color: #97a0b0; font-size: 11px; }
    #meta { justify-content: space-between; }
    select, input[type="text"], button {
      font: inherit; color: inherit; border-radius: 6px; border: 1px solid #3a4252;
      background: #232833; padding: 5px 7px; outline: none;
    }
    select { flex: 1; min-width: 0; }
    input[type="text"] { flex: 1; min-width: 0; }
    button { cursor: pointer; white-space: nowrap; }
    button:hover { background: #2c3341; }
    button:disabled { opacity: .45; cursor: default; }
    .seg { display: flex; }
    .seg button { flex: 1; border-radius: 0; }
    .seg button:first-child { border-radius: 6px 0 0 6px; }
    .seg button:last-child { border-radius: 0 6px 6px 0; border-left: none; }
    .seg button.on { background: #2563eb; border-color: #2563eb; color: #fff; }
    .warn { color: #fbbf24; font-size: 11px; }
    .toast {
      position: fixed; left: 50%; bottom: 140px; transform: translateX(-50%);
      max-width: 60vw; padding: 7px 12px; border-radius: 8px;
      background: #0f172a; color: #e7e9ee; border: 1px solid #334155;
      font: 12px/1.4 system-ui, sans-serif; pointer-events: none; z-index: 3;
      opacity: 0; transition: opacity .15s;
    }
    .toast.show { opacity: 1; }
    .toast.err { border-color: #b91c1c; background: #26141a; color: #fecaca; }
  `;

  function ensurePanel() {
    if (state.ui) return state.ui;
    if (!document.body) return null;

    const host = document.createElement('div');
    host.id = HOST_ID;
    host.style.cssText =
      'position:fixed;inset:0;pointer-events:none;z-index:2147483000;';
    const root = host.attachShadow({ mode: 'open' });

    const style = document.createElement('style');
    style.textContent = STYLE;

    const ov = document.createElement('canvas');
    ov.className = 'ov';

    const drag = document.createElement('div');
    drag.className = 'drag';

    const card = document.createElement('div');
    card.className = 'card';
    card.innerHTML = `
      <div class="hdr">
        <span class="dot"></span>
        <span class="title">SAM 3</span>
        <label class="sw"><input type="checkbox"><span>On</span></label>
      </div>
      <div class="body">
        <div class="row muted" id="meta"><span>job —</span><span>frame —</span></div>
        <div class="row"><select data-k="label" title="Label for new masks"></select></div>
        <div class="row seg">
          <button data-mode="point" class="on">Point</button>
          <button data-mode="box">Box</button>
        </div>
        <div class="row">
          <input type="text" data-k="prompt" placeholder="text prompt (concept)">
          <button data-k="detect" title="Segment everything matching the prompt">All</button>
        </div>
        <div class="row">
          <button data-k="clear">Clear</button>
          <button data-k="save" title="Save CVAT's own unsaved changes (same as Ctrl+S)">Save</button>
          <button data-k="reload" title="Reload the annotator to show saved shapes">Reload view</button>
        </div>
        <div class="row muted" id="hint">Alt+S to toggle · click = positive · Shift+click = negative</div>
        <div class="row muted" id="status"></div>
      </div>`;

    const toast = document.createElement('div');
    toast.className = 'toast';

    root.append(style, ov, drag, card, toast);
    document.body.appendChild(host);

    state.ui = {
      host,
      root,
      overlay: ov,
      drag,
      card,
      toast,
      dot: card.querySelector('.dot'),
      toggle: card.querySelector('.sw input'),
      labelSelect: card.querySelector('select[data-k="label"]'),
      prompt: card.querySelector('input[data-k="prompt"]'),
      meta: card.querySelector('#meta'),
      hint: card.querySelector('#hint'),
      status: card.querySelector('#status'),
      modeButtons: [...card.querySelectorAll('.seg button')],
      clear: card.querySelector('button[data-k="clear"]'),
      save: card.querySelector('button[data-k="save"]'),
      reload: card.querySelector('button[data-k="reload"]'),
      detect: card.querySelector('button[data-k="detect"]'),
    };

    wirePanel(state.ui);
    makeDraggable(state.ui);
    applyPanelPos();
    renderMeta();
    renderLabelSelect();
    renderMode();
    syncOverlay();
    return state.ui;
  }

  /* ------------------------------------------------------------------ *
   * Panel dragging
   * ------------------------------------------------------------------ */

  const PANEL_MARGIN = 8;

  function clampPanelPos(x, y, card) {
    const w = card.offsetWidth || 256;
    const h = card.offsetHeight || 220;
    const maxX = Math.max(PANEL_MARGIN, window.innerWidth - w - PANEL_MARGIN);
    const maxY = Math.max(PANEL_MARGIN, window.innerHeight - h - PANEL_MARGIN);
    return {
      x: Math.min(Math.max(PANEL_MARGIN, Math.round(x)), maxX),
      y: Math.min(Math.max(PANEL_MARGIN, Math.round(y)), maxY),
    };
  }

  function applyPanelPos() {
    const card = state.ui?.card;
    if (!card) return;

    const saved = state.cfg.panelPos;
    let x;
    let y;
    if (saved && Number.isFinite(saved.x) && Number.isFinite(saved.y)) {
      x = saved.x;
      y = saved.y;
    } else {
      x = 16;
      y = window.innerHeight - 110 - card.offsetHeight;
    }
    setPanelPos(x, y);
  }

  function setPanelPos(x, y) {
    const card = state.ui?.card;
    if (!card) return;
    const p = clampPanelPos(x, y, card);
    card.style.left = `${p.x}px`;
    card.style.top = `${p.y}px`;
    card.style.bottom = 'auto';
  }

  function reclampPanel() {
    const card = state.ui?.card;
    if (!card) return;
    const r = card.getBoundingClientRect();
    setPanelPos(r.left, r.top);
  }

  function makeDraggable(ui) {
    const { card } = ui;
    const hdr = card.querySelector('.hdr');
    let drag = null;

    hdr.addEventListener('pointerdown', (e) => {
      if (e.button !== 0) return;
      if (e.target.closest('.sw')) return; // let the toggle be clicked
      const r = card.getBoundingClientRect();
      drag = { dx: e.clientX - r.left, dy: e.clientY - r.top, moved: false };
      hdr.classList.add('dragging');
      try {
        hdr.setPointerCapture(e.pointerId);
      } catch {
        /* ignore */
      }
      e.preventDefault();
    });

    hdr.addEventListener('pointermove', (e) => {
      if (!drag) return;
      const p = clampPanelPos(e.clientX - drag.dx, e.clientY - drag.dy, card);
      card.style.left = `${p.x}px`;
      card.style.top = `${p.y}px`;
      card.style.bottom = 'auto';
      drag.moved = true;
    });

    const finish = (e) => {
      if (!drag) return;
      hdr.classList.remove('dragging');
      try {
        hdr.releasePointerCapture(e.pointerId);
      } catch {
        /* ignore */
      }
      if (drag.moved) {
        const r = card.getBoundingClientRect();
        state.cfg.panelPos = { x: Math.round(r.left), y: Math.round(r.top) };
        saveCfg();
      }
      drag = null;
    };

    hdr.addEventListener('pointerup', finish);
    hdr.addEventListener('pointercancel', finish);
  }

  function wirePanel(ui) {
    ui.toggle.addEventListener('change', () => setEnabled(ui.toggle.checked));

    for (const btn of ui.modeButtons) {
      btn.addEventListener('click', () => {
        state.cfg.mode = btn.dataset.mode;
        saveCfg();
        renderMode();
      });
    }

    ui.labelSelect.addEventListener('change', () => {
      state.cfg.labelId = Number(ui.labelSelect.value) || null;
      saveCfg();
    });

    ui.clear.addEventListener('click', () => {
      clearPreview();
      state.added = 0;
      renderMeta();
    });

    ui.reload.addEventListener('click', reloadView);
    ui.save.addEventListener('click', saveAnnotations);

    ui.detect.addEventListener('click', async () => {
      const prompt = ui.prompt.value.trim();
      if (!prompt) {
        toast('Type a text prompt first.', true);
        return;
      }
      await runBusy(async () => {
        const { shapes, width, height } = await segment({ prompt });
        await applyShapes(shapes, width, height);
        toast(`${shapes.length} object(s) added.`);
      });
    });
  }

  function renderMode() {
    const ui = state.ui;
    if (!ui) return;
    for (const btn of ui.modeButtons) btn.classList.toggle('on', btn.dataset.mode === state.cfg.mode);
  }

  function renderLabelSelect() {
    const ui = state.ui;
    if (!ui) return;
    const sel = ui.labelSelect;
    sel.innerHTML = '';
    if (!state.labels.length) {
      const o = document.createElement('option');
      o.textContent = state.labelError || 'no labels';
      o.value = '';
      sel.appendChild(o);
      sel.disabled = true;
      return;
    }
    sel.disabled = false;
    for (const l of state.labels) {
      const o = document.createElement('option');
      o.value = String(l.id);
      o.textContent = l.name;
      sel.appendChild(o);
    }
    sel.value = String(effectiveLabelId());
  }

  function renderMeta() {
    const ui = state.ui;
    if (!ui) return;
    ui.meta.innerHTML = '';
    const a = document.createElement('span');
    a.textContent = state.jobId ? `job ${state.jobId}` : 'no job';
    const b = document.createElement('span');
    b.textContent = `frame ${currentFrame()} · +${state.added}`;
    ui.meta.append(a, b);
  }

  function setStatus(text, isError = false) {
    const ui = state.ui;
    if (!ui) return;
    ui.status.textContent = text || '';
    ui.status.className = isError ? 'row warn' : 'row muted';
  }

  let toastTimer = 0;
  function toast(text, isError = false) {
    const ui = state.ui;
    if (!ui) return;
    ui.toast.textContent = text;
    ui.toast.className = `toast show${isError ? ' err' : ''}`;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      ui.toast.className = 'toast';
    }, isError ? 7000 : 3000);
  }

  function refreshDot() {
    const ui = state.ui;
    if (!ui) return;
    ui.dot.className = `dot${state.busy ? ' busy' : state.enabled ? ' on' : ''}`;
    ui.toggle.checked = state.enabled;
    const w = wrapper();
    if (w) w.style.cursor = state.enabled ? 'crosshair' : '';
  }

  function setEnabled(value) {
    state.enabled = value;
    refreshDot();
    if (value) {
      ensurePanel();
      startSync();
      setStatus('Click the image to segment.');
    } else {
      cancelDrag();
      if (!state.previews.length) stopSync();
      setStatus('');
    }
  }

  async function runBusy(fn) {
    if (state.busy) return;
    state.busy = true;
    refreshDot();
    setStatus('Running SAM 3…');
    try {
      await fn();
      setStatus('');
    } catch (e) {
      toast(e.message || String(e), true);
      setStatus('');
    } finally {
      state.busy = false;
      refreshDot();
    }
  }

  /* ------------------------------------------------------------------ *
   * Canvas interaction
   * ------------------------------------------------------------------ */

  function insideCanvas(target) {
    const w = wrapper();
    return !!(w && target instanceof Node && w.contains(target));
  }

  function onMouseDown(e) {
    if (!state.enabled || state.busy) return;
    if (e.button !== 0 || e.altKey || e.ctrlKey || e.metaKey) return;
    if (!insideCanvas(e.target)) return;

    const p = clientToImage(e.clientX, e.clientY);
    if (!p) return;

    e.preventDefault();
    e.stopPropagation();
    e.stopImmediatePropagation();

    state.drag = {
      startX: e.clientX,
      startY: e.clientY,
      startImg: p,
      moved: false,
    };
    if (state.cfg.mode === 'box') updateDragRect(e.clientX, e.clientY);
  }

  function onMouseMove(e) {
    const d = state.drag;
    if (!d) return;
    if (Math.abs(e.clientX - d.startX) > 4 || Math.abs(e.clientY - d.startY) > 4) d.moved = true;
    if (state.cfg.mode === 'box' && d.moved) updateDragRect(e.clientX, e.clientY);
  }

  function onMouseUp(e) {
    const d = state.drag;
    if (!d) return;
    state.drag = null;
    hideDragRect();

    if (e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    e.stopImmediatePropagation();

    const end = clientToImage(e.clientX, e.clientY);
    if (!end) return;

    const isBox = state.cfg.mode === 'box' && d.moved;
    if (isBox) {
      const box = [
        [Math.min(d.startImg.x, end.x), Math.min(d.startImg.y, end.y)],
        [Math.max(d.startImg.x, end.x), Math.max(d.startImg.y, end.y)],
      ];
      if (box[1][0] - box[0][0] < 3 || box[1][1] - box[0][1] < 3) return;
      runBusy(async () => {
        const { shapes, width, height } = await segment({ box });
        await applyShapes(shapes, width, height);
        toast('1 object added.');
      });
      return;
    }

    if (d.moved) return; // a pan/drag attempt: ignore
    const negative = e.shiftKey;
    const pt = [round2(d.startImg.x), round2(d.startImg.y)];
    runBusy(async () => {
      const { shapes, width, height } = await segment(
        negative ? { neg: [pt] } : { pos: [pt] },
      );
      await applyShapes(shapes, width, height);
      toast('1 object added.');
    });
  }

  function updateDragRect(x, y) {
    const d = state.drag;
    const el = state.ui?.drag;
    if (!d || !el) return;
    el.style.display = 'block';
    el.style.left = `${Math.min(d.startX, x)}px`;
    el.style.top = `${Math.min(d.startY, y)}px`;
    el.style.width = `${Math.abs(x - d.startX)}px`;
    el.style.height = `${Math.abs(y - d.startY)}px`;
  }

  function hideDragRect() {
    if (state.ui?.drag) state.ui.drag.style.display = 'none';
  }

  function cancelDrag() {
    state.drag = null;
    hideDragRect();
  }

  const round2 = (n) => Math.round(n * 100) / 100;

  function onKeyDown(e) {
    if (e.key === 'Escape') {
      cancelDrag();
      return;
    }
    if (e.altKey && !e.ctrlKey && !e.metaKey && (e.key === 's' || e.key === 'S')) {
      const tag = (e.target?.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea' || e.target?.isContentEditable) return;
      e.preventDefault();
      setEnabled(!state.enabled);
    }
  }

  /* ------------------------------------------------------------------ *
   * Config / lifecycle
   * ------------------------------------------------------------------ */

  function saveCfg() {
    chrome.storage.local.set({ cfg: state.cfg });
  }

  function reloadView() {
    const url = new URL(location.href);
    url.searchParams.set('frame', String(currentFrame()));
    location.href = url.toString();
  }

  // Masks produced by the extension are already stored through the API, so this
  // only flushes shapes edited inside CVAT itself (what Ctrl+S does), e.g. before
  // pressing "Reload view".
  const SAVE_SELECTORS = [
    'button.cvat-annotation-header-save-button',
    'button.cvat-save-annotations-button',
    '[data-testid="save-annotations-button"]',
  ];

  function findCvatSaveButton() {
    for (const sel of SAVE_SELECTORS) {
      const el = document.querySelector(sel);
      if (el) return el;
    }
    return null;
  }

  function cvatIsSaving(btn) {
    if (!btn) return false;
    return /saving/i.test(btn.textContent || '') || /\bdisabled\b/.test(btn.className);
  }

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  async function saveAnnotations() {
    const btn = findCvatSaveButton();

    if (btn) {
      if (cvatIsSaving(btn)) {
        toast('CVAT is already saving…');
        return;
      }
      btn.click();
    } else {
      // Fallback: CVAT binds Ctrl+S through mousetrap on the document.
      const init = {
        key: 's',
        code: 'KeyS',
        keyCode: 83,
        which: 83,
        ctrlKey: true,
        bubbles: true,
        cancelable: true,
      };
      document.dispatchEvent(new KeyboardEvent('keydown', init));
      document.dispatchEvent(new KeyboardEvent('keyup', init));
    }

    // Wait for the upload to actually finish, otherwise the toast lies.
    const started = performance.now();
    let sawSaving = false;
    for (;;) {
      await sleep(200);
      const busy = cvatIsSaving(findCvatSaveButton());
      if (busy) sawSaving = true;
      if (sawSaving && !busy) break;

      const elapsed = performance.now() - started;
      if (!sawSaving && elapsed > 2500) break;
      if (elapsed > 60000) {
        toast('CVAT is still saving — check the top bar.', true);
        return;
      }
    }

    toast('Annotations saved.');
  }

  let reloadTimer = 0;
  function scheduleReload() {
    clearTimeout(reloadTimer);
    reloadTimer = setTimeout(reloadView, 1200);
  }

  async function syncJob() {
    const jobId = currentJobId();
    if (jobId === state.jobId) return;
    state.jobId = jobId;
    state.added = 0;
    clearPreview();
    if (jobId) await loadLabels();
    else {
      state.labels = [];
      state.labelError = 'Open a job to start.';
      renderLabelSelect();
    }
    renderMeta();
  }

  async function boot() {
    const { cfg } = await chrome.storage.local.get(['cfg']);
    state.cfg = { ...DEFAULTS, ...(cfg || {}) };

    ensurePanel();
    await syncJob();
    refreshDot();
    renderMode();

    document.addEventListener('mousedown', onMouseDown, true);
    document.addEventListener('mousemove', onMouseMove, true);
    document.addEventListener('mouseup', onMouseUp, true);
    document.addEventListener('keydown', onKeyDown, true);
    window.addEventListener('resize', () => {
      reclampPanel();
      syncOverlay();
    });

    state.poll = setInterval(async () => {
      if (!state.ui) ensurePanel();
      renderMeta();
      await syncJob();
    }, 1500);

    chrome.storage.onChanged.addListener((changes, area) => {
      if (area !== 'local' || !changes.cfg) return;
      state.cfg = { ...DEFAULTS, ...(changes.cfg.newValue || {}) };
      renderMode();
    });
  }

  boot();
})();
