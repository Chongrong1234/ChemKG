/* =====================================================================
 * KG-RAG 电镀文献问答系统 — 前端逻辑
 * 功能：多会话管理 / SSE 流式问答 / 证据卡片与引用联动 / 检索设置
 * ===================================================================== */
"use strict";

/* ---------------- 常量与全局状态 ---------------- */
const $ = (sel) => document.querySelector(sel);
const STORAGE_KEY = "kgrag.chats.v1";
const SETTINGS_KEY = "kgrag.settings.v1";
const LLM_KEY = "kgrag.llm.v1";

const state = {
  chats: [],          // [{id, title, messages: [{role, content, evidence, meta, reasoning}]}]
  currentId: null,
  busy: false,
  abort: null,
  settings: {
    strategy: "kg",
    topk: 8,
    subject: "",
    thinking: true,
    showReasoning: true,
    collapseEvidence: true,
    webSearch: true,
  },
  llm: { baseUrl: "", apiKey: "", model: "" },   // 用户自带模型接口（空 = 服务端默认）
};

/* ---------------- 会话持久化 ---------------- */
function loadChats() {
  try { state.chats = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]"); }
  catch { state.chats = []; }
}
function saveChats() {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state.chats.slice(-30))); }
  catch { /* 存储满时静默失败 */ }
}
function loadSettings() {
  try { Object.assign(state.settings, JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}")); }
  catch { /* 使用默认 */ }
}
function saveSettings() {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(state.settings));
}
function loadLlm() {
  try { Object.assign(state.llm, JSON.parse(localStorage.getItem(LLM_KEY) || "{}")); }
  catch { /* 使用默认 */ }
}
function saveLlm() {
  try { localStorage.setItem(LLM_KEY, JSON.stringify(state.llm)); } catch { /* 静默 */ }
}
/** 组装用户级 LLM 配置（全空返回 null，走服务端默认） */
function llmOverride() {
  const o = {};
  if (state.llm.baseUrl.trim()) o.base_url = state.llm.baseUrl.trim();
  if (state.llm.apiKey.trim()) o.api_key = state.llm.apiKey.trim();
  if (state.llm.model.trim()) o.model = state.llm.model.trim();
  return Object.keys(o).length ? o : null;
}

