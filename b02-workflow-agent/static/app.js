const $ = (selector) => document.querySelector(selector);
const state = { workflow: null, runs: [], run: null, replay: null, tab: "control", busy: false };
const scenarioNames = { normal: "正常收敛", value_conflict: "价值分歧", budget_exhaustion: "预算耗尽", agent_failure: "Agent 失败" };
const statusNames = { READY: "可推进", RUNNING: "执行中", WAITING_HUMAN: "等待人工", PAUSED: "已暂停", STOPPED: "预算停止", BLOCKED: "已阻断", COMPLETED: "已完成" };
let toastTimer;

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
}
function tags(value) {
  return `<span class="tag ${escapeHtml(value)}">${escapeHtml(value)}</span>`;
}
async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `请求失败（HTTP ${response.status}）`);
  return data;
}
function showError(error) {
  $("#global-error-text").textContent = error.message || String(error);
  $("#global-error").classList.remove("hidden");
}
function clearError() { $("#global-error").classList.add("hidden"); }
function toast(message) {
  clearTimeout(toastTimer);
  $("#toast").textContent = message;
  $("#toast").classList.remove("hidden");
  toastTimer = setTimeout(() => $("#toast").classList.add("hidden"), 3200);
}
function setBusy(value) {
  state.busy = value;
  $("#start-button").disabled = value;
  $("#start-button").textContent = value ? "正在创建运行…" : "启动讨论 Workflow";
  if (state.run) renderControls();
}

