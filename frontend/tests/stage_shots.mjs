/**
 * 八页面工作台截图：逐个切页并截图，用于人工核对布局。
 *
 * 运行：node tests/stage_shots.mjs http://127.0.0.1:7100 [输出目录]
 */

import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const BASE = process.argv[2] || 'http://127.0.0.1:7100';
const OUT = process.argv[3] || 'shots';
const CHROME_CANDIDATES = [
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
];
const PORT = 9334;
const profile = mkdtempSync(join(tmpdir(), 'b05-stages-'));

const STAGES = [
  ['项目总览', '01-overview'],
  ['项目主理人', '02-owner'],
  ['需求与方案', '03-requirements'],
  ['规格与计划', '04-spec'],
  ['Agent 执行', '06-agents'],
  ['成果交付', '07-delivery'],
  ['历史项目', '08-history'],
];

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitForEndpoint(url, attempts = 60) {
  for (let index = 0; index < attempts; index += 1) {
    try {
      const response = await fetch(url);
      if (response.ok) return await response.json();
    } catch {
      /* not ready */
    }
    await sleep(250);
  }
  throw new Error(`等待 ${url} 超时`);
}

class Cdp {
  constructor(socket) {
    this.socket = socket;
    this.nextId = 1;
    this.pending = new Map();
    socket.addEventListener('message', (event) => {
      const message = JSON.parse(event.data);
      const entry = this.pending.get(message.id);
      if (entry) {
        this.pending.delete(message.id);
        if (message.error) entry.reject(new Error(message.error.message));
        else entry.resolve(message.result);
      }
    });
  }

  send(method, params = {}, sessionId = undefined) {
    const id = this.nextId++;
    const message = { id, method, params };
    if (sessionId) message.sessionId = sessionId;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.socket.send(JSON.stringify(message));
    });
  }

  async evaluate(expression, sessionId = undefined) {
    const result = await this.send(
      'Runtime.evaluate',
      { expression, returnByValue: true, awaitPromise: true },
      sessionId,
    );
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || '页面脚本异常');
    return result.result.value;
  }
}

async function main() {
  const executable = CHROME_CANDIDATES.find((candidate) => existsSync(candidate));
  if (!executable) throw new Error('未找到 Chrome/Edge 可执行文件');
  mkdirSync(OUT, { recursive: true });

  const child = spawn(
    executable,
    [
      '--headless=new',
      '--disable-gpu',
      '--no-sandbox',
      '--no-first-run',
      '--hide-scrollbars',
      '--window-size=1600,1000',
      `--remote-debugging-port=${PORT}`,
      `--user-data-dir=${join(profile, 'ud')}`,
      'about:blank',
    ],
    { stdio: 'ignore' },
  );

  try {
    const version = await waitForEndpoint(`http://127.0.0.1:${PORT}/json/version`);
    const socket = new WebSocket(version.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => {
      socket.addEventListener('open', resolve, { once: true });
      socket.addEventListener('error', () => reject(new Error('CDP 连接失败')), { once: true });
    });
    const cdp = new Cdp(socket);

    const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
    const { sessionId } = await cdp.send('Target.attachToTarget', { targetId, flatten: true });
    const send = (method, params = {}) => cdp.send(method, params, sessionId);
    await send('Page.enable');
    await send('Runtime.enable');
    await send('Emulation.setDeviceMetricsOverride', {
      width: 1680,
      height: 1020,
      deviceScaleFactor: 1,
      mobile: false,
    });
    await send('Page.navigate', { url: BASE });
    await sleep(2500);

    for (const [label, filename] of STAGES) {
      await cdp.evaluate(
        `(() => {
          const item = Array.from(document.querySelectorAll('.stage-item'))
            .find((button) => button.textContent.includes(${JSON.stringify(label)}));
          if (item) item.click();
          return Boolean(item);
        })()`,
        sessionId,
      );
      await sleep(900);
      const { data } = await send('Page.captureScreenshot', { format: 'png' });
      writeFileSync(join(OUT, `${filename}.png`), Buffer.from(data, 'base64'));
      console.log(`wrote ${join(OUT, `${filename}.png`)}`);
    }

    socket.close();
  } finally {
    child.kill();
    await sleep(400);
    try {
      rmSync(profile, { recursive: true, force: true });
    } catch {
      /* ignore */
    }
  }
}

try {
  await main();
} catch (error) {
  console.error(`ERROR ${error.message}`);
  process.exitCode = 1;
}