/* ---------------- 工具函数 ---------------- */
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/** 将答案文本渲染为 HTML：转义 -> 轻量 markdown -> 引用徽标 */
function renderAnswer(text, evidenceMap) {
  let html = esc(text);
  // 代码块（少见于本域，但保留）
  html = html.replace(/```([\s\S]*?)```/g, (_, code) =>
    `<pre style="background:#f4f7fb;padding:8px 10px;border-radius:6px;overflow-x:auto;font-size:12.5px;margin:6px 0">${code}</pre>`);
  html = html.replace(/`([^`\n]+)`/g, "<code style='background:#eef2f7;padding:1px 5px;border-radius:4px;font-size:.9em'>$1</code>");
  // 粗体 / 斜体
  html = html.replace(/\*\*([^*\n]+)\*\*/g, "<b>$1</b>");
  html = html.replace(/(^|\s)\*([^*\n]+)\*(?=\s|$)/g, "$1<i>$2</i>");
  // 引用徽标 [ev_xxx] / [web_xxx] 或 [1]
  html = html.replace(/\[(ev_[0-9a-f]{6,}|web_[0-9a-z]{4,}|\d{1,2})\]/g, (_, key) => {
    let idx = null;
    if (/^ev_|^web_/.test(key)) {
      idx = (evidenceMap || {}).indexById[key];
    } else {
      idx = parseInt(key, 10) - 1;
    }
    if (idx === undefined || idx === null || idx < 0) return `[${key}]`;
    const short = /^ev_|^web_/.test(key) ? key.slice(0, 8) : key;
    return `<span class="cite${/^web_/.test(key) ? " web" : ""}" data-ev-idx="${idx}">[${short}]</span>`;
  });
  return html;
}

function scrollToBottom(force = false) {
  const box = $("#messages");
  const near = box.scrollHeight - box.scrollTop - box.clientHeight < 160;
  if (force || near) box.scrollTop = box.scrollHeight;
}

/* ---------------- 元信息加载 ---------------- */
async function loadMeta() {
  try {
    const res = await fetch("/api/meta");
    const meta = await res.json();
    $("#chip-evidence").textContent = `${meta.evidence_count.toLocaleString()} 证据 · ${meta.document_count} 文献`;
    $("#chip-model").textContent = meta.llm_enabled ? `模型 ${meta.llm_model}` : "LLM 未配置";
  } catch {
    $("#chip-evidence").textContent = "服务未连接";
  }
  try {
    const res = await fetch("/api/llm/defaults");
    const d = await res.json();
    // 仅填充 placeholder（不覆盖用户已保存的值），并在自带配置时更新顶栏模型名
    $("#set-llm-base").placeholder = d.base_url || "https://api.epicllmrouter.top/v1";
    $("#set-llm-model").placeholder = d.model || "";
    $("#set-llm-key").placeholder = d.has_key ? `留空使用服务端默认 Key（${d.key_hint}）` : "服务端未配置 Key，请填写";
    if (state.llm.model.trim()) $("#chip-model").textContent = `模型 ${state.llm.model.trim()}（自带）`;
  } catch { /* 无默认信息时保持原 placeholder */ }
}

/* ---------------- 会话列表渲染 ---------------- */
function renderChatList() {
  const list = $("#chat-list");
  list.innerHTML = "";
  state.chats.forEach((chat) => {
    const item = document.createElement("div");
    item.className = "chat-item" + (chat.id === state.currentId ? " active" : "");
    item.innerHTML = `<span>💬</span><span class="chat-title">${esc(chat.title)}</span>
      <button class="chat-del" title="删除对话">✕</button>`;
    item.querySelector(".chat-title").addEventListener("click", () => switchChat(chat.id));
    item.addEventListener("click", (e) => {
      if (!e.target.classList.contains("chat-del")) switchChat(chat.id);
    });
    item.querySelector(".chat-del").addEventListener("click", (e) => {
      e.stopPropagation();
      deleteChat(chat.id);
    });
    list.appendChild(item);
  });
}

function currentChat() {
  return state.chats.find((c) => c.id === state.currentId);
}

function newChat() {
  const chat = { id: Date.now().toString(36), title: "新对话", messages: [] };
  state.chats.unshift(chat);
  state.currentId = chat.id;
  saveChats(); renderChatList(); renderMessages();
}

function switchChat(id) {
  state.currentId = id;
  saveChats(); renderChatList(); renderMessages();
}

function deleteChat(id) {
  state.chats = state.chats.filter((c) => c.id !== id);
  if (state.currentId === id) state.currentId = state.chats[0]?.id ?? null;
  if (!state.chats.length) newChat(); else { saveChats(); renderChatList(); renderMessages(); }
}

/* ---------------- 消息渲染 ---------------- */
function renderMessages() {
  const box = $("#messages");
  const chat = currentChat();
  const welcome = $("#welcome");
  const msgs = chat ? chat.messages : [];

  welcome.style.display = msgs.length ? "none" : "";

  // 清除旧消息节点（保留欢迎屏）
  box.querySelectorAll(".msg-row").forEach((n) => n.remove());

  msgs.forEach((m, i) => box.appendChild(buildMessageNode(m, i)));
  scrollToBottom(true);
}

function buildMessageNode(msg, idxInChat) {
  const row = document.createElement("div");
  row.className = "msg-row";
  const wrap = document.createElement("div");
  wrap.className = "msg " + msg.role;
  wrap.appendChild(Object.assign(document.createElement("div"), { className: "avatar", textContent: msg.role === "user" ? "🧑" : "⚡" }));

  const bubble = document.createElement("div");
  bubble.className = "bubble";

  if (msg.role === "user") {
    bubble.appendChild(Object.assign(document.createElement("div"),
      { className: "answer-body", textContent: msg.content }));
  } else {
    // 助手消息：agent 过程步骤 + 思考过程 + 正文 + 元信息 + 证据
    if (msg.steps && msg.steps.length) {
      bubble.appendChild(buildAgentSteps(msg.steps, msg.streaming));
    }
    const showReasoning = (state.settings.showReasoning || msg.streaming) && msg.reasoning;
    if (showReasoning) {
      const rb = document.createElement("div");
      rb.className = "reasoning-block" + (msg.streaming ? " live" : "");
      rb.innerHTML = `<span class="reasoning-toggle${msg.streaming ? "" : " open"}" onclick="this.classList.toggle('open');this.nextElementSibling.classList.toggle('show')">${msg.streaming ? "🧠 思考中…" : "思考过程"}</span>
        <div class="reasoning-body${msg.streaming ? " show" : ""}">${esc(msg.reasoning)}${msg.streaming ? '<span class="typing-cursor"></span>' : ""}</div>`;
      bubble.appendChild(rb);
    }
    const body = document.createElement("div");
    body.className = "answer-body";
    const evMap = buildEvidenceMap(msg.evidence);
    body.innerHTML = renderAnswer(msg.content || "", evMap) + (msg.streaming ? '<span class="typing-cursor"></span>' : "");
    bubble.appendChild(body);

    if (msg.meta) {
      const metaLine = document.createElement("div");
      metaLine.className = "meta-line";
      const parts = [];
      parts.push(`<span class="meta-badge">策略 ${esc(msg.meta.strategy || "-")}</span>`);
      parts.push(`<span class="meta-badge">检索 ${Math.round(msg.meta.retrieval_ms || 0)} ms</span>`);
      if (msg.meta.web_search) {
        parts.push(`<span class="meta-badge web">🌐 本地 ${msg.meta.local_count ?? 0} + 期刊 ${msg.meta.web_count ?? 0}</span>`);
      }
      if (msg.meta.generation_ms) parts.push(`<span class="meta-badge">生成 ${Math.round(msg.meta.generation_ms)} ms</span>`);
      if (msg.meta.model) parts.push(`<span class="meta-badge">${esc(msg.meta.model)}</span>`);
      if (msg.meta.abstained) parts.push(`<span class="meta-badge abstain">已弃答：证据不足</span>`);
      metaLine.innerHTML = parts.join("");
      bubble.appendChild(metaLine);
    }

    if (msg.evidence && msg.evidence.length) {
      bubble.appendChild(buildEvidencePanel(msg.evidence));
    } else if (msg.role === "assistant" && msg.meta && msg.meta.loaded && !msg.evidence?.length) {
      const none = document.createElement("div");
      none.className = "meta-line";
      none.innerHTML = `<span class="meta-badge abstain">知识库未检索到相关证据</span>`;
      bubble.appendChild(none);
    }
  }
  wrap.appendChild(bubble);
  row.appendChild(wrap);
  return row;
}

function buildEvidenceMap(evidence) {
  const map = { indexById: {} };
  (evidence || []).forEach((ev, i) => { map.indexById[ev.evidence_id] = i; });
  return map;
}

/* ---------------- Agent 过程步骤面板（CoT 流程展示） ---------------- */
function stepLine(st) {
  const icon = { local: "🔍", web_query: "🌐", web: "🌐", generate: "🧠" }[st.step] || "•";
  if (st.step === "local") {
    if (st.status === "start") return `${icon} 检索本地知识库…`;
    return `${icon} 本地知识库检索 · ${st.count} 条证据 · ${Math.round(st.ms || 0)} ms`;
  }
  if (st.step === "web_query") {
    return `${icon} 生成英文检索式 "${esc(st.query)}" · ${Math.round(st.ms || 0)} ms`;
  }
  if (st.step === "web") {
    if (st.status === "skipped") return `${icon} 联网检索已跳过 · ${esc(st.reason || "")}`;
    if (st.status === "empty") return `${icon} 联网检索无结果 · 检索式 "${esc(st.query || "")}"`;
    const js = (st.journals || []).length;
    return `${icon} 联网检索 ${st.count} 篇文献 · ${js} 本期刊 · ${Math.round(st.ms || 0)} ms`;
  }
  if (st.step === "generate") {
    return `${icon} 综合分析 ${st.evidence_total} 条证据（本地 ${st.local} + 网络 ${st.web}）生成答案…`;
  }
  return `${icon} ${esc(st.step)} ${st.status || ""}`;
}

function buildAgentSteps(steps, streaming) {
  const box = document.createElement("div");
  box.className = "agent-steps" + (streaming ? " live" : "");
  const title = document.createElement("div");
  title.className = "steps-title";
  title.textContent = streaming ? "🤖 正在工作…" : "🤖 检索与分析过程";
  const list = document.createElement("div");
  list.className = "steps-list";
  steps.forEach((st) => {
    const el = document.createElement("div");
    el.className = "step" + (st.status === "start" ? " running" : "");
    el.innerHTML = stepLine(st);
    list.appendChild(el);
  });
  box.appendChild(title);
  box.appendChild(list);
  return box;
}

function buildEvidencePanel(evidence) {
  const panel = document.createElement("div");
  panel.className = "evidence-panel";

  const localCount = evidence.filter((ev) => ev.source !== "web").length;
  const webCount = evidence.length - localCount;
  const countText = webCount
    ? `📎 ${evidence.length} 条证据（本地 ${localCount} · 联网 ${webCount}）`
    : `📎 检索到 ${evidence.length} 条证据`;

  const toggle = document.createElement("div");
  toggle.className = "evidence-toggle" + (state.settings.collapseEvidence ? " collapsed" : "");
  toggle.textContent = ` ${countText}`;
  const list = document.createElement("div");
  list.className = "evidence-list" + (state.settings.collapseEvidence ? " hidden" : "");
  toggle.addEventListener("click", () => {
    toggle.classList.toggle("collapsed");
    list.classList.toggle("hidden");
  });
  panel.appendChild(toggle);

  evidence.forEach((ev, i) => {
    const card = document.createElement("div");
    card.className = "ev-card" + (ev.source === "web" ? " web" : "");
    card.dataset.evIdx = i;
    if (ev.source === "web") {
      // ---- 联网期刊文献卡片 ----
      const authors = (ev.authors || []).slice(0, 3).join(", ") + ((ev.authors || []).length > 3 ? ", et al." : "");
      const authorTags = authors ? `<span class="ev-tag author">${esc(authors)}</span>` : "";
      const doiTag = ev.doi ? `<a class="ev-tag doi" href="https://doi.org/${encodeURIComponent(ev.doi)}" target="_blank" rel="noopener" title="打开原文">DOI: ${esc(ev.doi.length > 28 ? ev.doi.slice(0, 26) + "…" : ev.doi)}</a>` : "";
      card.innerHTML = `
        <div class="ev-head">
          <span class="ev-index">${i + 1}</span>
          <a class="ev-title ev-link" href="${esc(ev.path || (ev.doi ? "https://doi.org/" + ev.doi : "#"))}" target="_blank" rel="noopener" title="${esc(ev.title)}">🌐 ${esc(ev.journal || "Web")}${ev.year ? ` · ${ev.year}` : ""} — ${esc(ev.title.length > 52 ? ev.title.slice(0, 52) + "…" : ev.title)}</a>
          <span class="ev-id">web</span>
        </div>
        <div class="ev-body">${esc(ev.text)}</div>
        <div class="ev-tags">${authorTags}${doiTag}</div>`;
    } else {
      // ---- 本地知识库证据卡片 ----
      const predTags = (ev.predicates || []).map((p) =>
        `<span class="ev-tag pred">${esc(p)}</span>`).join("");
      const entTags = [...new Set(ev.entities || [])].slice(0, 6).map((e) =>
        `<span class="ev-tag">${esc(e)}</span>`).join("");
      const graphTag = ev.graph_expansion ? `<span class="ev-tag graph">图扩展</span>` : "";
      const neighbors = (ev.neighbors || []).map((n) =>
        `<div>· L${n.line_no} ${esc(n.text.slice(0, 160))}${n.text.length > 160 ? "…" : ""}</div>`).join("");
      card.innerHTML = `
        <div class="ev-head">
          <span class="ev-index">${i + 1}</span>
          <span class="ev-title" title="${esc(ev.title)}">📄 ${esc(ev.title || ev.doc_id)}</span>
          <span class="ev-id">${esc(ev.evidence_id.slice(0, 11))}</span>
          <span class="ev-score">score ${Number(ev.score).toFixed(2)}</span>
        </div>
        <div class="ev-body">${esc(ev.text)}</div>
        <div class="ev-tags">${predTags}${entTags}${graphTag}</div>
        ${neighbors ? `<div class="ev-neighbors"><details><summary>上下文窗口（${ev.neighbors.length} 行）</summary>${neighbors}</details></div>` : ""}`;
    }
    list.appendChild(card);
  });
  panel.appendChild(list);
  return panel;
}

/* ---------------- 引用徽标点击 -> 高亮证据卡片 ---------------- */
document.addEventListener("click", (e) => {
  const cite = e.target.closest(".cite");
  if (!cite) return;
  const idx = parseInt(cite.dataset.evIdx, 10);
  document.querySelectorAll(".ev-card.highlight, .cite.active").forEach((n) =>
    n.classList.remove("highlight", "active"));
  const panel = cite.closest(".bubble")?.querySelector(".evidence-panel");
  if (!panel) return;
  const list = panel.querySelector(".evidence-list");
  const toggle = panel.querySelector(".evidence-toggle");
  if (list.classList.contains("hidden")) { toggle.classList.remove("collapsed"); list.classList.remove("hidden"); }
  const card = list.querySelector(`.ev-card[data-ev-idx="${idx}"]`);
  if (card) {
    card.classList.add("highlight");
    card.scrollIntoView({ behavior: "smooth", block: "center" });
    setTimeout(() => card.classList.remove("highlight"), 2200);
  }
});

/* ---------------- 流式问答请求 ---------------- */
async function ask(question) {
  const chat = currentChat();
  if (!chat) return;

  chat.messages.push({ role: "user", content: question });
  const reply = { role: "assistant", content: "", reasoning: "", evidence: [], steps: [], meta: null, streaming: true };
  chat.messages.push(reply);
  if (chat.messages.length === 1 || chat.title === "新对话") {
    chat.title = question.slice(0, 18) + (question.length > 18 ? "…" : "");
  }
  saveChats(); renderChatList(); renderMessages();
  setBusy(true);

  const history = chat.messages.slice(0, -2)
    .filter((m) => m.role === "user" || m.content)
    .slice(-3)
    .map((m) => ({ question: m.role === "user" ? m.content : "", answer: m.role === "assistant" ? m.content : "" }));

  const body = {
    question,
    strategy: state.settings.strategy,
    topk: state.settings.topk,
    window: 1,
    history,
    thinking: state.settings.thinking,
    web_search: state.settings.webSearch,
  };
  if (state.settings.subject && state.settings.strategy === "anchored") {
    body.subject = state.settings.subject;
  }
  const llm = llmOverride();
  if (llm) body.llm = llm;

  const controller = new AbortController();
  state.abort = controller;

  try {
    const res = await fetch("/api/ask/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let sawEvidence = false;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      // 部分反向代理（如 frpc 的 HTTPS 反代）会把 SSE 换行规范化为 CRLF，
      // 统一归一为 LF，保证下方 "\n\n" 帧分隔与行解析稳定工作
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");

      // 解析 SSE 帧：event: X\ndata: Y\n\n
      let frameEnd;
      while ((frameEnd = buffer.indexOf("\n\n")) >= 0) {
        const raw = buffer.slice(0, frameEnd);
        buffer = buffer.slice(frameEnd + 2);
        const evLine = raw.split("\n").find((l) => l.startsWith("event:"));
        const dataLines = raw.split("\n").filter((l) => l.startsWith("data:"));
        if (!evLine || !dataLines.length) continue;
        const event = evLine.slice(6).trim();
        const data = dataLines.map((l) => l.slice(5).replace(/^ /, "")).join("\n");

        if (event === "evidence") {
          try { reply.evidence = JSON.parse(data); sawEvidence = true; } catch { /* 忽略坏帧 */ }
        } else if (event === "status") {
          try { reply.steps.push(JSON.parse(data)); } catch { /* 忽略坏帧 */ }
        } else if (event === "reasoning") {
          reply.reasoning += data;
        } else if (event === "content") {
          reply.content += data;
        } else if (event === "done") {
          try {
            const done = JSON.parse(data);
            Object.assign(reply, { content: reply.content || done.answer, meta: { ...done, loaded: true } });
          } catch { /* 忽略坏帧 */ }
        }
        // 增量刷新 DOM
        const lastRow = $("#messages").lastElementChild;
        if (lastRow) {
          const fresh = buildMessageNode({ ...reply, streaming: event !== "done" }, chat.messages.length - 1);
          lastRow.replaceWith(fresh);
          scrollToBottom();
        }
      }
    }
    reply.streaming = false;
    if (!reply.meta) reply.meta = { loaded: true, strategy: state.settings.strategy };
    if (!sawEvidence && !reply.evidence.length && !reply.content) {
      reply.content = "（服务连接中断，请重试）";
    }
  } catch (err) {
    reply.streaming = false;
    if (!reply.content) reply.content = `请求失败：${err.message}`;
    if (!reply.meta) reply.meta = { loaded: true, strategy: state.settings.strategy };
  } finally {
    saveChats();
    renderMessages();
    setBusy(false);
    state.abort = null;
  }
}

function setBusy(busy) {
  state.busy = busy;
  $("#btn-send").disabled = busy;
  $("#input").disabled = false;
  $("#btn-send").textContent = busy ? "■" : "➤";
  $("#btn-send").title = busy ? "停止生成" : "发送 (Enter)";
}

/* ---------------- 设置面板 ---------------- */
const STRATEGY_DESC = {
  lexical: "仅词法匹配，速度最快",
  kg: "词法 + 实体/关系/数值加权，综合最优（推荐）",
  anchored: "指明材料名时用，主体证据大幅提权",
  graph: "沿谓词与共享实体扩展更多相关证据",
};

function openSettings() {
  const s = state.settings;
  $("#set-strategy").value = s.strategy;
  $("#set-topk").value = s.topk;
  $("#topk-val").textContent = s.topk;
  $("#set-subject").value = s.subject;
  $("#set-thinking").checked = s.thinking;
  $("#set-show-reasoning").checked = s.showReasoning;
  $("#set-collapse-evidence").checked = s.collapseEvidence;
  $("#set-web-search").checked = s.webSearch;
  $("#strategy-desc").textContent = STRATEGY_DESC[s.strategy] || "";
  $("#set-llm-base").value = state.llm.baseUrl;
  $("#set-llm-key").value = state.llm.apiKey;
  $("#set-llm-model").value = state.llm.model;
  setLlmTestResult("", "");
  $("#settings").classList.remove("hidden");
  $("#settings-mask").classList.remove("hidden");
}

function closeSettings() {
  $("#settings").classList.add("hidden");
  $("#settings-mask").classList.add("hidden");
}

function applySettings() {
  state.settings.strategy = $("#set-strategy").value;
  state.settings.topk = parseInt($("#set-topk").value, 10);
  state.settings.subject = $("#set-subject").value.trim();
  state.settings.thinking = $("#set-thinking").checked;
  state.settings.showReasoning = $("#set-show-reasoning").checked;
  state.settings.collapseEvidence = $("#set-collapse-evidence").checked;
  state.settings.webSearch = $("#set-web-search").checked;
  state.llm = {
    baseUrl: $("#set-llm-base").value.trim(),
    apiKey: $("#set-llm-key").value.trim(),
    model: $("#set-llm-model").value.trim(),
  };
  saveSettings();
  saveLlm();
  updateTopbarStrategy();
  loadMeta(); // 自带模型名时刷新顶栏
  closeSettings();
  renderMessages(); // 思考过程显隐即时生效
}

/* ---------------- 模型接口连接测试 ---------------- */
function setLlmTestResult(text, cls) {
  const el = $("#llm-test-result");
  el.textContent = text;
  el.className = "llm-test-result " + (cls || "");
}

async function testLlmConnection() {
  const btn = $("#btn-llm-test");
  const payload = {};
  const base = $("#set-llm-base").value.trim();
  const key = $("#set-llm-key").value.trim();
  const model = $("#set-llm-model").value.trim();
  if (base) payload.base_url = base;
  if (key) payload.api_key = key;
  if (model) payload.model = model;

  btn.disabled = true;
  setLlmTestResult("测试中…", "pending");
  try {
    const res = await fetch("/api/llm/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const r = await res.json();
    if (r.ok) {
      setLlmTestResult(`✓ 连接成功 · ${r.model} · ${Math.round(r.latency_ms)} ms`, "ok");
    } else {
      setLlmTestResult(`✗ ${r.error || "连接失败"}`, "fail");
    }
  } catch (err) {
    setLlmTestResult(`✗ ${err.message}`, "fail");
  } finally {
    btn.disabled = false;
  }
}

function updateTopbarStrategy() {
  const names = { lexical: "BM25", kg: "KG 增强", anchored: "主体锚定", graph: "图扩展" };
  $("#topbar-strategy").textContent = `策略：${names[state.settings.strategy] || state.settings.strategy} · top-${state.settings.topk}`;
}

/* ---------------- 事件绑定 ---------------- */
function bindEvents() {
  $("#btn-new-chat").addEventListener("click", () => { if (!state.busy) newChat(); });
  $("#btn-settings").addEventListener("click", openSettings);
  $("#btn-close-settings").addEventListener("click", closeSettings);
  $("#settings-mask").addEventListener("click", closeSettings);
  $("#btn-save-settings").addEventListener("click", applySettings);
  $("#btn-llm-test").addEventListener("click", testLlmConnection);
  $("#set-strategy").addEventListener("change", (e) => {
    $("#strategy-desc").textContent = STRATEGY_DESC[e.target.value] || "";
  });
  $("#set-topk").addEventListener("input", (e) => { $("#topk-val").textContent = e.target.value; });

  $("#btn-toggle-sidebar").addEventListener("click", () => $("#sidebar").classList.toggle("collapsed"));

  const input = $("#input");
  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 160) + "px";
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendCurrent(); }
  });
  $("#btn-send").addEventListener("click", () => {
    if (state.busy && state.abort) { state.abort.abort(); return; }
    sendCurrent();
  });

  document.querySelectorAll(".example-card").forEach((card) => {
    card.addEventListener("click", () => { $("#input").value = card.dataset.q; sendCurrent(); });
  });
}

function sendCurrent() {
  if (state.busy) return;
  const q = $("#input").value.trim();
  if (q.length < 2) return;
  $("#input").value = "";
  $("#input").style.height = "auto";
  $("#welcome").style.display = "none";
  ask(q);
}

/* ---------------- 启动 ---------------- */
(function init() {
  loadChats(); loadSettings(); loadLlm(); bindEvents();
  if (!state.chats.length) newChat(); else switchChat(state.chats[0].id);
  updateTopbarStrategy();
  loadMeta();
})();
