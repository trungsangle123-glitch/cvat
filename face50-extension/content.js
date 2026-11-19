/* CVAT Face Landmark-50 — content script.
 *
 * Runs inside the CVAT annotation page and only uses public surfaces:
 *
 *   1. current frame pixels come from #cvat_canvas_background
 *      (cvat-data sizes that canvas to the source resolution)
 *   2. the frame is POSTed to the self-hosted model (through the service
 *      worker, so CORS does not apply)
 *   3. the 7 skeletons / 50 points are PATCHed into the job with the page's
 *      own session cookie + CSRF token
 *   4. points are previewed on an overlay: green = visible, orange = occluded,
 *      red = outside (guideline section 3)
 *
 * The 7 skeleton labels must already exist in the task (see labels_raw.json).
 */

(() => {
  'use strict';

  if (window.__cvatFace50Loaded) return;
  window.__cvatFace50Loaded = true;

  const HOST_ID = 'cvat-face50-host';
  const STORE_CFG = 'face50Cfg';
  const STORE_POS = 'face50PanelPos';

  // Guideline section 2: 7 skeletons, 50 points, ids never reset.
  const SCHEMA = [
    { name: 'longmaytrai', first: 0, count: 5, closed: false },
    { name: 'longmayphai', first: 5, count: 5, closed: false },
    { name: 'songmui', first: 10, count: 4, closed: false },
    { name: 'mattrai', first: 14, count: 8, closed: true },
    { name: 'matphai', first: 22, count: 8, closed: true },
    { name: 'moingoai', first: 30, count: 12, closed: true },
    { name: 'moitrong', first: 42, count: 8, closed: true },
  ];

  const DEFAULT_CFG = {
    endpoint: 'http://localhost:58219/predict',
    timeoutMs: 120000,
    replace: false,
    previewOnly: false,
    showIds: false,
    groups: Object.fromEntries(SCHEMA.map((s) => [s.name, true])),
  };

  const STATE_COLOR = {
    visible: '#22c55e',
    occluded: '#f59e0b',
    outside: '#ef4444',
  };

  const state = {
    cfg: { ...DEFAULT_CFG, groups: { ...DEFAULT_CFG.groups } },
    jobId: null,
    frame: null,
    jobMeta: null,
    labels: [],          // skeleton labels of the job
    labelMap: {},        // name -> { id, color, sublabels: Map<pointId, labelId> }
    labelsError: '',
    prediction: null,
    busy: false,
    batch: null,
    added: 0,
    ui: null,
    raf: 0,
    poll: 0,
  };

  /* ------------------------------------------------------------------ *
   * CVAT page helpers
   * ------------------------------------------------------------------ */

  const bgCanvas = () => document.getElementById('cvat_canvas_background');

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

  function parsePointId(name) {
    const m = String(name || '').match(/(\d+)(?!.*\d)/);
    return m ? Number(m[1]) : null;
  }

  function hexToRgb(hex, fallback = [59, 130, 246]) {
    const clean = String(hex || '').replace('#', '');
    if (!/^[0-9a-f]{6}$/i.test(clean)) return fallback;
    return [parseInt(clean.slice(0, 2), 16), parseInt(clean.slice(2, 4), 16), parseInt(clean.slice(4, 6), 16)];
  }

  /* ------------------------------------------------------------------ *
   * Labels
   * ------------------------------------------------------------------ */

  async function loadLabels() {
    if (!state.jobId) return;
    try {
      const res = await fetch(`/api/labels?job_id=${state.jobId}&page_size=1000`, {
        credentials: 'include',
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const all = Array.isArray(data) ? data : data.results || [];
      state.labels = all.filter((l) => String(l.type) === 'skeleton');
      state.labelsError = '';
    } catch (e) {
      state.labels = [];
      state.labelsError = `Cannot read job labels: ${e.message}`;
    }

    state.labelMap = {};
    for (const schema of SCHEMA) {
      const label = state.labels.find((l) => l.name === schema.name);
      if (!label) continue;
      const sublabels = new Map();
      for (const sub of label.sublabels || []) {
        const pid = parsePointId(sub.name);
        if (pid !== null && !sublabels.has(pid)) sublabels.set(pid, sub.id);
      }
      state.labelMap[schema.name] = {
        id: label.id,
        color: label.color,
        sublabels,
        complete: schema.count === [...sublabels.keys()]
          .filter((id) => id >= schema.first && id < schema.first + schema.count).length,
      };
    }

    renderMeta();
    renderLabelStatus();
  }

  function missingLabels() {
    return SCHEMA.filter((s) => !state.labelMap[s.name]).map((s) => s.name);
  }

  function incompleteLabels() {
    return SCHEMA.filter((s) => state.labelMap[s.name] && !state.labelMap[s.name].complete)
      .map((s) => s.name);
  }

  async function loadJobMeta() {
    if (!state.jobId) return;
    try {
      const res = await fetch(`/api/jobs/${state.jobId}`, { credentials: 'include' });
      if (res.ok) state.jobMeta = await res.json();
    } catch {
      state.jobMeta = null;
    }
    const from = state.jobMeta?.start_frame ?? 0;
    const to = state.jobMeta?.stop_frame ?? 0;
    if (state.ui) {
      state.ui.from.value = String(from);
      state.ui.to.value = String(to);
    }
  }

  /* ------------------------------------------------------------------ *
   * Frame capture
   * ------------------------------------------------------------------ */

  function canvasToImage(el) {
    const c = document.createElement('canvas');
    c.width = el.width;
    c.height = el.height;
    c.getContext('2d').drawImage(el, 0, 0);
    return { image: c.toDataURL('image/jpeg', 0.95), width: c.width, height: c.height };
  }

  async function frameFromCanvas() {
    const el = bgCanvas();
    if (!el || !el.width || !el.height) throw new Error('CVAT canvas not found — open a 2D job first.');
    try {
      return { image: el.toDataURL('image/jpeg', 0.95), width: el.width, height: el.height };
    } catch {
      return frameFromApi(currentFrame());
    }
  }

  async function frameFromApi(number) {
    const res = await fetch(
      `/api/jobs/${state.jobId}/data/?type=frame&number=${number}&quality=original`,
      { credentials: 'include' },
    );
    if (!res.ok) throw new Error(`Cannot read frame ${number} (HTTP ${res.status})`);
    const bitmap = await createImageBitmap(await res.blob());
    const c = document.createElement('canvas');
    c.width = bitmap.width;
    c.height = bitmap.height;
    c.getContext('2d').drawImage(bitmap, 0, 0);
    bitmap.close?.();
    return { image: c.toDataURL('image/jpeg', 0.95), width: c.width, height: c.height };
  }

  async function getFrameImage(number, batch) {
    if (!batch && number === currentFrame()) return frameFromCanvas();
    return frameFromApi(number);
  }

  /* ------------------------------------------------------------------ *
   * Model call
   * ------------------------------------------------------------------ */

  function callModel(image) {
    return new Promise((resolve, reject) => {
      chrome.runtime.sendMessage(
        { type: 'face50', url: state.cfg.endpoint, timeoutMs: state.cfg.timeoutMs, payload: { image } },
        (res) => {
          if (chrome.runtime.lastError) {
            reject(new Error(chrome.runtime.lastError.message));
            return;
          }
          if (!res) {
            reject(new Error('No response from the extension background worker.'));
            return;
          }
          if (!res.ok) reject(new Error(res.error || 'Model request failed'));
          else resolve(res.data);
        },
      );
    });
  }

  /* ------------------------------------------------------------------ *
   * Write to CVAT
   * ------------------------------------------------------------------ */

  function buildShapes(result, frameNo) {
    const shapes = [];
    const warnings = [...(result.warnings || [])];
    let points = 0;

    for (const sk of result.skeletons) {
      if (!state.cfg.groups[sk.name]) continue;
      const label = state.labelMap[sk.name];
      if (!label) {
        warnings.push(`no label for ${sk.name}`);
        continue;
      }

      const elements = [];
      for (const p of sk.points) {
        const sublabelId = label.sublabels.get(p.id);
        if (!sublabelId) continue;
        elements.push({
          type: 'points',
          frame: frameNo,
          label_id: sublabelId,
          points: [p.x, p.y],
          occluded: p.state === 'occluded',
          outside: p.state === 'outside',
          z_order: 0,
          group: 0,
          rotation: 0,
          source: 'manual',
          attributes: [],
        });
      }
      const expected = SCHEMA.find((s) => s.name === sk.name)?.count ?? 0;
      if (elements.length !== expected) {
        warnings.push(`${sk.name}: ${elements.length}/${expected} sublabels matched`);
      }
      if (!elements.length) continue;

      points += elements.length;
      shapes.push({
        type: 'skeleton',
        frame: frameNo,
        label_id: label.id,
        points: [],
        occluded: elements.every((e) => e.occluded),
        outside: elements.every((e) => e.outside),
        z_order: 0,
        group: 0,
        rotation: 0,
        source: 'manual',
        attributes: [],
        elements,
      });
    }

    return { shapes, warnings, points };
  }

  async function managedShapeIds() {
    return new Set(Object.values(state.labelMap).map((l) => l.id));
  }

  async function deleteManagedShapes(frameNo) {
    const res = await fetch(`/api/jobs/${state.jobId}/annotations/`, { credentials: 'include' });
    if (!res.ok) throw new Error(`Cannot read annotations (HTTP ${res.status})`);
    const data = await res.json();
    const ids = await managedShapeIds();
    const doomed = (data.shapes || []).filter(
      (s) => s.frame === frameNo && s.type === 'skeleton' && ids.has(s.label_id),
    );
    if (!doomed.length) return 0;

    const del = await fetch(`/api/jobs/${state.jobId}/annotations/?action=delete`, {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
      body: JSON.stringify({ shapes: doomed }),
    });
    const text = await del.text();
    if (!del.ok) throw new Error(`CVAT rejected the delete (HTTP ${del.status}): ${text.slice(0, 300)}`);
    return doomed.length;
  }

  async function writeShapes(shapes, frameNo) {
    if (!shapes.length) throw new Error('Nothing to write (no enabled skeleton or no matched sublabel).');
    if (!state.jobId) throw new Error('No job detected in the URL.');

    if (state.cfg.replace) await deleteManagedShapes(frameNo);

    const res = await fetch(`/api/jobs/${state.jobId}/annotations/?action=create`, {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
      body: JSON.stringify({ shapes }),
    });
    const text = await res.text();
    if (!res.ok) throw new Error(`CVAT rejected the shapes (HTTP ${res.status}): ${text.slice(0, 300)}`);
    state.added += shapes.length;
  }

  /* CVAT's own "Save" (top bar). Only needed for manual edits made in CVAT -
   * shapes written by this extension are already persisted over REST.
   * CVAT 2.x renders it as <button class="cvat-annotation-header-save-button">
   * with the text "Save"; the other selectors cover older/alternate builds. */
  const SAVE_SELECTORS = [
    '.cvat-annotation-header-save-button',
    '.cvat-save-annotations-button',
    '[data-testid="save-annotations-button"]',
    'button[aria-label="Save annotations"]',
  ];

  function findSaveButton() {
    for (const sel of SAVE_SELECTORS) {
      const btn = document.querySelector(sel);
      if (btn && btn.offsetParent) return btn;
    }
    const candidates = [...document.querySelectorAll('button')];
    return candidates.find((btn) => btn.offsetParent && /^\s*save\s*$/i.test(btn.textContent || '')) || null;
  }

  async function saveInCvat() {
    const btn = findSaveButton();
    if (btn) {
      if (btn.disabled) {
        toast('CVAT is already saving - wait a moment.');
        return;
      }
      btn.click();
      toast('Clicked CVAT "Save".');
      return;
    }
    // Last resort: CVAT binds Ctrl+S through the page's shortcut handler.
    document.dispatchEvent(new KeyboardEvent('keydown', {
      key: 's', code: 'KeyS', ctrlKey: true, bubbles: true, cancelable: true,
    }));
    toast('Save button not found - sent Ctrl+S to CVAT. If nothing happens, press Ctrl+S.', true);
  }

  function reloadView() {
    const url = new URL(location.href);
    url.searchParams.set('frame', String(currentFrame()));
    location.href = url.toString();
  }

  /* ------------------------------------------------------------------ *
   * Preview overlay
   * ------------------------------------------------------------------ */

  function ensureOverlay(w, h) {
    const ui = state.ui;
    if (!ui) return null;
    const ov = ui.overlay;
    if (ov.width !== w || ov.height !== h) {
      ov.width = w;
      ov.height = h;
    }
    return ov.getContext('2d');
  }

  function drawPrediction(result) {
    const el = bgCanvas();
    if (!el || !state.ui) return;
    const ctx = ensureOverlay(el.width, el.height);
    if (!ctx) return;
    ctx.clearRect(0, 0, el.width, el.height);

    const kx = el.width / (result.width || el.width);
    const ky = el.height / (result.height || el.height);
    const lw = Math.max(1, Math.round(el.width / 900));
    const radius = Math.max(2, Math.round(el.width / 500));

    for (const sk of result.skeletons) {
      if (!state.cfg.groups[sk.name]) continue;
      const pts = sk.points.map((p) => [p.x * kx, p.y * ky]);
      if (!pts.length) continue;
      ctx.beginPath();
      pts.forEach(([x, y], i) => (i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)));
      if (sk.closed) ctx.closePath();
      ctx.strokeStyle = 'rgba(0,0,0,.55)';
      ctx.lineWidth = lw + 2;
      ctx.stroke();
      ctx.strokeStyle = 'rgba(34,211,238,.95)';
      ctx.lineWidth = lw;
      ctx.stroke();
    }

    ctx.font = `${Math.max(9, radius * 3)}px system-ui, sans-serif`;
    ctx.textBaseline = 'bottom';
    for (const sk of result.skeletons) {
      if (!state.cfg.groups[sk.name]) continue;
      for (const p of sk.points) {
        const x = p.x * kx;
        const y = p.y * ky;
        ctx.beginPath();
        ctx.arc(x, y, radius, 0, Math.PI * 2);
        ctx.fillStyle = STATE_COLOR[p.state] || '#fff';
        ctx.fill();
        ctx.lineWidth = 1;
        ctx.strokeStyle = 'rgba(0,0,0,.8)';
        ctx.stroke();
        if (state.cfg.showIds) {
          ctx.fillStyle = 'rgba(255,255,255,.95)';
          ctx.fillText(String(p.id), x + radius + 1, y - radius);
        }
      }
    }
  }

  function clearPreview() {
    const ui = state.ui;
    if (!ui) return;
    ui.overlay.getContext('2d').clearRect(0, 0, ui.overlay.width, ui.overlay.height);
    state.prediction = null;
  }

  function positionCanvas(canvas, r) {
    const s = canvas.style;
    s.left = `${r.left}px`;
    s.top = `${r.top}px`;
    s.width = `${r.width}px`;
    s.height = `${r.height}px`;
  }

  function syncOverlay() {
    const ui = state.ui;
    const el = bgCanvas();
    if (!ui || !el) return;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) return;
    positionCanvas(ui.overlay, r);
  }

  function startSync() {
    if (state.raf) return;
    const tick = () => {
      state.raf = requestAnimationFrame(tick);
      syncOverlay();
    };
    state.raf = requestAnimationFrame(tick);
  }

  /* ------------------------------------------------------------------ *
   * Main workflow
   * ------------------------------------------------------------------ */

  async function labelFrame(frameNo, opts = {}) {
    const missing = missingLabels();
    if (missing.length === SCHEMA.length) {
      throw new Error(
        'This job has no Face-50 skeleton labels. Add longmaytrai/longmayphai/songmui/mattrai/matphai/moingoai/moitrong first (labels_raw.json).',
      );
    }

    const { image } = await getFrameImage(frameNo, !!opts.batch);
    const result = await callModel(image);
    if (!result.detected) {
      throw new Error(`No face detected in frame ${frameNo} (guideline: skip the frame).`);
    }

    state.frame = frameNo;
    state.prediction = { result, frame: frameNo };
    if (frameNo === currentFrame()) drawPrediction(result);

    if (state.cfg.previewOnly && !opts.batch) {
      renderStatus(result, { preview: true });
      return result;
    }

    const { shapes, points, warnings } = buildShapes(result, frameNo);
    await writeShapes(shapes, frameNo);
    state.lastWarnings = warnings;
    renderStatus(result, { wrote: shapes.length, points, warnings });
    return result;
  }

  async function runCurrent() {
    if (state.busy) {
      toast('Busy — wait for the current frame.', true);
      return;
    }
    state.busy = true;
    renderBusy();
    try {
      const frameNo = currentFrame();
      await labelFrame(frameNo, {});
      toast(`Frame ${frameNo}: ${state.cfg.previewOnly ? 'previewed' : 'written'}.`);
    } catch (e) {
      toast(e.message, true);
      renderStatus(null, { error: e.message });
    } finally {
      state.busy = false;
      renderBusy();
    }
  }

  async function runBatch() {
    if (state.batch) {
      state.batch.stop = true;
      return;
    }
    if (state.busy) return;

    const from = Number(state.ui.from.value);
    const to = Number(state.ui.to.value);
    if (!Number.isFinite(from) || !Number.isFinite(to) || to < from) {
      toast('Invalid frame range.', true);
      return;
    }

    state.batch = { stop: false, done: 0, total: to - from + 1, errors: 0 };
    state.busy = true;
    renderBusy();

    let firstError = '';
    for (let f = from; f <= to; f += 1) {
      if (state.batch?.stop) break;
      try {
        await labelFrame(f, { batch: true });
      } catch (e) {
        state.batch.errors += 1;
        if (!firstError) firstError = e.message;
      }
      state.batch.done += 1;
      if (state.ui) {
        state.ui.batchInfo.textContent = `${state.batch.done}/${state.batch.total}`;
        state.ui.status.textContent =
          `batch ${state.batch.done}/${state.batch.total} · errors ${state.batch.errors}`;
      }
    }

    const done = state.batch.done;
    const errors = state.batch.errors;
    state.batch = null;
    state.busy = false;
    renderBusy();
    toast(
      `Batch finished: ${done} frame(s), ${errors} error(s)${firstError ? ` — ${firstError}` : ''}.`,
      errors > 0,
    );
  }

  /* ------------------------------------------------------------------ *
   * UI
   * ------------------------------------------------------------------ */

  const STYLE = `
    :host { all: initial; }
    * { box-sizing: border-box; }
    .ov {
      position: fixed; pointer-events: none; z-index: 1; display: block;
    }
    .card {
      position: fixed; left: 16px; bottom: 110px; width: 268px;
      background: #111827; color: #e7e9ee; border: 1px solid #334155;
      border-radius: 10px; box-shadow: 0 10px 30px rgba(0,0,0,.45);
      font: 12px/1.35 system-ui, -apple-system, Segoe UI, sans-serif;
      pointer-events: auto; overflow: hidden;
    }
    .hdr {
      display: flex; align-items: center; gap: 8px; padding: 8px 10px;
      background: #0b1220; border-bottom: 1px solid #1f2937; cursor: move;
      user-select: none;
    }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: #22d3ee; }
    .title { font-weight: 600; flex: 1; letter-spacing: .2px; }
    .body { padding: 9px 10px 10px; display: flex; flex-direction: column; gap: 7px; }
    .row { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
    .muted { color: #94a3b8; }
    .grow { flex: 1; }
    button {
      background: #1f2937; color: #e7e9ee; border: 1px solid #374151;
      border-radius: 6px; padding: 4px 8px; font: inherit; cursor: pointer;
    }
    button:hover { background: #273449; }
    button.primary { background: #0891b2; border-color: #0891b2; color: #fff; font-weight: 600; }
    button.primary:hover { background: #06a3c8; }
    button.on { background: #b91c1c; border-color: #b91c1c; }
    button:disabled { opacity: .55; cursor: progress; }
    input[type="number"] {
      width: 54px; background: #0b1220; color: #e7e9ee; border: 1px solid #374151;
      border-radius: 6px; padding: 3px 5px; font: inherit;
    }
    label.sw { display: inline-flex; align-items: center; gap: 4px; cursor: pointer; }
    label.sw input { accent-color: #0891b2; }
    .groups { display: grid; grid-template-columns: 1fr 1fr; gap: 2px 8px; }
    .groups label { font-size: 11px; }
    .groups b { font-weight: 600; color: #cbd5e1; }
    .warn { color: #fbbf24; font-size: 11px; white-space: pre-wrap; }
    .err { color: #fca5a5; font-size: 11px; white-space: pre-wrap; }
    .toast {
      position: fixed; left: 50%; bottom: 140px; transform: translateX(-50%);
      max-width: 62vw; padding: 7px 12px; border-radius: 8px;
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
    host.style.cssText = 'position:fixed;inset:0;pointer-events:none;z-index:2147483000;';
    const root = host.attachShadow({ mode: 'open' });

    const style = document.createElement('style');
    style.textContent = STYLE;

    const overlay = document.createElement('canvas');
    overlay.className = 'ov';

    const card = document.createElement('div');
    card.className = 'card';
    card.innerHTML = `
      <div class="hdr">
        <span class="dot"></span>
        <span class="title">Face-50</span>
        <label class="sw"><input type="checkbox" data-k="open" checked><span>On</span></label>
      </div>
      <div class="body">
        <div class="row muted" id="meta"><span>job —</span><span class="grow"></span><span>frame —</span></div>
        <div class="row">
          <button class="primary grow" data-k="run">Auto-label</button>
          <label class="sw" title="Show points, do not write to CVAT"><input type="checkbox" data-k="previewOnly"><span>Preview</span></label>
        </div>
        <div class="row">
          <label class="sw" title="Delete the 7 skeletons of this frame before writing"><input type="checkbox" data-k="replace"><span>Replace</span></label>
          <label class="sw" title="Draw point ids on the overlay"><input type="checkbox" data-k="showIds"><span>IDs</span></label>
        </div>
        <div class="groups" id="groups"></div>
        <div class="row">
          <button data-k="batch">All frames</button>
          <input type="number" data-k="from" min="0" step="1" title="first frame">
          <span class="muted">–</span>
          <input type="number" data-k="to" min="0" step="1" title="last frame">
          <span class="muted" id="batchInfo"></span>
        </div>
        <div class="row">
          <button data-k="save" title="Save CVAT's own unsaved edits (Ctrl+S)">Save</button>
          <button data-k="reload" title="Reload the annotator">Reload</button>
          <button data-k="clear">Clear</button>
        </div>
        <div class="row muted" id="status">Alt+F = auto-label this frame</div>
        <div class="row warn" id="warn"></div>
      </div>`;

    const toastEl = document.createElement('div');
    toastEl.className = 'toast';

    root.append(style, overlay, card, toastEl);
    document.body.appendChild(host);

    state.ui = {
      host,
      root,
      overlay,
      card,
      toast: toastEl,
      header: card.querySelector('.hdr'),
      meta: card.querySelector('#meta'),
      status: card.querySelector('#status'),
      warn: card.querySelector('#warn'),
      groups: card.querySelector('#groups'),
      batchInfo: card.querySelector('#batchInfo'),
      open: card.querySelector('input[data-k="open"]'),
      previewOnly: card.querySelector('input[data-k="previewOnly"]'),
      replace: card.querySelector('input[data-k="replace"]'),
      showIds: card.querySelector('input[data-k="showIds"]'),
      run: card.querySelector('button[data-k="run"]'),
      batch: card.querySelector('button[data-k="batch"]'),
      from: card.querySelector('input[data-k="from"]'),
      to: card.querySelector('input[data-k="to"]'),
      save: card.querySelector('button[data-k="save"]'),
      reload: card.querySelector('button[data-k="reload"]'),
      clear: card.querySelector('button[data-k="clear"]'),
    };

    buildGroupToggles();
    wirePanel();
    makeDraggable();
    applyCfgToUi();
    renderMeta();
    startSync();
    return state.ui;
  }

  function buildGroupToggles() {
    const { groups } = state.ui;
    groups.innerHTML = '';
    for (const s of SCHEMA) {
      const label = document.createElement('label');
      label.className = 'sw';
      label.title = `${s.name}: ${s.count} points (${s.first}-${s.first + s.count - 1})`;
      label.innerHTML = `<input type="checkbox" data-group="${s.name}"><span><b>${s.name}</b> ${s.count}</span>`;
      groups.appendChild(label);
    }
  }

  function applyCfgToUi() {
    const ui = state.ui;
    if (!ui) return;
    ui.previewOnly.checked = !!state.cfg.previewOnly;
    ui.replace.checked = !!state.cfg.replace;
    ui.showIds.checked = !!state.cfg.showIds;
    for (const input of ui.groups.querySelectorAll('input[data-group]')) {
      input.checked = state.cfg.groups[input.dataset.group] !== false;
    }
  }

  function wirePanel() {
    const ui = state.ui;

    ui.run.addEventListener('click', runCurrent);
    ui.batch.addEventListener('click', runBatch);
    ui.save.addEventListener('click', saveInCvat);
    ui.reload.addEventListener('click', reloadView);
    ui.clear.addEventListener('click', clearPreview);

    ui.open.addEventListener('change', () => {
      ui.card.querySelector('.body').style.display = ui.open.checked ? '' : 'none';
    });
    ui.previewOnly.addEventListener('change', () => {
      state.cfg.previewOnly = ui.previewOnly.checked;
      saveCfg();
    });
    ui.replace.addEventListener('change', () => {
      state.cfg.replace = ui.replace.checked;
      saveCfg();
    });
    ui.showIds.addEventListener('change', () => {
      state.cfg.showIds = ui.showIds.checked;
      saveCfg();
      if (state.prediction) drawPrediction(state.prediction.result);
    });
    ui.groups.addEventListener('change', () => {
      for (const input of ui.groups.querySelectorAll('input[data-group]')) {
        state.cfg.groups[input.dataset.group] = input.checked;
      }
      saveCfg();
      if (state.prediction) drawPrediction(state.prediction.result);
    });

    document.addEventListener('keydown', (e) => {
      if (e.altKey && !e.ctrlKey && !e.metaKey && String(e.key).toLowerCase() === 'f') {
        e.preventDefault();
        e.stopPropagation();
        if (!state.batch) runCurrent();
      }
    }, true);
  }

  function makeDraggable() {
    const ui = state.ui;
    let origin = null;
    try {
      const saved = JSON.parse(localStorage.getItem(STORE_POS) || 'null');
      if (saved && Number.isFinite(saved.left) && Number.isFinite(saved.top)) {
        ui.card.style.left = `${saved.left}px`;
        ui.card.style.top = `${saved.top}px`;
        ui.card.style.bottom = 'auto';
      }
    } catch { /* ignore */ }

    ui.header.addEventListener('pointerdown', (e) => {
      if (e.target.matches('input')) return;
      const r = ui.card.getBoundingClientRect();
      origin = { x: e.clientX - r.left, y: e.clientY - r.top };
      ui.header.setPointerCapture(e.pointerId);
    });
    ui.header.addEventListener('pointermove', (e) => {
      if (!origin) return;
      const left = Math.max(0, Math.min(window.innerWidth - 60, e.clientX - origin.x));
      const top = Math.max(0, Math.min(window.innerHeight - 40, e.clientY - origin.y));
      ui.card.style.left = `${left}px`;
      ui.card.style.top = `${top}px`;
      ui.card.style.bottom = 'auto';
    });
    ui.header.addEventListener('pointerup', () => {
      if (!origin) return;
      origin = null;
      const r = ui.card.getBoundingClientRect();
      localStorage.setItem(STORE_POS, JSON.stringify({ left: r.left, top: r.top }));
    });
  }

  function renderMeta() {
    const ui = state.ui;
    if (!ui) return;
    const [jobSpan, , frameSpan] = ui.meta.children;
    jobSpan.textContent = state.jobId ? `job ${state.jobId}` : 'no job';
    frameSpan.textContent = `frame ${currentFrame()}`;
    ui.run.disabled = !state.jobId || state.busy;
    ui.batch.disabled = !state.jobId;
  }

  function renderLabelStatus() {
    const ui = state.ui;
    if (!ui) return;
    const missing = missingLabels();
    const broken = incompleteLabels();
    if (state.labelsError) {
      ui.warn.className = 'row err';
      ui.warn.textContent = state.labelsError;
    } else if (missing.length) {
      ui.warn.className = 'row warn';
      ui.warn.textContent = `missing labels (${missing.length}/7): ${missing.join(', ')}`;
    } else if (broken.length) {
      ui.warn.className = 'row warn';
      ui.warn.textContent = `sublabels incomplete: ${broken.join(', ')}`;
    } else {
      ui.warn.className = 'row warn';
      ui.warn.textContent = '';
    }
  }

  function renderStatus(result, extra = {}) {
    const ui = state.ui;
    if (!ui) return;
    ui.warn.className = 'row warn';
    if (extra.error) {
      ui.status.textContent = 'error';
      ui.warn.className = 'row err';
      ui.warn.textContent = extra.error;
      return;
    }
    if (extra.batch) {
      ui.status.textContent = extra.batch;
      return;
    }
    if (!result) return;

    const s = result.summary || {};
    const face = result.face || {};
    const wrote = extra.wrote ? ` · wrote ${extra.wrote} skeleton(s)/${extra.points} pts` : '';
    ui.status.textContent =
      `V ${s.visible || 0} · O ${s.occluded || 0} · X ${s.outside || 0} · ` +
      `yaw ${face.yaw_deg ?? '?'}° · ${result.elapsed_ms ?? '?'} ms${wrote}`;

    const warnings = [...(result.warnings || []), ...(extra.warnings || [])];
    ui.warn.className = 'row warn';
    ui.warn.textContent = warnings.slice(0, 3).join('\n');
  }

  function renderBusy() {
    const ui = state.ui;
    if (!ui) return;
    ui.run.disabled = state.busy;
    ui.run.textContent = state.busy && !state.batch ? 'Working…' : 'Auto-label';
    if (state.batch) {
      ui.batch.textContent = 'Stop';
      ui.batch.classList.add('on');
    } else {
      ui.batch.textContent = 'All frames';
      ui.batch.classList.remove('on');
      ui.batchInfo.textContent = '';
    }
    renderMeta();
  }

  let toastTimer = 0;
  function toast(message, isError = false) {
    const ui = state.ui;
    if (!ui) return;
    ui.toast.textContent = message;
    ui.toast.className = `toast show${isError ? ' err' : ''}`;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      ui.toast.className = 'toast';
    }, isError ? 6000 : 2500);
  }

  /* ------------------------------------------------------------------ *
   * Config + lifecycle
   * ------------------------------------------------------------------ */

  function saveCfg() {
    const { endpoint, timeoutMs, replace, previewOnly, showIds, groups } = state.cfg;
    chrome.storage.local.set({ [STORE_CFG]: { endpoint, timeoutMs, replace, previewOnly, showIds, groups } });
  }

  async function loadCfg() {
    const data = await chrome.storage.local.get([STORE_CFG]);
    const stored = data[STORE_CFG] || {};
    state.cfg = {
      ...DEFAULT_CFG,
      ...stored,
      groups: { ...DEFAULT_CFG.groups, ...(stored.groups || {}) },
    };
  }

  async function pollTick() {
    const job = currentJobId();
    if (job !== state.jobId) {
      state.jobId = job;
      state.labelMap = {};
      state.labels = [];
      state.prediction = null;
      clearPreview();
      await loadLabels();
      await loadJobMeta();
    }
    const frame = currentFrame();
    if (frame !== state.frame) {
      state.frame = frame;
      if (state.prediction && state.prediction.frame !== frame) clearPreview();
      renderMeta();
    }
  }

  async function init() {
    await loadCfg();
    if (!ensurePanel()) {
      setTimeout(init, 800);
      return;
    }
    await pollTick();
    state.poll = setInterval(pollTick, 700);
    watchCfg();
  }

  /* The options page writes the same record; keep an open tab in sync. */
  function watchCfg() {
    if (!chrome.storage?.onChanged) return;
    chrome.storage.onChanged.addListener((changes, area) => {
      if (area !== 'local' || !changes[STORE_CFG]) return;
      const stored = changes[STORE_CFG].newValue || {};
      state.cfg = {
        ...DEFAULT_CFG,
        ...stored,
        groups: { ...DEFAULT_CFG.groups, ...(stored.groups || {}) },
      };
      if (state.ui) applyCfgToUi();
      if (state.prediction) drawPrediction(state.prediction.result);
    });
  }

  init();
})();
