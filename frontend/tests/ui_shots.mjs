/**
 * 对 7100 工作台的若干页面做整页截图，用于人工目检。
 * 用法：node tests/ui_shots.mjs http://127.0.0.1:7100 <输出目录>
 */
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

const BASE = process.argv[2] ?? 'http://127.0.0.1:7100';
const OUT = resolve(process.argv[3] ?? 'shots');
const PORT = 9333;
const CHROME_CANDIDATES = [
  process.env.CHROME_BIN,
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
].filter(Boolean);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function connect() {
  const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
  const target = list.find((t) => t.type === 'page');
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((done, fail) => { ws.addEventListener('open', done, { once: true }); ws.addEventListener('error', fail, { once: true }); });
  let id = 0; const pending = new Map();
  ws.addEventListener('message', ({ data }) => { const m = JSON.parse(data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } });
  const send = (method, params = {}, sessionId) => new Promise((done, fail) => {
    const i = ++id; pending.set(i, (m) => (m.error ? fail(new Error(m.error.message)) : done(m.result)));
    ws.send(JSON.stringify({ id: i, method, params, sessionId }));
  });
  return { send, ws };
}

async function main() {
  const exe = CHROME_CANDIDATES.find((p) => existsSync(p));
  if (!exe) throw new Error('未找到 Chrome/Edge');
  mkdirSync(OUT, { recursive: true });
  const profile = join(tmpdir(), `maw-shots-${Date.now()}`);
  const child = spawn(exe, ['--headless=new', '--disable-gpu', '--no-sandbox', '--no-first-run', '--hide-scrollbars',
    '--window-size=1600,1000', `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, 'about:blank'], { stdio: 'ignore' });
  try {
    await sleep(900);
    const cdp = await connect();
    const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
    const { sessionId } = await cdp.send('Target.attachToTarget', { targetId, flatten: true });
    await cdp.send('Page.enable', {}, sessionId);
    await cdp.send('Runtime.enable', {}, sessionId);
    await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false }, sessionId);
    await cdp.send('Page.navigate', { url: BASE }, sessionId);
    await sleep(2500);

    const stages = ['编排与执行', '项目主理人', '需求讨论', '规格与计划', '观测与回溯', '项目总览'];
    for (const label of stages) {
      await cdp.send('Runtime.evaluate', { expression: `(() => { const b = Array.from(document.querySelectorAll('.stage-item')).find(x => x.textContent.includes(${JSON.stringify(label)})); if (b) b.click(); return Boolean(b); })()`, returnByValue: true }, sessionId);
      await sleep(900);
      const { data } = await cdp.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false }, sessionId);
      const name = `ui-${label}.png`;
      writeFileSync(join(OUT, name), Buffer.from(data, 'base64'));
      console.log('shot:', join(OUT, name));
    }
    cdp.ws.close();
  } finally {
    child.kill();
    await sleep(400);
    try { rmSync(profile, { recursive: true, force: true }); } catch { /* ignore */ }
  }
}

main().catch((error) => { console.error('ERROR', error.message); process.exitCode = 1; });