async function loadWorkflow() {
  const data = await api("/api/workflow");
  state.workflow = data;
  renderWorkflowSteps();
}
async function loadRuns() {
  const data = await api("/api/runs");
  state.runs = data.runs;
  const container = $("#run-history");
  if (!state.runs.length) {
    container.innerHTML = '<p class="empty-history">暂无运行，创建一个开始验收。</p>';
    return;
  }
  container.innerHTML = state.runs.map((run) => `<button type="button" data-run-id="${escapeHtml(run.run_id)}" class="${state.run?.run_id === run.run_id ? "active" : ""}" title="${escapeHtml(run.idea)}"><strong>${escapeHtml(run.idea)}</strong><small>${escapeHtml(run.run_id)} · ${escapeHtml(run.status)}</small></button>`).join("");
}
function renderWorkflowSteps() {
  if (!state.workflow) return;
  const currentIndex = state.run ? state.workflow.stages.findIndex((stage) => stage.id === state.run.stage) : -1;
  $("#workflow-steps").innerHTML = state.workflow.stages.map((stage, index) => {
    const className = index === currentIndex ? "active" : (currentIndex > index ? "complete" : "");
    return `<li class="${className}"><span>${stage.code}</span><div><strong>${escapeHtml(stage.name)}</strong><small>${escapeHtml(stage.id)}</small></div></li>`;
  }).join("");
}
function showInput() {
  state.run = null;
  state.replay = null;
  clearError();
  $("#result-view").classList.add("hidden");
  $("#input-view").classList.remove("hidden");
  renderWorkflowSteps();
  loadRuns().catch(showError);
  $("#idea-input").focus();
}
async function selectRun(runId) {
  clearError();
  const data = await api(`/api/runs/${encodeURIComponent(runId)}`);
  state.run = data.run;
  state.replay = null;
  state.tab = "control";
  renderRun();
}
function renderRun() {
  const run = state.run;
  if (!run) return showInput();
  $("#input-view").classList.add("hidden");
  $("#result-view").classList.remove("hidden");
  $("#run-id").textContent = run.run_id;
  $("#run-title").textContent = run.idea;
  $("#run-subtitle").textContent = `${scenarioNames[run.scenario]} · 更新于 ${run.updated_at}`;
  const board = run.blackboard;
  const openCount = board.objections.filter((item) => item.status === "open").length;
  $("#metric-stage").textContent = run.stage;
  $("#metric-status").textContent = statusNames[run.status] || run.status;
  $("#metric-status").className = `status-${run.status}`;
  $("#metric-round").textContent = `${run.round} / ${run.max_rounds}`;
  $("#metric-objections").textContent = openCount;
  $("#metric-events").textContent = run.events.length;
  renderWorkflowSteps();
  renderControls();
  renderTabs();
  renderTabContent();
  loadRuns().catch(showError);
}
function renderControls() {
  const run = state.run;
  if (!run) return;
  const canAdvance = !state.busy && run.status === "READY" && !["HUMAN_CONFIRMATION", "COMPLETED"].includes(run.stage);
  $("#step-button").disabled = !canAdvance;
  $("#until-button").disabled = !canAdvance;
  $("#pause-button").disabled = state.busy || !["READY", "PAUSED"].includes(run.status);
  $("#pause-button").textContent = run.status === "PAUSED" ? "恢复运行" : "暂停";
  $("#export-json").disabled = state.busy;
  $("#export-markdown").disabled = state.busy;
  $("#step-button").textContent = state.busy ? "执行中…" : "推进一阶段";
}
function renderTabs() {
  document.querySelectorAll("[data-tab]").forEach((button) => {
    const active = button.dataset.tab === state.tab;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  });
}
function stageDetails() {
  return state.workflow.stages.find((stage) => stage.id === state.run.stage);
}
function renderControl() {
  const run = state.run;
  const board = run.blackboard;
  const stage = stageDetails();
  const verdict = run.latest_consensus;
  let alert = "";
  if (run.status === "WAITING_HUMAN" && ["EVALUATE", "PROPOSAL_REVIEW"].includes(run.stage)) {
    alert = `<div class="control-alert"><h3>需要人类裁决，自动控制已停下</h3><p>${escapeHtml(verdict?.reason || "存在高影响价值分歧。")}</p><form id="decision-form" class="human-form"><label class="field-label" for="decision-input">裁决内容与理由</label><textarea id="decision-input" required minlength="3" placeholder="例如：首期优先隐私和可控成本，理由是……"></textarea><button class="primary-button" type="submit" ${state.busy ? "disabled" : ""}>记录裁决并解锁流程</button></form></div>`;
  } else if (run.stage === "HUMAN_CONFIRMATION") {
    const draft = board.requirements_draft;
    alert = `<div class="control-alert"><h3>B01 六人需求确认门槛</h3><p>每人分别确认才有效；沉默、Pending 或只勾选部分成员均不能发布 R1。</p><div class="requirement-list">${draft.requirements.map((req) => `<div class="requirement-item"><strong>${escapeHtml(req.req_id)} · ${escapeHtml(req.description)}</strong><p>验收：${escapeHtml(req.acceptance)} · ${escapeHtml(req.priority)}</p></div>`).join("")}</div><form id="confirm-form"><div class="member-grid">${state.workflow.members.map((member) => `<label class="check-member"><input type="checkbox" name="member" value="${escapeHtml(member)}"><span>${escapeHtml(member)}确认</span></label>`).join("")}</div><p class="field-note">已确认 <span id="member-count">0</span> / 6 人</p><p id="confirm-error" class="field-note" role="alert"></p><button class="primary-button" type="submit" ${state.busy ? "disabled" : ""}>校验六人确认并发布 R1</button></form></div>`;
  } else if (run.status === "STOPPED") {
    alert = '<div class="control-alert danger"><h3>已达到控制预算，流程停止</h3><p>停止不等于共识。开放异议仍被保留，未生成 R1，也不能进入六人确认。</p></div>';
  } else if (run.status === "BLOCKED") {
    alert = `<div class="control-alert danger"><h3>执行失败，已阻断</h3><p>${escapeHtml(run.failure?.message || "角色调用失败")}</p><p>失败阶段：${escapeHtml(run.failure?.stage || run.stage)}。系统没有伪造观点、评价或后续迁移。</p></div>`;
  } else if (run.status === "PAUSED") {
    alert = '<div class="control-alert"><h3>已在检查点暂停</h3><p>恢复前不会派发新角色任务；已有黑板和事件均已保留。</p></div>';
  } else if (run.status === "COMPLETED") {
    alert = `<div class="control-alert success"><h3>R1 已由六人确认发布</h3><p>确认人：${board.r1.confirmed_by.map(escapeHtml).join("、")}。流程、需求与回放日志可以导出。</p></div>`;
  }
  const signoffs = board.signoffs.length ? `<div class="subsection"><h3>Proposal 角色 sign-off</h3><div class="table-wrap"><table><thead><tr><th>角色</th><th>立场</th><th>理由</th></tr></thead><tbody>${board.signoffs.map((item) => `<tr><td>${escapeHtml(item.role)}</td><td>${tags(item.stance)}</td><td>${escapeHtml(item.reason)}</td></tr>`).join("")}</tbody></table></div></div>` : "";
  const r1 = board.r1 ? `<div class="subsection"><h3>已确认 R1</h3><div class="requirement-list">${board.r1.requirements.map((req) => `<div class="requirement-item"><strong>${escapeHtml(req.req_id)} · ${escapeHtml(req.description)} ${tags(req.status)}</strong><p>验收：${escapeHtml(req.acceptance)}</p></div>`).join("")}</div></div>` : "";
  return `${alert}<div class="control-grid"><section class="control-section"><span class="stage-code">${stage.code}</span><h3>${escapeHtml(stage.name)}</h3><p><code>${escapeHtml(stage.id)}</code> · ${escapeHtml(stage.owner)}</p><p>${escapeHtml(stage.action)}</p></section><section class="control-section"><h3>B06 最近评价</h3>${verdict ? `<p>${escapeHtml(verdict.reason)}</p><p>开放异议：<strong>${verdict.open_count ?? "—"}</strong>　高影响：<strong>${verdict.high_count ?? "—"}</strong></p><p>needs_human：${tags(String(Boolean(verdict.needs_human)))}　can_proceed：${tags(String(Boolean(verdict.can_proceed)))}</p>` : '<p>尚未执行共识评价。B02 不会提前推断评价结果。</p>'}</section></div>${signoffs}${r1}`;
}
function renderBlackboard() {
  const board = state.run.blackboard;
  const claims = board.claims.length ? board.claims.map((item) => `<article class="record-card"><header><span class="id-text">${escapeHtml(item.claim_id)}</span><h4>${escapeHtml(item.role)}</h4>${tags(`round ${item.round}`)}</header><p>${escapeHtml(item.claim)}</p><p><strong>理由：</strong>${escapeHtml(item.reason)}</p><p><strong>证据：</strong>${escapeHtml(item.evidence)}</p><p><strong>影响：</strong>${escapeHtml(item.impact)}</p></article>`).join("") : '<div class="empty-state">尚无观点。执行独立发散后，四个角色的候选输出会写入黑板。</div>';
  const objections = board.objections.length ? board.objections.map((item) => `<article class="record-card"><header><span class="id-text">${escapeHtml(item.objection_id)}</span><h4>${escapeHtml(item.raised_by)} → ${escapeHtml(item.target_id)}</h4>${tags(item.category)}${tags(item.severity)}${tags(item.status)}</header><p>${escapeHtml(item.content)}</p><p><strong>证据：</strong>${escapeHtml(item.evidence)}</p><p><strong>回应：</strong>${escapeHtml(item.response || "尚未回应")}${item.resolution_ref ? ` · ${escapeHtml(item.resolution_ref)}` : ""}</p></article>`).join("") : '<div class="empty-state">暂无异议记录。</div>';
  const decisions = board.decisions.length ? board.decisions.map((item) => `<article class="record-card"><header><span class="id-text">${escapeHtml(item.decision_id)}</span><h4>${escapeHtml(item.decided_by)}</h4></header><p>${escapeHtml(item.content)}</p><p>${escapeHtml(item.time)}</p></article>`).join("") : '<div class="empty-state">尚无人工裁决。价值取向分歧不会被模型投票替代。</div>';
  const proposal = board.proposal_draft ? `<div class="subsection"><h3>Proposal 草案</h3><div class="proposal">${escapeHtml(board.proposal_draft)}</div></div>` : "";
  return `<div class="panel-toolbar"><div><h3>独立观点</h3><p>发散阶段互不可见；原始意见不会被“多数票”抹掉。</p></div><span class="source-label">${board.claims.length} CLAIMS</span></div><div class="card-list">${claims}</div><div class="subsection"><h3>异议与处理状态</h3><div class="card-list">${objections}</div></div><div class="subsection"><h3>人类裁决记录</h3><div class="card-list">${decisions}</div></div><div class="subsection"><h3>未决问题</h3>${board.open_questions.length ? `<ul>${board.open_questions.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : '<p class="empty-state">暂无未决问题。</p>'}</div>${proposal}`;
}
function renderDesign() {
  return `<div class="panel-toolbar"><div><h3>阶段迁移表</h3><p>迁移由事件与守卫条件共同决定，评价结果本身不直接改状态。</p></div><span class="source-label">11 RULES</span></div><div class="table-wrap"><table><thead><tr><th>当前阶段</th><th>事件</th><th>守卫条件</th><th>下一状态</th></tr></thead><tbody>${state.workflow.transitions.map((item) => `<tr><td><code>${escapeHtml(item.from)}</code></td><td>${escapeHtml(item.event)}</td><td>${escapeHtml(item.guard)}</td><td><code>${escapeHtml(item.to)}</code></td></tr>`).join("")}</tbody></table></div><div class="subsection"><h3>discussion_controller 控制伪代码</h3><pre class="pseudocode">${escapeHtml(state.workflow.pseudocode)}</pre></div>`;
}
function renderReplay() {
  const replay = state.replay;
  if (!replay) return '<div class="empty-state">正在读取有序事件并校验检查点…</div>';
  return `<div class="replay-summary ${replay.passed ? "" : "failed"}"><strong>${replay.passed ? "✓ 回放校验通过" : "回放校验失败"}</strong><span>${replay.event_count} 个连续事件；回放控制状态与当前 checkpoint ${replay.passed ? "一致" : "不一致"}。</span></div><div class="table-wrap"><table><thead><tr><th>序号</th><th>事件 ID</th><th>事件类型</th><th>阶段</th><th>状态</th><th>轮次</th></tr></thead><tbody>${replay.timeline.map((event) => `<tr><td>${event.sequence}</td><td><span class="id-text">${escapeHtml(event.event_id)}</span></td><td>${escapeHtml(event.type)}</td><td><code>${escapeHtml(event.stage)}</code></td><td>${escapeHtml(event.status)}</td><td>${event.round}</td></tr>`).join("")}</tbody></table></div>`;
}
function renderTabContent() {
  if (!state.run) return;
  const renderers = { control: renderControl, blackboard: renderBlackboard, design: renderDesign, replay: renderReplay };
  $("#tab-content").innerHTML = renderers[state.tab]();
}
async function activateTab(tab) {
  state.tab = tab;
  if (tab === "replay") state.replay = null;
  renderTabs();
  renderTabContent();
  if (tab === "replay") {
    const runId = state.run.run_id;
    try {
      const data = await api(`/api/runs/${encodeURIComponent(runId)}/replay`);
      if (state.tab === "replay" && state.run?.run_id === runId) {
        state.replay = data.replay;
        renderTabContent();
      }
    } catch (error) { showError(error); }
  }
}
async function performAction(action, payload = {}) {
  if (!state.run || state.busy) return;
  clearError();
  setBusy(true);
  try {
    const data = await api(`/api/runs/${encodeURIComponent(state.run.run_id)}/${action}`, { method: "POST", body: JSON.stringify(payload) });
    state.run = data.run;
    state.replay = null;
    if (state.tab === "replay") state.tab = "control";
    renderRun();
  } catch (error) { showError(error); }
  finally { setBusy(false); renderControls(); }
}
async function exportRun(format) {
  if (!state.run || state.busy) return;
  clearError();
  setBusy(true);
  try {
    const data = await api(`/api/runs/${encodeURIComponent(state.run.run_id)}/export`, { method: "POST", body: JSON.stringify({ format }) });
    const blob = new Blob([data.content], { type: data.mime });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = data.filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast(`已导出 ${data.filename}`);
  } catch (error) { showError(error); }
  finally { setBusy(false); }
}

$("#new-run").addEventListener("click", showInput);
$("#refresh-runs").addEventListener("click", () => loadRuns().then(() => toast("历史运行已刷新")).catch(showError));
$("#dismiss-error").addEventListener("click", clearError);
$("#run-history").addEventListener("click", (event) => {
  const button = event.target.closest("[data-run-id]");
  if (button) selectRun(button.dataset.runId).catch(showError);
});
$("#idea-input").addEventListener("input", () => { $("#idea-count").textContent = `${$("#idea-input").value.length} / 500`; });
$("#run-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.busy) return;
  clearError();
  setBusy(true);
  try {
    const data = await api("/api/runs", { method: "POST", body: JSON.stringify({ idea: $("#idea-input").value, constraints: $("#constraints-input").value, scenario: $("#scenario-input").value, max_rounds: Number($("#max-rounds").value) }) });
    state.run = data.run;
    state.replay = null;
    state.tab = "control";
    renderRun();
    toast(`已创建 ${data.run.run_id}，请逐阶段或连续推进`);
  } catch (error) { showError(error); }
  finally { setBusy(false); }
});
$("#step-button").addEventListener("click", () => performAction("step"));
$("#until-button").addEventListener("click", () => performAction("until-control-point"));
$("#pause-button").addEventListener("click", () => performAction(state.run?.status === "PAUSED" ? "resume" : "pause"));
$("#export-json").addEventListener("click", () => exportRun("json"));
$("#export-markdown").addEventListener("click", () => exportRun("markdown"));
document.querySelectorAll("[data-tab]").forEach((button) => {
  button.addEventListener("click", () => activateTab(button.dataset.tab));
  button.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    event.preventDefault();
    const tabs = [...document.querySelectorAll("[data-tab]")];
    const offset = event.key === "ArrowRight" ? 1 : -1;
    const next = tabs[(tabs.indexOf(button) + offset + tabs.length) % tabs.length];
    next.focus();
    activateTab(next.dataset.tab);
  });
});
$("#tab-content").addEventListener("change", (event) => {
  if (event.target.matches('input[name="member"]')) {
    $("#member-count").textContent = document.querySelectorAll('input[name="member"]:checked').length;
    $("#confirm-error").textContent = "";
  }
});
$("#tab-content").addEventListener("submit", (event) => {
  event.preventDefault();
  if (event.target.id === "decision-form") {
    performAction("human-decision", { decision: $("#decision-input").value });
  }
  if (event.target.id === "confirm-form") {
    const members = [...document.querySelectorAll('input[name="member"]:checked')].map((input) => input.value);
    if (members.length !== 6) {
      $("#confirm-error").textContent = `当前仅 ${members.length} / 6 人确认，不能发布 R1。`;
      return;
    }
    performAction("confirm", { members });
  }
});

(async function init() {
  $("#idea-count").textContent = `${$("#idea-input").value.length} / 500`;
  try { await Promise.all([loadWorkflow(), loadRuns()]); }
  catch (error) { showError(error); }
})();
