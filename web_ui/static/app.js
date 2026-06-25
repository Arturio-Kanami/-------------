const stateUrl = "/api/state";
let state = null;

const $ = (id) => document.getElementById(id);
const fmtSize = (bytes) => {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`;
};
const fmtTime = (ts) => ts ? new Date(ts * 1000).toLocaleTimeString() : "";
const clip = (text, n = 96) => text && text.length > n ? `${text.slice(0, n)}...` : (text || "");

async function api(path, body = {}) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return res.json();
}

function rowEmpty(text) {
  return `<div class="empty">${text}</div>`;
}

function renderCandidates(items) {
  const el = $("candidateList");
  if (!items.length) {
    el.innerHTML = rowEmpty("还没有捕获到媒体。请在 Edge 中播放已购课节。");
    return;
  }
  el.innerHTML = items.map((item) => `
    <div class="row">
      <div class="row-main">
        <div class="row-title">${item.page_title || item.host || "未命名视频"}</div>
        <div class="row-actions">
          <button data-download-video="${item.id}">下载视频</button>
          <button class="secondary" data-download-audio="${item.id}">仅音频</button>
        </div>
      </div>
      <div class="row-meta">
        <span class="chip">${item.kind}</span>
        <span>${item.host}</span>
        <span>命中 ${item.hits}</span>
        ${item.content_type ? `<span>${item.content_type}</span>` : ""}
      </div>
      <div class="url-line">${clip(item.url, 180)}</div>
    </div>
  `).join("");
  el.querySelectorAll("[data-download-video]").forEach((button) => {
    button.addEventListener("click", () => api("/api/download", { id: button.dataset.downloadVideo, type: "video" }).then(refresh));
  });
  el.querySelectorAll("[data-download-audio]").forEach((button) => {
    button.addEventListener("click", () => api("/api/download", { id: button.dataset.downloadAudio, type: "audio" }).then(refresh));
  });
}

function renderJobs(items) {
  const el = $("jobList");
  if (!items.length) {
    el.innerHTML = rowEmpty("暂无任务。");
    return;
  }
  el.innerHTML = items.slice(0, 12).map((job) => `
    <div class="row">
      <div class="row-main">
        <div class="row-title">${job.label}</div>
        <span class="chip ${job.status}">${job.kind} · ${job.status}</span>
      </div>
      <div class="row-meta">
        <span>${fmtTime(job.started_at)}</span>
        ${job.output ? `<span>${clip(job.output, 80)}</span>` : ""}
      </div>
      ${job.error ? `<div class="url-line">${job.error}</div>` : ""}
    </div>
  `).join("");
}

function renderFiles(el, items, emptyText, withTranscribe = false) {
  if (!items.length) {
    el.innerHTML = rowEmpty(emptyText);
    return;
  }
  el.innerHTML = items.slice(0, 18).map((file) => `
    <div class="row">
      <div class="row-main">
        <div class="row-title">${file.name}</div>
        ${withTranscribe ? `<button class="secondary" data-transcribe-file="${file.path}">转写</button>` : ""}
      </div>
      <div class="row-meta">
        <span>${fmtSize(file.size)}</span>
        <span>${file.short_path}</span>
      </div>
    </div>
  `).join("");
  el.querySelectorAll("[data-transcribe-file]").forEach((button) => {
    button.addEventListener("click", () => {
      $("transcribePath").value = button.dataset.transcribeFile;
      startTranscribe();
    });
  });
}

function renderLogs(items) {
  $("logBox").textContent = items.map((item) => {
    const level = item.level === "error" ? "ERR" : item.level === "success" ? "OK " : "INF";
    return `${fmtTime(item.ts)} ${level} ${item.message}`;
  }).join("\n");
  $("logBox").scrollTop = $("logBox").scrollHeight;
}

function render(next) {
  state = next;
  $("browserLabel").textContent = state.browser_path ? state.browser_path.split("\\").pop() : "未找到";
  $("ffmpegLabel").textContent = state.ffmpeg_path ? "已找到" : "未找到";
  $("gpuLabel").textContent = state.gpu?.ready ? "CUDA 可用" : state.gpu?.nvidia ? "缺运行库" : "未检测到";
  $("captureStatus").textContent = state.capture_running ? "运行中" : "未启动";
  const notice = $("gpuNotice");
  if (state.gpu?.nvidia && !state.gpu?.ready) {
    notice.hidden = false;
    const missing = [
      state.gpu.cublas ? "" : "cublas64_12.dll",
      state.gpu.cudnn ? "" : "cuDNN",
    ].filter(Boolean).join("、");
    notice.textContent = `检测到 NVIDIA 显卡，但本机 PATH 中缺少 ${missing || "CUDA/cuDNN 运行库"}。自动模式会直接使用 CPU，避免 GPU 初始化失败。`;
  } else if (state.gpu?.ready) {
    notice.hidden = false;
    notice.textContent = "CUDA 运行库已就绪，自动模式会优先使用 GPU。";
  } else {
    notice.hidden = true;
  }
  renderCandidates(state.candidates);
  renderJobs(state.jobs);
  renderFiles($("downloadList"), state.downloads, "downloads 文件夹里还没有视频。", true);
  renderFiles($("transcriptList"), state.transcripts, "transcripts 文件夹里还没有文字稿。");
  renderLogs(state.logs);
}

async function refresh() {
  const res = await fetch(stateUrl, { cache: "no-store" });
  render(await res.json());
}

function startTranscribe() {
  const path = $("transcribePath").value.trim();
  const model = $("modelName").value;
  const language = $("language").value;
  const device = $("device").value;
  const force = $("forceTranscribe").checked;
  api("/api/transcribe", { path, model, language, device, force }).then(refresh);
}

$("startCaptureBtn").addEventListener("click", () => {
  api("/api/capture/start", { url: $("courseUrl").value.trim() }).then(refresh);
});
$("stopCaptureBtn").addEventListener("click", () => api("/api/capture/stop").then(refresh));
$("clearCandidatesBtn").addEventListener("click", () => api("/api/candidates/clear").then(refresh));
$("clearJobsBtn").addEventListener("click", () => api("/api/jobs/clear").then(refresh));
$("clearLogsBtn").addEventListener("click", () => api("/api/logs/clear").then(refresh));
$("startTranscribeBtn").addEventListener("click", startTranscribe);
$("refreshBtn").addEventListener("click", refresh);
$("openDownloadsBtn").addEventListener("click", () => fetch(`/open/${encodeURIComponent(state?.download_dir || "")}`));
$("openTranscriptsBtn").addEventListener("click", () => fetch(`/open/${encodeURIComponent(state?.transcript_dir || "")}`));

refresh();
setInterval(refresh, 1500);
