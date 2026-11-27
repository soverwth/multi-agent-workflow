/**
 * 结构化布局检查（替代肉眼看截图）：
 * 读取关键元素的实际渲染盒模型，断言侧栏在左、顶栏在上、内容区无横向溢出、卡片不超出视口。
 */
import { spawn } from 'node:child_process';
import { existsSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const BASE = process.argv[2] ?? 'http://127.0.0.1:7100';
const PORT = 9334;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const CANDIDATES = [process.env.CHROME_BIN, 'C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].filter(Boolean);

async function connect() {
  const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
  const target = list.find((t) => t.type === 'page');
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((d, f) => { ws.addEventListener('open', d, { once: true }); ws.addEventListener('error', f, { once: true }); });
  let id = 0; const pending = new Map();
  ws.addEventListener('message', ({ data }) => { const m = JSON.parse(data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } });
  const send = (method, params = {}, sessionId) => new Promise((done, fail) => { const i = ++id; pending.set(i, (m) => (m.error ? fail(new Error(m.error.message)) : done(m.result))); ws.send(JSON.stringify({ id: i, method, params, sessionId })); });
  return { send, ws };
}

const PROBE = `(() => {
  const box = (sel) => { const el = document.querySelector(sel); if (!el) return null; const r = el.getBoundingClientRect(); return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height), sw: el.scrollWidth, cw: el.clientWidth }; };
  return {
    viewport: { w: window.innerWidth, h: window.innerHeight },
    header: box('.app-header'), sidebar: box('.sidebar'), main: box('.app-main'), content: box('.app-content'),
    page: box('.page') || box('.stage-panel'),
    docOverflowX: document.documentElement.scrollWidth > window.innerWidth,
    firstCard: box('.card') || box('.stat-card'),
    pageScrollX: (() => { const p = document.querySelector('.page') || document.querySelector('.stage-panel'); return p ? p.scrollWidth > p.clientWidth : null; })(),
    cardsOverflow: Array.from(document.querySelectorAll('.card, .stat-card, .requirement-section')).filter(el => { const r = el.getBoundingClientRect(); return r.right > window.innerWidth + 1 || r.left < -1; }).length,
  };
})()`;

async function main() {
  const exe = CANDIDATES.find((p) => existsSync(p));
  const profile = join(tmpdir(), `maw-layout-${Date.now()}`);
  const child = spawn(exe, ['--headless=new', '--disable-gpu', '--no-sandbox', '--no-first-run', '--hide-scrollbars', '--window-size=1600,1000', `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, 'about:blank'], { stdio: 'ignore' });
  let failures = 0;
  const check = (ok, msg) => { console.log(`  ${ok ? 'PASS' : 'FAIL'} ${msg}`); if (!ok) failures += 1; };
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

    for (const label of ['编排与执行', '项目主理人', '需求讨论', '规格与计划', '观测与回溯', '项目总览', '需求与方案', 'Agent 执行', '成果交付', '历史项目']) {
      await cdp.send('Runtime.evaluate', { expression: `(() => { const b = Array.from(document.querySelectorAll('.stage-item')).find(x => x.textContent.includes(${JSON.stringify(label)})); if (b) b.click(); })()`, returnByValue: true }, sessionId);
      await sleep(800);
      const { result } = await cdp.send('Runtime.evaluate', { expression: PROBE, returnByValue: true }, sessionId);
      const p = result.value;
      console.log(`\n[${label}]`);
      if (label === '编排与执行') {
        check(p.header && p.header.y === 0 && p.header.h >= 50 && p.header.h <= 70, `顶栏贴顶、高度 ${p.header?.h}px（期望 50–70）`);
        check(p.sidebar && p.sidebar.x === 0 && p.sidebar.w >= 200 && p.sidebar.w <= 240, `侧栏贴左、宽度 ${p.sidebar?.w}px（期望 200–240）`);
        check(p.sidebar && p.sidebar.y === p.header.h, `侧栏从顶栏下方开始（y=${p.sidebar?.y}）`);
        check(p.main && p.main.x === p.sidebar.w, `内容区紧跟侧栏（x=${p.main?.x}）`);
      }
      check(p.header && p.sidebar && p.main, '壳层三要素（顶栏/侧栏/内容区）均渲染');
      check(!p.docOverflowX, '文档无横向溢出');
      check(p.pageScrollX !== true, '页面容器无横向滚动');
      check(p.cardsOverflow === 0, `无卡片超出视口（${p.cardsOverflow} 个）`);
      check(p.page && p.page.h > 300, `内容区高度 ${p.page?.h}px`);
    }
    // 窄屏（平板）断点
    await cdp.send('Emulation.setDeviceMetricsOverride', { width: 820, height: 1000, deviceScaleFactor: 1, mobile: false }, sessionId);
    await sleep(600);
    const { result } = await cdp.send('Runtime.evaluate', { expression: PROBE, returnByValue: true }, sessionId);
    const n = result.value;
    console.log('\n[窄屏 820px]');
    check(n.sidebar && n.sidebar.y === n.header.h && n.sidebar.h < 200, `侧栏折叠为横向条（h=${n.sidebar?.h}px）`);
    check(!n.docOverflowX, '窄屏无横向溢出');
    cdp.ws.close();
  } finally {
    child.kill(); await sleep(300);
    try { rmSync(profile, { recursive: true, force: true }); } catch { /* ignore */ }
  }
  console.log(failures === 0 ? '\nLAYOUT: PASS' : `\nLAYOUT: ${failures} FAILURE(S)`);
  if (failures) process.exitCode = 1;
}
main().catch((e) => { console.error('ERROR', e.message); process.exitCode = 1; });
