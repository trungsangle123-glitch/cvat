(() => {
  "use strict";

  if (window.__cvatAutoQcLoaded) return;
  window.__cvatAutoQcLoaded = true;

  const HOST_ID = "cvat-autoqc-host";
  const DEFAULTS = {
    serverUrl: "http://localhost:58220",
    timeoutMs: 300000,
    cvatHost: "http://localhost:8080",
    token: "",
  };

  let cfg = { ...DEFAULTS };
  let jobId = null;
  let result = null;
  let busy = false;
  let selectedIssue = null;

  function currentJobId() {
    const match = location.pathname.match(/\/jobs\/(\d+)/);
    if (match) return Number(match[1]);
    const job = new URLSearchParams(location.search).get("job");
    return job ? Number(job) : null;
  }

  function currentFrame() {
    const input = document.querySelector(".cvat-player-frame-selector input");
    if (input) {
      const value = Number(input.value);
      if (Number.isFinite(value)) return value;
    }
    const frame = Number(new URLSearchParams(location.search).get("frame"));
    return Number.isFinite(frame) ? frame : 0;
  }

  function issueSeverity(issue) {
    return issue.severity === "error" ? "error" : "warn";
  }

  function ensurePanel() {
    if (document.getElementById(HOST_ID)) return;

    const host = document.createElement("div");
    host.id = HOST_ID;
    host.innerHTML = `
      <style>
        #cvat-autoqc-panel {
          position: fixed; z-index: 10000; left: 16px; bottom: 16px;
          width: 330px; max-height: 520px; overflow: hidden;
          background: #fff; color: #262626;
          border: 1px solid #d9d9d9; border-radius: 2px;
          box-shadow: 0 3px 6px rgba(0,0,0,.16);
          font: 12px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
        }
        #cvat-autoqc-header {
          height: 38px; display:flex; align-items:center; gap:8px;
          padding: 0 8px 0 12px; border-bottom:1px solid #f0f0f0;
          background:#fafafa; cursor:move; user-select:none;
        }
        #cvat-autoqc-header strong { flex:1; font-size:13px; }
        #cvat-autoqc-body { max-height: 440px; overflow-y:auto; padding:12px; }
        #cvat-autoqc-panel button {
          height:30px; border:1px solid #d9d9d9; border-radius:2px;
          background:#fff; color:#262626; padding:0 10px; cursor:pointer;
        }
        #cvat-autoqc-panel button:hover { color:#40a9ff; border-color:#40a9ff; }
        #cvat-autoqc-panel button.primary {
          background:#1890ff; border-color:#1890ff; color:#fff;
        }
        #cvat-autoqc-panel button.primary:hover { background:#40a9ff; }
        #cvat-autoqc-panel button:disabled { color:#bfbfbf; background:#f5f5f5; border-color:#d9d9d9; cursor:not-allowed; }
        #cvat-autoqc-meta { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:10px; }
        .cvat-autoqc-stat { border:1px solid #f0f0f0; padding:7px 8px; }
        .cvat-autoqc-stat b { display:block; font-size:15px; }
        #cvat-autoqc-verdict { margin:10px 0; padding:8px; border-left:3px solid #faad14; background:#fffbe6; }
        #cvat-autoqc-verdict.release { border-left-color:#52c41a; background:#f6ffed; }
        #cvat-autoqc-verdict.rework { border-left-color:#ff4d4f; background:#fff1f0; }
        #cvat-autoqc-actions { display:flex; gap:8px; margin-bottom:10px; }
        #cvat-autoqc-list { display:grid; gap:6px; }
        .cvat-autoqc-issue {
          width:100%; box-sizing:border-box; text-align:left; height:auto !important;
          min-height:48px; padding:7px 8px !important; white-space:normal;
          border-color:#f0f0f0 !important;
        }
        .cvat-autoqc-issue.error { border-left:3px solid #ff4d4f !important; }
        .cvat-autoqc-issue.warn { border-left:3px solid #faad14 !important; }
        .cvat-autoqc-issue.selected { background:#e6f7ff; border-color:#91d5ff !important; }
        .cvat-autoqc-code { font-family:ui-monospace,SFMono-Regular,Consolas,monospace; color:#595959; }
        #cvat-autoqc-status { color:#8c8c8c; min-height:18px; margin-top:8px; }
        #cvat-autoqc-toggle { position:fixed; z-index:9999; left:16px; bottom:16px; width:96px; }
        #cvat-autoqc-panel.collapsed #cvat-autoqc-body { display:none; }
      </style>
      <div id="cvat-autoqc-panel">
        <div id="cvat-autoqc-header">
          <strong>AutoQC</strong>
          <button id="cvat-autoqc-collapse" title="Collapse">−</button>
        </div>
        <div id="cvat-autoqc-body">
          <div id="cvat-autoqc-meta"></div>
          <div id="cvat-autoqc-verdict">Chưa chạy QC.</div>
          <div id="cvat-autoqc-actions">
            <button id="cvat-autoqc-run" class="primary">Run QC</button>
            <button id="cvat-autoqc-open-frame" disabled>Open frame</button>
          </div>
          <div id="cvat-autoqc-list"></div>
          <div id="cvat-autoqc-status"></div>
        </div>
      </div>
    `;
    document.documentElement.appendChild(host);

    document.getElementById("cvat-autoqc-collapse").addEventListener("click", () => {
      document.getElementById("cvat-autoqc-panel").classList.toggle("collapsed");
      const button = document.getElementById("cvat-autoqc-collapse");
      button.textContent = document.getElementById("cvat-autoqc-panel").classList.contains("collapsed") ? "+" : "−";
    });

    document.getElementById("cvat-autoqc-run").addEventListener("click", runQc);
    document.getElementById("cvat-autoqc-open-frame").addEventListener("click", openSelectedFrame);

    const panel = document.getElementById("cvat-autoqc-panel");
    let dragging = false;
    let dx = 0;
    let dy = 0;
    const header = document.getElementById("cvat-autoqc-header");
    header.addEventListener("mousedown", (event) => {
      if (event.target.tagName === "BUTTON") return;
      dragging = true;
      const rect = panel.getBoundingClientRect();
      dx = event.clientX - rect.left;
      dy = event.clientY - rect.top;
    });
    window.addEventListener("mousemove", (event) => {
      if (!dragging) return;
      panel.style.left = `${Math.max(0, event.clientX - dx)}px`;
      panel.style.top = `${Math.max(0, event.clientY - dy)}px`;
      panel.style.bottom = "auto";
    });
    window.addEventListener("mouseup", () => { dragging = false; });
  }

  function setStatus(text) {
    const el = document.getElementById("cvat-autoqc-status");
    if (el) el.textContent = text || "";
  }

  function renderMeta() {
    const el = document.getElementById("cvat-autoqc-meta");
    if (!el) return;
    el.innerHTML = `
      <div class="cvat-autoqc-stat"><span>Job</span><b>${jobId || "-"}</b></div>
      <div class="cvat-autoqc-stat"><span>Frame</span><b>${currentFrame()}</b></div>
    `;
  }

  function renderResult() {
    renderMeta();
    const verdict = document.getElementById("cvat-autoqc-verdict");
    const list = document.getElementById("cvat-autoqc-list");
    if (!verdict || !list) return;

    if (!result) {
      verdict.textContent = "Chưa chạy QC.";
      verdict.className = "";
      list.textContent = "";
      document.getElementById("cvat-autoqc-open-frame").disabled = true;
      return;
    }

    verdict.className = result.decision.toLowerCase();
    verdict.innerHTML = `
      <b>${result.decision}</b><br>
      ${result.n_errors} lỗi bắt buộc · ${result.n_warn_frames} frame cảnh báo · ${Math.round(result.warn_ratio * 10000) / 100}%.
      ${result.reasons?.length ? `<br>${result.reasons.join(" ")}` : ""}
    `;

    list.textContent = "";
    if (!result.issues?.length) {
      const empty = document.createElement("div");
      empty.textContent = "Không có issue.";
      list.appendChild(empty);
      return;
    }

    for (const issue of result.issues) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `cvat-autoqc-issue ${issueSeverity(issue)}`;
      button.innerHTML = `
        <b class="cvat-autoqc-code">${escapeHtml(issue.code)}</b>
        <br>Frame ${issue.frame ?? "-"}${issue.shape_id ? ` · shape ${issue.shape_id}` : ""}
        <br>${escapeHtml(issue.message)}
      `;
      button.addEventListener("click", () => {
        selectedIssue = issue;
        for (const node of list.querySelectorAll("button")) node.classList.remove("selected");
        button.classList.add("selected");
        document.getElementById("cvat-autoqc-open-frame").disabled = issue.frame == null;
      });
      list.appendChild(button);
    }
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;");
  }

  async function runQc() {
    if (busy) return;
    if (!jobId) {
      setStatus("Mở một CVAT job trước.");
      return;
    }
    const { autoQcCfg } = await chrome.storage.local.get(["autoQcCfg"]);
    cfg = { ...DEFAULTS, ...(autoQcCfg || {}) };
    if (!cfg.token) {
      setStatus("Chưa có CVAT token. Mở AutoQC settings.");
      return;
    }

    busy = true;
    const button = document.getElementById("cvat-autoqc-run");
    button.disabled = true;
    setStatus("Đang kiểm tra job…");

    try {
      const response = await chrome.runtime.sendMessage({
        type: "autoqc-run",
        serverUrl: cfg.serverUrl,
        timeoutMs: cfg.timeoutMs,
        payload: {
          cvat_host: cfg.cvatHost,
          token: cfg.token,
          job_id: jobId,
        },
      });
      if (!response?.ok) throw new Error(response?.error || "No response.");
      result = response.data;
      selectedIssue = null;
      renderResult();
      setStatus(`Hoàn tất ${result.n_frames} frame.`);
    } catch (error) {
      setStatus(error.message || String(error));
    } finally {
      busy = false;
      button.disabled = false;
    }
  }

  function openSelectedFrame() {
    if (!selectedIssue || selectedIssue.frame == null) return;
    const url = new URL(location.href);
    url.searchParams.set("frame", String(selectedIssue.frame));
    location.href = url.toString();
  }

  async function syncJob() {
    const nextJobId = currentJobId();
    if (nextJobId === jobId) {
      renderMeta();
      return;
    }
    jobId = nextJobId;
    result = null;
    selectedIssue = null;
    renderResult();
  }

  async function boot() {
    const { autoQcCfg } = await chrome.storage.local.get(["autoQcCfg"]);
    cfg = { ...DEFAULTS, ...(autoQcCfg || {}) };
    ensurePanel();
    await syncJob();
    setInterval(syncJob, 1500);
  }

  boot();
})();
