const DEFAULTS = {
  serverUrl: "http://localhost:58220",
  timeoutMs: 300000,
};

chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.local.get(["autoQcCfg"]).then(({ autoQcCfg }) => {
    chrome.storage.local.set({
      autoQcCfg: { ...DEFAULTS, ...(autoQcCfg || {}) },
    });
  });
});

chrome.action.onClicked.addListener(() => chrome.runtime.openOptionsPage());

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (!msg || !["autoqc-run", "autoqc-health"].includes(msg.type)) return undefined;
  const operation = msg.type === "autoqc-run" ? runAutoQc(msg) : health(msg);
  operation.then(
    (data) => sendResponse({ ok: true, data }),
    (error) => sendResponse({ ok: false, error: error?.message || String(error) }),
  );
  return true;
});

async function health({ serverUrl, timeoutMs }) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), Math.min(timeoutMs || 8000, 8000));
  try {
    const res = await fetch(`${String(serverUrl).replace(/\/$/, "")}/health`, {
      signal: ctrl.signal,
    });
    const text = await res.text();
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${text.slice(0, 200)}`);
    return JSON.parse(text);
  } catch (error) {
    if (error?.name === "AbortError") throw new Error("AutoQC server timed out.");
    throw explainFetch(error, serverUrl);
  } finally {
    clearTimeout(timer);
  }
}

async function runAutoQc({ serverUrl, timeoutMs, payload }) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs || DEFAULTS.timeoutMs);
  try {
    const res = await fetch(`${String(serverUrl).replace(/\/$/, "")}/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: ctrl.signal,
    });
    const text = await res.text();
    if (!res.ok) throw new Error(`AutoQC HTTP ${res.status}: ${text.slice(0, 400)}`);
    return JSON.parse(text);
  } catch (error) {
    if (error?.name === "AbortError") {
      throw new Error(`AutoQC timed out after ${Math.round((timeoutMs || 300000) / 1000)}s.`);
    }
    throw explainFetch(error, serverUrl);
  } finally {
    clearTimeout(timer);
  }
}

function explainFetch(error, serverUrl) {
  if (/Failed to fetch/i.test(error?.message || "")) {
    return new Error(`Cannot reach ${serverUrl}. Is the AutoQC container running?`);
  }
  return error instanceof Error ? error : new Error(String(error));
}
