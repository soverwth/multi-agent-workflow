/**
 * 截图脚本：为交付物生成成功/失败/详情三张界面截图。
 * 运行：node tests/screenshots.mjs [http://127.0.0.1:4321]
 */

import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const BASE = process.argv[2] || 'http://127.0.0.1:4321';
const OUT_DIR = process.argv[3] || 'shots';
const CHROME_CANDIDATES = [
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
];
const PORT = 9335;
const profile = mkdtempSync(join(tmpdir(), 'b05-shots-'));
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

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

async function waitFor(url, attempts = 60) {
  for (let index = 0; index < attempts; index += 1) {
    try {
      const response = await fetch(url);
      if (response.ok) return await response.json();
    } catch {
      /* retry */
    }
    await sleep(250);
  }
  throw new Error(`等待 ${url} 超时`);
}

async function shoot(cdp, sessionId, url, path, prepare) {
  const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
  const attached = await cdp.send('Target.attachToTarget', { targetId, flatten: true });
  const sid = attached.sessionId;
  await cdp.send('Page.enable', {}, sid);
  await cdp.send('Runtime.enable', {}, sid);
  await cdp.send('Emulation.setDeviceMetricsOverride', {
    width: 1680, height: 1020, deviceScaleFactor: 1, mobile: false,
  }, sid);
  await cdp.send('Page.navigate', { url }, sid);
  await sleep(2800);
  if (prepare) {
    await cdp.evaluate(prepare, sid);
    await sleep(1500);
  }
  const { data } = await cdp.send('Page.captureScreenshot', { format: 'png' }, sid);
  writeFileSync(path, Buffer.from(data, 'base64'));
  await cdp.send('Target.closeTarget', { targetId });
  console.log(`wrote ${path}`);
}

async function main() {
  const executable = CHROME_CANDIDATES.find((candidate) => existsSync(candidate));
  if (!executable) throw new Error('未找到 Chrome/Edge');
  mkdirSync(OUT_DIR, { recursive: true });
  const child = spawn(executable, [
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

    await shoot(cdp, null, BASE, join(OUT_DIR, 'dag-success.png'), `
      (() => {
        const select = document.querySelector('select[aria-label="模拟运行"]');
        if (select) {
          const option = Array.from(select.options).find((o) => o.textContent.includes('全部任务'));
          if (option) { select.value = option.value; select.dispatchEvent(new Event('change', { bubbles: true })); }
        }
      })()
    `);

    await shoot(cdp, null, BASE, join(OUT_DIR, 'dag-failure.png'), `
      (() => {
        const select = document.querySelector('select[aria-label="模拟运行"]');
        if (!select) return;
        const option = Array.from(select.options).find((o) => o.textContent.includes('失败'));
        if (option) { select.value = option.value; select.dispatchEvent(new Event('change', { bubbles: true })); }
      })()
    `);

    await shoot(cdp, null, BASE, join(OUT_DIR, 'detail-panel.png'), `
      (() => {
        const nodes = Array.from(document.querySelectorAll('.react-flow__node'));
        const blocked = nodes.find((node) => node.innerText.includes('已阻塞'));
        (blocked || nodes[0])?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      })()
    `);
    socket.close();
  } finally {
    child.kill();
    await sleep(500);
    rmSync(profile, { recursive: true, force: true });
  }
}

try {
  await main();
} catch (error) {
  console.error(`ERROR ${error.message}`);
  process.exitCode = 1;
}
