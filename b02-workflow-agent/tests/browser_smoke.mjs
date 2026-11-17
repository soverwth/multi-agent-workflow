import { spawn } from "node:child_process";
import { mkdir, readFile, readdir, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

const root = path.resolve(import.meta.dirname, "..");
const qaDir = path.join(root, ".qa");
const downloadDir = path.join(qaDir, "downloads");
const edgePath = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const appPort = 7100;
const debugPort = 9225;
const createdRuns = new Set();
let server;
let browser;
let socket;
let liveSocket;

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function waitFor(check, description, timeout = 15000) {
  const start = Date.now();
  let lastError;
  while (Date.now() - start < timeout) {
    try {
      const value = await check();
      if (value) return value;
    } catch (error) { lastError = error; }
    await delay(150);
  }
  throw new Error(`Timeout: ${description}${lastError ? ` (${lastError.message})` : ""}`);
}
async function stopProcess(child) {
  if (!child || child.killed || !child.pid) return;
  await new Promise((resolve) => {
    const killer = spawn("taskkill", ["/pid", String(child.pid), "/T", "/F"], { stdio: "ignore" });
    killer.on("exit", resolve);
    killer.on("error", () => { child.kill(); resolve(); });
  });
}
class Cdp {
  constructor(ws) {
    this.ws = ws;
    this.nextId = 1;
    this.pending = new Map();
    this.errors = [];
    this.httpErrors = [];
    ws.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (message.id && this.pending.has(message.id)) {
        const { resolve, reject } = this.pending.get(message.id);
        this.pending.delete(message.id);
        if (message.error) reject(new Error(JSON.stringify(message.error)));
        else resolve(message.result);
      }
      if (message.method === "Runtime.exceptionThrown") {
        const detail = message.params.exceptionDetails;
        this.errors.push(`${detail.text}: ${detail.exception?.description || detail.exception?.value || "no description"} @ ${detail.url || "unknown"}:${detail.lineNumber ?? "?"}:${detail.columnNumber ?? "?"}`);
      }
      if (message.method === "Log.entryAdded" && message.params.entry.level === "error") this.errors.push(message.params.entry.text);
      if (message.method === "Network.responseReceived" && message.params.response.status >= 400) this.httpErrors.push(`${message.params.response.status} ${message.params.response.url}`);
    });
  }
  send(method, params = {}) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  async evaluate(expression) {
    const result = await this.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
    return result.result.value;
  }
  async screenshot(name) {
    const result = await this.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
    await writeFile(path.join(qaDir, `${name}.png`), Buffer.from(result.data, "base64"));
  }
}
function assert(condition, message) {
  if (!condition) throw new Error(`Assertion failed: ${message}`);
}

