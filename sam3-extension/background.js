/* CVAT SAM 3 Segment — service worker.
 *
 * Its only job is to reach the SAM 3 endpoint. Content scripts run on the CVAT
 * origin, so a fetch from there to http://localhost:58218 would be blocked by
 * CORS. Fetches started here are covered by host_permissions instead.
 */

const DEFAULT_TIMEOUT_MS = 180000;

chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.local.get(['cfg']).then(({ cfg }) => {
    chrome.storage.local.set({
      cfg: {
        sam3Url: 'http://localhost:58218/',
        timeoutMs: DEFAULT_TIMEOUT_MS,
        ...(cfg || {}),
      },
    });
  });
});

chrome.action.onClicked.addListener(() => {
  chrome.runtime.openOptionsPage();
});

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (!msg || msg.type !== 'sam3') return undefined;

  callSam3(msg).then(
    (data) => sendResponse({ ok: true, data }),
    (err) => sendResponse({ ok: false, error: err?.message || String(err) }),
  );
  return true; // keep the message channel open for the async reply
});

async function callSam3({ url, payload, timeoutMs }) {
  if (!url) throw new Error('SAM 3 URL is not configured (extension options).');

  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs || DEFAULT_TIMEOUT_MS);

  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: ctrl.signal,
    });

    const text = await res.text();
    if (!res.ok) {
      throw new Error(`SAM 3 HTTP ${res.status}: ${text.slice(0, 400) || '<empty body>'}`);
    }
    try {
      return JSON.parse(text);
    } catch {
      throw new Error(`SAM 3 returned non-JSON: ${text.slice(0, 400)}`);
    }
  } catch (err) {
    if (err?.name === 'AbortError') {
      throw new Error(`SAM 3 timed out after ${Math.round((timeoutMs || DEFAULT_TIMEOUT_MS) / 1000)}s`);
    }
    if (/Failed to fetch/i.test(err?.message || '')) {
      throw new Error(
        `Cannot reach ${url}. Is the function running and is the host granted in the extension settings?`,
      );
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}
