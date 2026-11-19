const DEFAULTS = {
  serverUrl: "http://localhost:58220",
  timeoutMs: 300000,
  cvatHost: "http://localhost:8080",
  token: "",
};

const $ = (id) => document.getElementById(id);

async function load() {
  const { autoQcCfg } = await chrome.storage.local.get(["autoQcCfg"]);
  const cfg = { ...DEFAULTS, ...(autoQcCfg || {}) };
  $("server").value = cfg.serverUrl;
  $("timeout").value = String(Math.round(cfg.timeoutMs / 1000));
  $("cvatHost").value = cfg.cvatHost;
  $("token").value = cfg.token;
}

async function save() {
  const cfg = {
    serverUrl: $("server").value.trim().replace(/\/$/, "") || DEFAULTS.serverUrl,
    timeoutMs: Math.min(900, Math.max(30, Number($("timeout").value) || 300)) * 1000,
    cvatHost: $("cvatHost").value.trim().replace(/\/$/, "") || DEFAULTS.cvatHost,
    token: $("token").value.trim(),
  };
  await chrome.storage.local.set({ autoQcCfg: cfg });
  setStatus("Saved.", "ok");
}

async function testConnection() {
  const serverUrl = $("server").value.trim().replace(/\/$/, "") || DEFAULTS.serverUrl;
  setStatus("Testing…");
  try {
    const res = await chrome.runtime.sendMessage({
      type: "autoqc-health",
      serverUrl,
      timeoutMs: 8000,
    });
    if (!res?.ok) throw new Error(res?.error || "No response.");
    setStatus("Server is reachable.", "ok");
  } catch (error) {
    setStatus(error.message || String(error), "err");
  }
}

function setStatus(text, kind = "") {
  $("status").textContent = text;
  $("status").className = kind;
}

$("save").addEventListener("click", save);
$("test").addEventListener("click", testConnection);
load();
