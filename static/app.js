// ============================================================
// 全局状态
// ============================================================
const state = {
  novelId: null,
  chapters: [],
  screenplayId: null,
  yamlText: null,
};

// ============================================================
// DOM 引用
// ============================================================
const $ = (id) => document.getElementById(id);
const uploadZone = $("uploadZone");
const fileInput = $("fileInput");
const uploadStatus = $("uploadStatus");
const chapterList = $("chapterList");
const chapterInfo = $("chapterInfo");
const progressCard = $("progressCard");
const progressFill = $("progressFill");
const progressStage = $("progressStage");
const progressPercent = $("progressPercent");
const yamlOutput = $("yamlOutput");
const outputActions = $("outputActions");
const outputTag = $("outputTag");

// ============================================================
// 上传
// ============================================================

uploadZone.addEventListener("click", () => fileInput.click());
uploadZone.addEventListener("dragover", (e) => { e.preventDefault(); uploadZone.classList.add("drag"); });
uploadZone.addEventListener("dragleave", () => uploadZone.classList.remove("drag"));
uploadZone.addEventListener("drop", (e) => {
  e.preventDefault();
  uploadZone.classList.remove("drag");
  const file = e.dataTransfer.files[0];
  if (file) handleFile(file);
});
fileInput.addEventListener("change", () => {
  const file = fileInput.files[0];
  if (file) handleFile(file);
});

async function handleFile(file) {
  if (!file.name.endsWith(".txt") && !file.name.endsWith(".epub")) {
    uploadStatus.innerHTML = '<span class="tag tag-err">仅支持 .txt 和 .epub 文件</span>';
    return;
  }
  uploadStatus.innerHTML = '<span class="tag tag-info">上传中...</span>';

  const form = new FormData();
  form.append("file", file);

  try {
    const resp = await fetch("/api/novel/upload", { method: "POST", body: form });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "上传失败");

    state.novelId = data.novel_id;
    state.chapters = data.chapters;
    uploadStatus.innerHTML = `<span class="tag tag-ok">已上传：${data.title}（${data.chapter_count} 章）</span>`;
    renderChapters();
  } catch (e) {
    uploadStatus.innerHTML = `<span class="tag tag-err">${e.message}</span>`;
  }
}

// ============================================================
// 章节选择
// ============================================================

function renderChapters() {
  chapterList.innerHTML = state.chapters.map((ch, i) => `
    <div class="chapter-item">
      <input type="checkbox" id="ch_${i}" value="${i}">
      <label for="ch_${i}">${ch.title || "第" + (i+1) + "章"}</label>
      <span class="count">${ch.char_count} 字</span>
    </div>
  `).join("");

  if (state.chapters.length >= 3) {
    // 默认选中前三章
    for (let i = 0; i < 3; i++) {
      const cb = document.querySelector(`#ch_${i}`);
      if (cb) cb.checked = true;
    }
  }

  chapterInfo.innerHTML = '<button class="btn btn-primary" onclick="startExtraction()">🚀 开始转换</button>';
}

// ============================================================
// Stage 1 提取
// ============================================================

async function startExtraction() {
  const selected = [...document.querySelectorAll("#chapterList input:checked")].map(cb => parseInt(cb.value));
  if (selected.length < 3) {
    alert("请至少选择 3 个章节");
    return;
  }

  progressCard.style.display = "block";
  progressFill.style.width = "5%";
  progressStage.textContent = "提交任务...";
  progressPercent.textContent = "5%";

  try {
    const resp = await fetch("/api/extract/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ novel_id: state.novelId, chapter_indexes: selected }),
    });
    const data = await resp.json();
    pollStage1(data.job_id);
  } catch (e) {
    progressStage.textContent = "启动失败: " + e.message;
  }
}

