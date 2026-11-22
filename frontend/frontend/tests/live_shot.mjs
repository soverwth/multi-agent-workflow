/**
 * 真实接口联调截图：从 B02 读取一个进行中的运行并截图。
 * 运行：node tests/live_shot.mjs http://127.0.0.1:4321 TASK-RUN-LIVE01 shots/live.png
 */

import { spawn } from 'node:child_process';
import { existsSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const BASE = process.argv[2] || 'http://127.0.0.1:4321';
const RUN_ID = process.argv[3] || 'TASK-RUN-LIVE01';
const OUT = process.argv[4] || 'live.png';
const API = process.env.B02_BASE || 'http://127.0.0.1:7100';
const PORT = 9337;
const profile = mkdtempSync(join(tmpdir(), 'b05-live-'));
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const CHROME = [
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
].find((p) => existsSync(p));

class Cdp {
  constructor(socket) {
    this.socket = socket;
    this.nextId = 1;
    this.pending = new Map();
    socket.addEventListener('message', (event) => {
      const message = JSON.parse(event.data);
      const entry = this.pending.get(message.id);
      if (!entry) return;
      this.pending.delete(message.id);
      if (message.error) entry.reject(new Error(message.error.message));
      else entry.resolve(message.result);
    });
  }

  send(method, params = {}, sessionId) {
    const id = this.nextId++;
    const message = { id, method, params };
    if (sessionId) message.sessionId = sessionId;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.socket.send(JSON.stringify(message));
    });
  }

  async evaluate(expression, sessionId) {
    const result = await this.send(
      'Runtime.evaluate',
      { expression, returnByValue: true, awaitPromise: true },
      sessionId,
    );
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
    return result.result.value;
  }
}

async function waitFor(url) {
  for (let i = 0; i < 60; i += 1) {
    try {
      const r = await fetch(url);
      if (r.ok) return await r.json();
    } catch {
      /* retry */
    }
    await sleep(250);
  }
  throw new Error(`等待 ${url} 超时`);
}

async function main() {
  if (!CHROME) throw new Error('未找到 Chrome/Edge');
  const child = spawn(CHROME, [
    '--headless=new', '--disable-gpu', '--no-sandbox', '--no-first-run',
    '--hide-scrollbars', '--window-size=1680,1020',
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${join(profile, 'ud')}`,
    'about:blank',
  ], { stdio: 'ignore' });

  try {
    const version = await waitFor(`http://127.0.0.1:${PORT}/json/version`);
    const socket = new WebSocket(version.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => {
      socket.addEventListener('open', resolve, { once: true });
      socket.addEventListener('error', () => reject(new Error('CDP 连接失败')), { once: true });
    });
    const cdp = new Cdp(socket);
    const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
    const { sessionId } = await cdp.send('Target.attachToTarget', { targetId, flatten: true });
    await cdp.send('Page.enable', {}, sessionId);
    await cdp.send('Runtime.enable', {}, sessionId);
    await cdp.send('Emulation.setDeviceMetricsOverride',
      { width: 1680, height: 1020, deviceScaleFactor: 1, mobile: false }, sessionId);
    await cdp.send('Page.navigate', { url: BASE }, sessionId);
    await sleep(2800);

    // 切到真实接口 + 填入地址与运行编号 + 点击加载
    const applied = await cdp.evaluate(`
      (() => {
        const setValue = (input, value) => {
          const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
          setter.call(input, value);
          input.dispatchEvent(new Event('input', { bubbles: true }));
        };
        const real = Array.from(document.querySelectorAll('.source-switch button'))
          .find((b) => b.textContent.includes('真实接口'));
        if (real) real.click();
        return Boolean(real);
      })()
    `, sessionId);
    await sleep(600);
    const filled = await cdp.evaluate(`
      (() => {
        const setValue = (input, value) => {
          const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
          setter.call(input, value);
          input.dispatchEvent(new Event('input', { bubbles: true }));
        };
        const api = document.querySelector('input[aria-label="后端地址"]');
        const run = document.querySelector('input[aria-label="任务运行编号"]');
        if (!api || !run) return 'no-inputs';
        setValue(api, ${JSON.stringify(API)});
        setValue(run, ${JSON.stringify(RUN_ID)});
        const button = Array.from(document.querySelectorAll('button'))
          .find((b) => b.textContent.includes('加载运行'));
        if (button) button.click();
        return 'ok';
      })()
    `, sessionId);
    await sleep(3000);

    const state = await cdp.evaluate(`
      JSON.stringify({
        nodes: document.querySelectorAll('.react-flow__node').length,
        text: document.body.innerText.slice(0, 4000),
      })
    `, sessionId);
    const parsed = JSON.parse(state);
    console.log(`切换真实接口: ${applied}, 填表: ${filled}, 节点数: ${parsed.nodes}`);
    for (const needle of ['TASK-RUN-LIVE01', 'PLAN-lab-equipment-loan-v1.0', '真实接口', '已通过', '等依赖']) {
      console.log(`  ${parsed.text.includes(needle) ? 'PASS' : 'FAIL'} 界面包含「${needle}」`);
    }
    if (parsed.text.includes('无法读取真实任务运行')) {
      console.log('  FAIL 界面显示了连接错误');
    }
    const { data } = await cdp.send('Page.captureScreenshot', { format: 'png' }, sessionId);
    writeFileSync(OUT, Buffer.from(data, 'base64'));
    console.log(`wrote ${OUT}`);
    socket.close();
  } finally {
    child.kill();
    await sleep(400);
    rmSync(profile, { recursive: true, force: true });
  }
}

try {
  await main();
} catch (error) {
  console.error(`ERROR ${error.message}`);
  process.exitCode = 1;
}
