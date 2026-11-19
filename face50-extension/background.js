/* CVAT Face Landmark-50 — service worker.
 *
 * Content scripts run on the CVAT origin, so a fetch to http://localhost:58219
 * would be blocked by CORS. Requests started from the service worker are
 * covered by host_permissions instead.
 */

const DEFAULTS = {
  endpoint: 'http://localhost:58219/predict',
  timeoutMs: 120000,
};

chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.local.get(['face50Cfg']).then(({ face50Cfg }) => {
    chrome.storage.local.set({ face50Cfg: { ...DEFAULTS, ...(face50Cfg || {}) } });
  });
});

chrome.action.onClicked.addListener(() => {
  chrome.runtime.openOptionsPage();
});

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (!msg) return undefined;

  if (msg.type === 'face50') {
    postJSON(msg).then(
      (data) => sendResponse({ ok: true, data }),
      (err) => sendResponse({ ok: false, error: err?.message || String(err) }),
    );
    return true;
  }

  if (msg.type === 'face50-ping') {
    ping(msg.endpoint).then(
      (data) => sendResponse({ ok: true, data }),
      (err) => sendResponse({ ok: false, error: err?.message || String(err) }),
    );
    return true;
  }

  return undefined;
});

function normalize(url, path) {
  let clean = String(url || '').trim();
  if (!clean) throw new Error('Model endpoint is not configured (extension options).');
  if (!/^https?:\/\//i.test(clean)) clean = `http://${clean}`;
  const u = new URL(clean);
  if (!u.pathname || u.pathname === '/') u.pathname = path;
  return u.toString();
}

async function withTimeout(timeoutMs, fn) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs || DEFAULTS.timeoutMs);
  try {
    return await fn(ctrl.signal);
  } finally {
    clearTimeout(timer);
  }
}

async function postJSON({ url, payload, timeoutMs }) {
  const target = normalize(url || DEFAULTS.endpoint, 'predict');
  try {
    return await withTimeout(timeoutMs, async (signal) => {
      const res = await fetch(target, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal,
      });
      const text = await res.text();
      if (!res.ok) {
        throw new Error(`Model HTTP ${res.status}: ${text.slice(0, 400) || '<empty body>'}`);
      }
      try {
        return JSON.parse(text);
      } catch {
        throw new Error(`Model returned non-JSON: ${text.slice(0, 300)}`);
      }
    });
  } catch (err) {
    throw explain(err, target, timeoutMs);
  }
}

async function ping(endpoint) {
  const target = normalize(endpoint || DEFAULTS.endpoint, 'predict').replace(/\/predict\/?$/, '/health');
  try {
    return await withTimeout(8000, async (signal) => {
      const res = await fetch(target, { signal });
      const text = await res.text();
      if (!res.ok) throw new Error(`HTTP ${res.status}: ${text.slice(0, 200)}`);
      return JSON.parse(text);
    });
  } catch (err) {
    throw explain(err, target, 8000);
  }
}

function explain(err, target, timeoutMs) {
  if (err?.name === 'AbortError') {
    return new Error(`Timed out after ${Math.round((timeoutMs || DEFAULTS.timeoutMs) / 1000)}s (${target})`);
  }
  if (/Failed to fetch/i.test(err?.message || '')) {
    return new Error(`Cannot reach ${target}. Is the container running and the host allowed in the extension?`);
  }
  return err instanceof Error ? err : new Error(String(err));
}