async function pollStage1(jobId) {
  const poll = async () => {
    const resp = await fetch(`/api/extract/${jobId}/status`);
    if (!resp.ok) { setTimeout(poll, 3000); return; }
    const job = await resp.json();

    const pct = (job.progress && job.progress.percent) || 0;
    progressFill.style.width = pct + "%";
    progressStage.textContent = job.progress.detail || job.status;
    progressPercent.textContent = pct + "%";

    if (job.status === "complete") {
      state.screenplayId = job.result?.screenplay_id;
      progressStage.textContent = "Stage 1 完成，开始格式转换...";
      startConversion(state.screenplayId);
    } else if (job.status === "failed") {
      progressStage.textContent = "Stage 1 失败: " + (job.progress.detail || "未知错误");
      setTag("err", "失败");
    } else {
      setTimeout(poll, 3000);
    }
  };
  poll();
}

// ============================================================
// Stage 2 转换
// ============================================================

async function startConversion(screenplayId) {
  if (!screenplayId) {
    progressStage.textContent = "Stage 2 启动失败: 未获取到 screenplay_id，请重新运行 Stage 1";
    setTag("err", "失败");
    return;
  }
  try {
    const resp = await fetch("/api/convert/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ screenplay_id: screenplayId }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      throw new Error(data.detail || "请求失败");
    }
    pollStage2(data.job_id);
  } catch (e) {
    progressStage.textContent = "Stage 2 启动失败: " + e.message;
    setTag("err", "失败");
  }
}

async function pollStage2(jobId) {
  const poll = async () => {
    const resp = await fetch(`/api/convert/${jobId}/status`);
    if (!resp.ok) { setTimeout(poll, 3000); return; }
    const job = await resp.json();

    const pct = (job.progress && job.progress.percent) || 0;
    progressFill.style.width = pct + "%";
    progressStage.textContent = job.progress.detail || job.status;
    progressPercent.textContent = pct + "%";

    if (job.status === "complete") {
      progressStage.textContent = "剧本生成完成！";
      progressFill.style.width = "100%";
      loadScreenplay();
    } else if (job.status === "failed") {
      progressStage.textContent = "Stage 2 失败: " + (job.progress.detail || "未知错误");
      setTag("err", "失败");
    } else {
      setTimeout(poll, 3000);
    }
  };
  poll();
}

// ============================================================
// 预览
// ============================================================

async function loadScreenplay() {
  try {
    const resp = await fetch(`/api/screenplay/${state.screenplayId}?format=yaml`);
    const data = await resp.json();
    state.yamlText = data.yaml;

    // 简单语法高亮
    let html = escapeHtml(state.yamlText);
    html = html
      .replace(/^(\s*\w[\w\s]*?):/gm, '<span class="key">$1</span>:')
      .replace(/:\s*(&gt;|\|)\s*$/gm, ': <span class="string">$1</span>')
      .replace(/:\s*"([^"]*)"$/gm, ': <span class="string">"$1"</span>')
      .replace(/:\s*'([^']*)'$/gm, ': <span class="string">\'$1\'</span>')
      .replace(/^(\s*)#(.*)$/gm, '<span class="comment">$1#$2</span>');

    yamlOutput.className = "yaml-preview";
    yamlOutput.innerHTML = html;
    outputActions.style.display = "flex";
    setTag("ok", "完成");
  } catch (e) {
    yamlOutput.textContent = "加载失败: " + e.message;
    setTag("err", "失败");
  }
}

function downloadYaml() {
  if (!state.yamlText) return;
  const blob = new Blob([state.yamlText], { type: "application/x-yaml" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "screenplay.yaml";
  a.click();
  URL.revokeObjectURL(url);
}

function copyYaml() {
  if (!state.yamlText) return;
  navigator.clipboard.writeText(state.yamlText).then(() => alert("已复制到剪贴板"));
}

// ============================================================
// 工具函数
// ============================================================

function setTag(type, text) {
  const cls = type === "ok" ? "tag-ok" : type === "err" ? "tag-err" : "tag-info";
  outputTag.innerHTML = `<span class="tag ${cls}">${text}</span>`;
}

function escapeHtml(text) {
  const map = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  return text.replace(/[&<>"']/g, c => map[c]);
}
