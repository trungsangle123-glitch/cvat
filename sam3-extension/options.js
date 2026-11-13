/* CVAT SAM 3 Segment — options page */

const BUILTIN_SITES = ['https://cvat.edufun.ai'];

const $ = (id) => document.getElementById(id);

function originOf(input) {
  const raw = (input || '').trim();
  if (!raw) return null;
  try {
    const u = new URL(/^[a-z]+:\/\//i.test(raw) ? raw : `https://${raw}`);
    return `${u.protocol}//${u.host}`;
  } catch {
    return null;
  }
}

function patternOf(origin) {
  return `${origin}/*`;
}

async function loadCfg() {
  const { cfg } = await chrome.storage.local.get(['cfg']);
  const merged = { sam3Url: 'http://localhost:58218/', timeoutMs: 180000, ...(cfg || {}) };
  $('url').value = merged.sam3Url;
  $('timeout').value = Math.round((merged.timeoutMs || 180000) / 1000);
  return merged;
}

function setStatus(text, kind = '') {
  const el = $('status');
  el.textContent = text;
  el.className = kind;
}

async function save() {
  const url = originOf($('url').value) || ($('url').value || '').trim();
  if (!url) {
    setStatus('Enter a URL.', 'err');
    return;
  }
  const origin = originOf(url);
  const timeoutMs = Math.min(900, Math.max(10, Number($('timeout').value) || 180)) * 1000;

  if (origin && !(await hasOrigin(origin))) {
    const granted = await chrome.permissions.request({ origins: [patternOf(origin)] }).catch(() => false);
    if (!granted) {
      setStatus('Permission for the model host was denied — the browser will block the request.', 'err');
    }
  }

  $('url').value = origin ? `${origin}/` : url;
  const { cfg } = await chrome.storage.local.get(['cfg']);
  await chrome.storage.local.set({ cfg: { ...(cfg || {}), sam3Url: $('url').value, timeoutMs } });
  setStatus('Saved.', 'ok');
}

async function hasOrigin(origin) {
  return chrome.permissions.contains({ origins: [patternOf(origin)] }).catch(() => false);
}

async function testConnection() {
  const url = originOf($('url').value) ? `${originOf($('url').value)}/` : $('url').value;
  setStatus('Testing…');
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 8000);
    const res = await fetch(url, { method: 'GET', signal: ctrl.signal });
    clearTimeout(t);
    setStatus(`Reachable — HTTP ${res.status} (any response means the function is up).`, 'ok');
  } catch (e) {
    setStatus(`Not reachable: ${e.message}. Check the container, the port and the host permission.`, 'err');
  }
}

async function listSites() {
  const registered = await chrome.scripting.getRegisteredContentScripts();
  const dynamic = registered.map((s) => (s.matches || [])[0]).filter(Boolean);
  const all = [...new Set([...BUILTIN_SITES.map(patternOf), ...dynamic])];

  const ul = $('sites');
  ul.innerHTML = '';
  for (const pattern of all) {
    const li = document.createElement('li');
    const span = document.createElement('span');
    span.textContent = pattern.replace(/\/\*$/, '');
    li.appendChild(span);

    if (!BUILTIN_SITES.map(patternOf).includes(pattern)) {
      const rm = document.createElement('button');
      rm.textContent = 'Remove';
      rm.addEventListener('click', async () => {
        const script = registered.find((s) => (s.matches || [])[0] === pattern);
        if (script) await chrome.scripting.unregisterContentScripts({ ids: [script.id] });
        await listSites();
      });
      li.appendChild(rm);
    } else {
      const tag = document.createElement('span');
      tag.className = 'hint';
      tag.textContent = 'built-in';
      li.appendChild(tag);
    }
    ul.appendChild(li);
  }
}

async function addSite() {
  const origin = originOf($('site').value);
  if (!origin) {
    setStatus('Enter a valid CVAT URL.', 'err');
    return;
  }
  const granted = await chrome.permissions.request({ origins: [patternOf(origin)] }).catch(() => false);
  if (!granted) {
    setStatus('Permission denied.', 'err');
    return;
  }
  const id = `cvat-${origin.replace(/[^a-z0-9]+/gi, '-')}`;
  const existing = await chrome.scripting.getRegisteredContentScripts({ ids: [id] });
  if (!existing.length) {
    await chrome.scripting.registerContentScripts([
      {
        id,
        matches: [patternOf(origin)],
        js: ['content.js'],
        runAt: 'document_idle',
        allFrames: false,
      },
    ]);
  }
  $('site').value = '';
  setStatus(`Added ${origin}. Reload the CVAT tab.`, 'ok');
  await listSites();
}

$('save').addEventListener('click', save);
$('test').addEventListener('click', testConnection);
$('addSite').addEventListener('click', addSite);

loadCfg();
listSites();