try {
  await rm(qaDir, { recursive: true, force: true });
  await mkdir(qaDir, { recursive: true });
  server = spawn("python", ["-m", "backend.app", "--host", "127.0.0.1", "--port", String(appPort)], { cwd: root, stdio: ["ignore", "pipe", "pipe"] });
  let serverLog = "";
  server.stdout.on("data", (chunk) => { serverLog += chunk.toString(); });
  server.stderr.on("data", (chunk) => { serverLog += chunk.toString(); });
  await waitFor(async () => (await fetch(`http://127.0.0.1:${appPort}/api/health`)).ok, "application health");
  browser = spawn(edgePath, ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", `--remote-debugging-port=${debugPort}`, `--user-data-dir=${path.join(qaDir, "edge-profile")}`, "--window-size=1440,1000", "about:blank"], { stdio: "ignore" });
  await waitFor(async () => (await fetch(`http://127.0.0.1:${debugPort}/json/version`)).ok, "Edge CDP");
  const target = await (await fetch(`http://127.0.0.1:${debugPort}/json/new?about:blank`, { method: "PUT" })).json();
  socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.addEventListener("open", resolve, { once: true }); socket.addEventListener("error", reject, { once: true }); });
  const cdp = new Cdp(socket);
  await Promise.all([cdp.send("Page.enable"), cdp.send("Runtime.enable"), cdp.send("Network.enable"), cdp.send("Log.enable")]);
  await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  await cdp.send("Page.navigate", { url: `http://127.0.0.1:${appPort}/` });
  await waitFor(() => cdp.evaluate("document.readyState === 'complete' && document.querySelectorAll('#workflow-steps li').length === 8"), "workflow loaded");
  assert(await cdp.evaluate("document.querySelector('#idea-input').value.length > 3"), "idea input is ready");
  await cdp.screenshot("01-input-desktop");

  async function createRun(scenario) {
    await cdp.evaluate("document.querySelector('#new-run').click()");
    await waitFor(() => cdp.evaluate("!document.querySelector('#input-view').classList.contains('hidden')"), "new run form");
    await cdp.evaluate(`document.querySelector('#scenario-input').value = '${scenario}'; document.querySelector('#start-button').click()`);
    await waitFor(() => cdp.evaluate(`!document.querySelector('#result-view').classList.contains('hidden') && document.querySelector('#run-subtitle').textContent.includes(${JSON.stringify({ normal: "正常收敛", value_conflict: "价值分歧", budget_exhaustion: "预算耗尽", agent_failure: "Agent 失败" }[scenario])})`), `${scenario} run created`);
    const runId = await cdp.evaluate("document.querySelector('#run-id').textContent");
    createdRuns.add(runId);
    return runId;
  }

  const normalId = await createRun("normal");
  const liveMessages = [];
  liveSocket = new WebSocket(`ws://127.0.0.1:${appPort}/ws/runs/${normalId}`);
  liveSocket.addEventListener("message", (event) => liveMessages.push(JSON.parse(event.data)));
  await new Promise((resolve, reject) => { liveSocket.addEventListener("open", resolve, { once: true }); liveSocket.addEventListener("error", reject, { once: true }); });
  await waitFor(() => liveMessages.find((message) => message.type === "snapshot"), "initial WebSocket snapshot");
  assert(liveMessages[0].run.run_id === normalId && liveMessages[0].run.stage === "INTAKE", "snapshot contains full run");
  liveSocket.send(JSON.stringify({ type: "ping" }));
  await waitFor(() => liveMessages.find((message) => message.type === "pong"), "WebSocket application ping");
  await cdp.evaluate("document.querySelector('#step-button').click()");
  await waitFor(() => cdp.evaluate("document.querySelector('#metric-stage').textContent === 'DIVERGE'"), "single stage advance");
  const pushed = await waitFor(() => liveMessages.find((message) => message.type === "event" && message.event.type === "IDEA_FRAMED"), "WebSocket stage event");
  assert(pushed.run.stage === "DIVERGE" && pushed.sequence === pushed.event.sequence, "event includes latest snapshot and sequence");
  liveSocket.close();
  await waitFor(() => liveSocket.readyState === WebSocket.CLOSED, "WebSocket client closed");
  await cdp.evaluate("document.querySelector('#pause-button').click()");
  await waitFor(() => cdp.evaluate("document.querySelector('#metric-status').textContent === '已暂停'"), "pause checkpoint");
  assert(await cdp.evaluate("document.querySelector('#step-button').disabled"), "paused run cannot advance");
  await cdp.evaluate("document.querySelector('#pause-button').click()");
  await waitFor(() => cdp.evaluate("document.querySelector('#metric-status').textContent === '可推进'"), "resume checkpoint");
  await cdp.evaluate("document.querySelector('#until-button').click()");
  await waitFor(() => cdp.evaluate("document.querySelector('#metric-stage').textContent === 'HUMAN_CONFIRMATION'"), "six person gate");
  assert(await cdp.evaluate("document.querySelectorAll('input[name=\"member\"]').length") === 6, "six independent confirmations");
  assert(await cdp.evaluate("document.querySelector('#metric-round').textContent.trim()") === "2 / 2", "critique loop reached round two");
  await cdp.evaluate("document.querySelectorAll('input[name=\"member\"]').forEach((input, index) => { input.checked = index < 5; input.dispatchEvent(new Event('change', { bubbles: true })); }); document.querySelector('#confirm-form').requestSubmit()");
  await waitFor(() => cdp.evaluate("document.querySelector('#confirm-error').textContent.includes('当前仅 5 / 6')"), "partial confirmation rejected");
  assert(await cdp.evaluate("document.querySelector('#metric-status').textContent === '等待人工'"), "partial confirmation did not publish");
  await cdp.evaluate("document.querySelectorAll('input[name=\"member\"]').forEach((input) => { input.checked = true; input.dispatchEvent(new Event('change', { bubbles: true })); }); document.querySelector('#confirm-form').requestSubmit()");
  await waitFor(() => cdp.evaluate("document.querySelector('#metric-status').textContent === '已完成'"), "R1 published");
  assert(await cdp.evaluate("document.querySelector('#tab-content').textContent.includes('R1 已由六人确认发布')"), "R1 success visible");
  await cdp.screenshot("02-normal-completed-desktop");

  await cdp.evaluate("document.querySelector('[data-tab=\"blackboard\"]').click()");
  await waitFor(() => cdp.evaluate("document.querySelectorAll('#tab-content .record-card').length >= 6"), "blackboard records");
  assert(await cdp.evaluate("document.querySelector('#tab-content').textContent.includes('首轮未读取其他角色答案')"), "independent divergence evidence visible");
  await cdp.screenshot("03-blackboard-desktop");
  await cdp.evaluate("document.querySelector('[data-tab=\"design\"]').click()");
  await waitFor(() => cdp.evaluate("document.querySelectorAll('#tab-content tbody tr').length === 11"), "transition table");
  assert(await cdp.evaluate("document.querySelector('.pseudocode').textContent.includes('confirm_requirements')"), "control pseudocode visible");
  await cdp.evaluate("document.querySelector('[data-tab=\"replay\"]').click()");
  await waitFor(() => cdp.evaluate("document.querySelector('.replay-summary')?.textContent.includes('回放校验通过')"), "replay verified");
  const replayRows = await cdp.evaluate("document.querySelectorAll('#tab-content tbody tr').length");
  assert(replayRows === Number(await cdp.evaluate("document.querySelector('#metric-events').textContent")), "replay covers every event");
  await cdp.screenshot("04-replay-desktop");

  await mkdir(downloadDir, { recursive: true });
  await cdp.send("Page.setDownloadBehavior", { behavior: "allow", downloadPath: downloadDir });
  await cdp.evaluate("document.querySelector('#export-json').click()");
  const jsonName = await waitFor(async () => (await readdir(downloadDir)).find((name) => name.endsWith(".json")), "JSON downloaded");
  const exported = JSON.parse(await readFile(path.join(downloadDir, jsonName), "utf8"));
  assert(exported.run.run_id === normalId && exported.run.blackboard.r1.version === "R1", "JSON contains current confirmed run");
  assert(exported.replay.passed && exported.pseudocode.includes("step(run)"), "JSON contains replay and pseudocode");
  await cdp.evaluate("document.querySelector('#export-markdown').click()");
  const markdownName = await waitFor(async () => (await readdir(downloadDir)).find((name) => name.endsWith(".md")), "Markdown downloaded");
  const markdown = await readFile(path.join(downloadDir, markdownName), "utf8");
  assert(markdown.includes("## 阶段迁移表") && markdown.includes("## 已确认 R1"), "Markdown contains design and R1");

  await createRun("value_conflict");
  await cdp.evaluate("document.querySelector('#until-button').click()");
  await waitFor(() => cdp.evaluate("document.querySelector('#metric-stage').textContent === 'EVALUATE' && document.querySelector('#metric-status').textContent === '等待人工'"), "value conflict gate");
  assert(await cdp.evaluate("document.querySelector('#until-button').disabled && !!document.querySelector('#decision-form')"), "human decision blocks auto advance");
  await cdp.evaluate("document.querySelector('#decision-input').value = '团队决定首期优先隐私与可控成本，并保留该价值取舍理由。'; document.querySelector('#decision-form').requestSubmit()");
  await waitFor(() => cdp.evaluate("document.querySelector('#metric-status').textContent === '可推进'"), "decision unlocks run");
  await cdp.evaluate("document.querySelector('#until-button').click()");
  await waitFor(() => cdp.evaluate("document.querySelector('#metric-stage').textContent === 'HUMAN_CONFIRMATION'"), "decision resumes workflow");
  await cdp.evaluate("document.querySelector('[data-tab=\"blackboard\"]').click()");
  await waitFor(() => cdp.evaluate("document.querySelector('#tab-content').textContent.includes('D001')"), "decision linked to objection");

  await createRun("budget_exhaustion");
  await cdp.evaluate("document.querySelector('#until-button').click()");
  await waitFor(() => cdp.evaluate("document.querySelector('#metric-status').textContent === '预算停止'"), "budget stopped");
  assert(await cdp.evaluate("document.querySelector('#tab-content').textContent.includes('停止不等于共识')"), "stopped is not consensus");
  assert(await cdp.evaluate("document.querySelector('#until-button').disabled"), "stopped run cannot auto advance");
  await cdp.screenshot("05-budget-stopped-desktop");

  await createRun("agent_failure");
  await cdp.evaluate("document.querySelector('#until-button').click()");
  await waitFor(() => cdp.evaluate("document.querySelector('#metric-status').textContent === '已阻断'"), "agent failure blocked");
  assert(await cdp.evaluate("document.querySelector('#metric-stage').textContent === 'DIVERGE'"), "failure stays at divergence");
  assert(await cdp.evaluate("document.querySelector('#tab-content').textContent.includes('未生成任何观点')"), "real failure visible");
  await cdp.evaluate("document.querySelector('[data-tab=\"blackboard\"]').click()");
  await waitFor(() => cdp.evaluate("document.querySelector('#tab-content').textContent.includes('尚无观点')"), "no invented claims");

  const responsive = {};
  for (const width of [768, 1024]) {
    await cdp.send("Emulation.setDeviceMetricsOverride", { width, height: 900, deviceScaleFactor: 1, mobile: false });
    await delay(200);
    const dimensions = await cdp.evaluate("({viewport: innerWidth, page: document.documentElement.scrollWidth})");
    assert(dimensions.page <= dimensions.viewport, `no page overflow at ${width}px (${JSON.stringify(dimensions)})`);
    responsive[width] = dimensions;
  }
  await cdp.send("Emulation.setDeviceMetricsOverride", { width: 375, height: 812, deviceScaleFactor: 1, mobile: true });
  await delay(250);
  const resultDimensions = await cdp.evaluate("({viewport: innerWidth, page: document.documentElement.scrollWidth})");
  assert(resultDimensions.page <= resultDimensions.viewport, `no mobile result overflow (${JSON.stringify(resultDimensions)})`);
  await cdp.screenshot("06-result-mobile");
  await cdp.evaluate("document.querySelector('#new-run').click()");
  await delay(250);
  const inputDimensions = await cdp.evaluate("({viewport: innerWidth, page: document.documentElement.scrollWidth})");
  assert(inputDimensions.page <= inputDimensions.viewport, `no mobile input overflow (${JSON.stringify(inputDimensions)})`);
  await cdp.screenshot("07-input-mobile");

  assert(cdp.errors.length === 0, `zero browser errors: ${cdp.errors.join("; ")}`);
  assert(cdp.httpErrors.length === 0, `zero HTTP errors: ${cdp.httpErrors.join("; ")}`);
  console.log(JSON.stringify({ ok: true, websocket: { snapshot: true, eventPush: true, pingPong: true }, singleStageAdvance: true, normalConfirmed: true, partialConfirmationRejected: true, pauseResume: true, valueDecision: true, budgetStopped: true, agentBlocked: true, tabs: 4, replayRows, exports: [jsonName, markdownName], responsive, mobile: { resultDimensions, inputDimensions }, consoleErrors: cdp.errors, httpErrors: cdp.httpErrors, serverLog: serverLog.split("\n").filter((line) => line.includes(" 500 ")).length }, null, 2));
  socket.close();
} catch (error) {
  console.error(error.stack || error);
  process.exitCode = 1;
} finally {
  if (liveSocket && liveSocket.readyState === WebSocket.OPEN) liveSocket.close();
  if (socket && socket.readyState === WebSocket.OPEN) socket.close();
  await stopProcess(browser);
  await stopProcess(server);
  await delay(700);
  for (const runId of createdRuns) await rm(path.join(root, "data", `${runId}.json`), { force: true });
  await rm(path.join(qaDir, "edge-profile"), { recursive: true, force: true, maxRetries: 8, retryDelay: 250 });
}
