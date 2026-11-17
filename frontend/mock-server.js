/**
 * B05 交互展示 Agent —— 演示用 Orchestrator 事件源
 *
 * 通过 WebSocket 广播任务快照 / 增量事件 / 控制回执 / 日志，
 * 让前端在不接真实后端的情况下完整演示 B05 验收场景：
 *   1) 依赖等待、并行派发、串行汇合
 *   2) D-01 缺陷 → 撤销错误成功 → 阻塞下游 → 返修 → 重验
 *   3) 人工确认入口（暂停/恢复/取消/重派/变更确认）
 *   4) 模拟 / 真实数据源标识（?source=real 切换）
 *
 * 用法：node mock-server.js        （默认 8000 端口，simulation 数据源）
 *      node mock-server.js 8010   （指定端口）
 * 前端：ws://localhost:8000 或 ws://localhost:8000?source=real
 */
import { WebSocketServer } from 'ws';

const port = Number(process.argv[2] || 8000);

/** 由 URL 查询参数决定数据源，界面据此明确区分模拟与真实结果 */
function sourceFromRequest(req) {
  try {
    const url = new URL(req.url, `http://${req.headers.host}`);
    return url.searchParams.get('source') === 'real' ? 'real' : 'simulation';
  } catch {
    return 'simulation';
  }
}

const SPEC_VERSION = 'S1';
const CONTRACT_VERSION = 'C1';
const RUN_ID = `RUN-DEMO-${new Date().toISOString().slice(0, 10)}`;
const now = () => new Date().toISOString();

/** 标准任务种子（字段与 src/types/task.ts 对齐） */
function baseTask(task_id, goal, depends_on, assignee) {
  return {
    task_id,
    goal,
    depends_on,
    assignee,
    status: 'PENDING',
    spec_version: SPEC_VERSION,
    contract_version: CONTRACT_VERSION,
    input_snapshot: `snap-${task_id}-r1`,
    attempt_id: 0,
    retry_count: 0,
    revalidation_id: null,
    write_scope: [],
    outputs: [],
    evidence: [],
    objections: [],
    attempts: [],
    blocked_reason: null,
    error: null,
  };
}

function initialTasks() {
  return [
    baseTask('T01', '校验并冻结已批准的 S1/C1 基线，登记审批引用', [], 'Orchestrator'),
    baseTask('T02', '设计 user / lost_item / claim_application 数据模型与约束', ['T01'], 'DB-01'),
    baseTask('T03', '实现注册、登录、会话与本人信息操作', ['T02'], 'BE-01'),
    baseTask('T04', '实现 publish_lost / search_lost / get_lost 处理逻辑', ['T03'], 'BE-01'),
    baseTask('T05', '实现 create_claim 认领申请与去重约束', ['T04'], 'BE-01'),
    baseTask('T06', '失物发布表单：名称/描述/地点/丢失时间输入与提示', ['T01'], 'FE-01'),
    baseTask('T07', '失物搜索列表：关键词/地点过滤与分页展示', ['T01'], 'FE-01'),
    baseTask('T08', '失物详情与认领入口页面', ['T01'], 'FE-01'),
    baseTask('T09', '接口与边界测试设计（含 TC-P02 省略 lost_at）', ['T01'], 'QA-01'),
    baseTask('T10', '跨模块集成检查与缺陷发现/回归', ['T05', 'T06', 'T07', 'T08', 'T09'], 'QA-01'),
    baseTask('T11', '汇总交付物、追溯表、缺陷关闭记录与运行说明', ['T10'], 'Orchestrator'),
  ];
}

function seedTask(task, status, extra = {}) {
  Object.assign(task, { status }, extra);
  return task;
}

let tasks = initialTasks();
seedTask(tasks[0], 'SUCCEEDED', {
  attempt_id: 1,
  outputs: [{ path: 'baseline/S1-C1-frozen.json', version: 'r1', desc: '冻结的设计输入快照' }],
  evidence: [{ case_id: 'CHK-BASELINE', passed: true, detail: 'S1/C1 批准记录存在且字段完整' }],
  attempts: [{ attempt_id: 1, retry_count: 0, started_at: now(), finished_at: now(), result: 'success' }],
});
seedTask(tasks[1], 'SUCCEEDED', { attempt_id: 1 });
seedTask(tasks[2], 'RUNNING', {
  attempt_id: 1,
  attempts: [{ attempt_id: 1, retry_count: 0, started_at: now(), result: 'running' }],
});
seedTask(tasks[5], 'RUNNING', {
  attempt_id: 1,
  attempts: [{ attempt_id: 1, retry_count: 0, started_at: now(), result: 'running' }],
});
seedTask(tasks[6], 'READY');
seedTask(tasks[8], 'READY');

const wss = new WebSocketServer({ port });
console.log(`Mock Orchestrator 已启动: ws://localhost:${port}  (default source=simulation, 可加 ?source=real)`);

const clients = new Set();
let paused = false;
let timer = null;
let stepIndex = 0;

function broadcast(event) {
  const data = JSON.stringify(event);
  for (const ws of clients) {
    if (ws.readyState === ws.OPEN) ws.send(data);
  }
}

function log(level, message, task_id) {
  broadcast({ type: 'log', level, message, task_id, timestamp: now(), _source: currentSourceForBroadcast() });
}

function currentSourceForBroadcast() {
  // 广播事件按连接来源打标；这里取最近一次连接来源作为默认值，
  // 单个连接收到的事件会在 sendTo 中按该连接来源覆盖。
  return lastSource;
}
let lastSource = 'simulation';

function sendSnapshot(ws, source) {
  ws.send(JSON.stringify({
    type: 'snapshot',
    tasks: tasks.map((t) => ({ ...t, source })),
    source,
    spec_version: SPEC_VERSION,
    contract_version: CONTRACT_VERSION,
    run_id: RUN_ID,
    timestamp: now(),
  }));
}

function updateTask(taskId, patch, source) {
  const task = tasks.find((t) => t.task_id === taskId);
  if (!task) return;
  const next = { ...task, ...patch };
  tasks = tasks.map((t) => (t.task_id === taskId ? next : t));
  broadcast({
    type: 'update',
    task_id: taskId,
    patch: { ...patch, source },
    source,
    timestamp: now(),
  });
}

function ack(command, accepted, message, source) {
  broadcast({
    type: 'control_ack',
    request_id: command?.request_id,
    command: command?.action,
    accepted,
    message,
    source,
    timestamp: now(),
  });
}

/** 演示时间线：每一步产生若干事件；事件带来源标记 */
const timeline = [
  // 0: T03 完成，T04 就绪
  () => {
    updateTask('T03', {
      status: 'SUCCEEDED',
      outputs: [{ path: 'backend/auth/session.pseudo', version: 'r1' }],
      evidence: [{ case_id: 'TC-A01', passed: true, detail: '注册/登录/会话过期用例通过' }],
      attempts: [{ attempt_id: 1, retry_count: 0, started_at: now(), finished_at: now(), result: 'success' }],
    });
    updateTask('T04', { status: 'READY' });
    log('info', 'T03 用户身份模块验收通过，T04 进入 READY', 'T03');
  },
  // 1: T04 首次派发
  () => {
    updateTask('T04', {
      status: 'RUNNING',
      attempt_id: 1,
      attempts: [{ attempt_id: 1, retry_count: 0, started_at: now(), result: 'running' }],
    });
    log('info', 'BE-01 开始 T04 首次执行（attempt_id=1）', 'T04');
  },
  // 2: T04 候选提交进入验收
  () => {
    updateTask('T04', {
      status: 'REVIEWING',
      outputs: [{ path: 'backend/lost/publish_handler.pseudo', version: 'r1', desc: '候选 r1，含缺陷' }],
      evidence: [{ case_id: 'TC-P01', passed: true, detail: '合法发布与搜索自检通过' }],
    });
    log('info', 'T04 r1 提交，QA-01 开始独立验收（缺 TC-P02/TC-P03）', 'T04');
  },
  // 3: 缺陷暴露：T04 失败 + 下游阻塞
  () => {
    updateTask('T04', {
      status: 'FAILED',
      error: 'TC-P02 失败：省略 lost_at 未返回 REQUIRED_FIELD',
      objections: [{
        id: 'D-01', from: 'QA-01',
        reason: 'publish_lost 用 current_time() 兜底 lost_at，缺失时未返回 REQUIRED_FIELD',
        status: 'open', created_at: now(),
      }],
      attempts: [{ attempt_id: 1, retry_count: 0, started_at: now(), finished_at: now(), result: 'failure', note: 'D-01' }],
    });
    updateTask('T05', { status: 'BLOCKED', blocked_reason: '上游 T04 r1 验收失败，放行条件撤销' });
    updateTask('T10', { status: 'BLOCKED', blocked_reason: '依赖 T05 未通过，集成门槛未满足' });
    log('error', '发现 D-01，Orchestrator 撤销 T04 放行并阻塞 T05/T10', 'T04');
  },
  // 4: 返修重派 attempt_id=2, retry_count=1
  () => {
    updateTask('T04', {
      status: 'RUNNING',
      attempt_id: 2,
      retry_count: 1,
      error: null,
      input_snapshot: 'snap-T04-r2',
      attempts: [
        { attempt_id: 1, retry_count: 0, started_at: '09:12:00', finished_at: '09:18:00', result: 'failure', note: 'D-01' },
        { attempt_id: 2, retry_count: 1, started_at: now(), result: 'running' },
      ],
    });
    log('warn', 'T04 返修重派：attempt_id=2, retry_count=1（预算 2）', 'T04');
  },
  // 5: T04 r2 通过，缺陷关闭，下游恢复
  () => {
    updateTask('T04', {
      status: 'SUCCEEDED',
      outputs: [{ path: 'backend/lost/publish_handler.pseudo', version: 'r2', desc: '移除默认时间，写入前校验字段' }],
      evidence: [
        { case_id: 'TC-P01', passed: true, detail: '合法发布/搜索通过' },
        { case_id: 'TC-P02', passed: true, detail: '缺失 lost_at 返回 400 REQUIRED_FIELD' },
        { case_id: 'TC-P03', passed: true, detail: '非法 ISO 8601 被拒绝' },
        { case_id: 'PRIVACY', passed: true, detail: 'LostView 不含 publisher_id' },
      ],
      objections: [{
        id: 'D-01', from: 'QA-01',
        reason: 'publish_lost 用 current_time() 兜底 lost_at，缺失时未返回 REQUIRED_FIELD',
        status: 'resolved', created_at: '09:18:00',
      }],
      attempts: [
        { attempt_id: 1, retry_count: 0, started_at: '09:12:00', finished_at: '09:18:00', result: 'failure', note: 'D-01' },
        { attempt_id: 2, retry_count: 1, started_at: '09:19:00', finished_at: now(), result: 'success' },
      ],
    });
    updateTask('T05', { status: 'READY', blocked_reason: null });
    updateTask('T10', { status: 'PENDING', blocked_reason: null });
    log('success', 'D-01 关闭，T04 r2 验收通过，T05 恢复 READY', 'T04');
  },
  // 6: 前端与测试设计完成，T10 就绪
  () => {
    for (const [id, path] of [
      ['T06', 'frontend/publish/PublishForm.tsx'],
      ['T07', 'frontend/search/SearchList.tsx'],
      ['T08', 'frontend/detail/LostDetail.tsx'],
      ['T09', 'tests/contract/api.spec.ts'],
    ]) {
      updateTask(id, {
        status: 'SUCCEEDED', attempt_id: 1,
        outputs: [{ path, version: 'r1' }],
        evidence: [{ case_id: `CHK-${id}`, passed: true, detail: '局部检查通过' }],
        attempts: [{ attempt_id: 1, retry_count: 0, started_at: now(), finished_at: now(), result: 'success' }],
      });
    }
    updateTask('T05', {
      status: 'SUCCEEDED', attempt_id: 1,
      outputs: [{ path: 'backend/claim/create_claim.pseudo', version: 'r1' }],
      evidence: [{ case_id: 'TC-C01', passed: true, detail: '重复认领被拒绝' }],
      attempts: [{ attempt_id: 1, retry_count: 0, started_at: now(), finished_at: now(), result: 'success' }],
    });
    updateTask('T10', { status: 'READY' });
    log('success', 'T03—T09 均有效成功，T10 集成检查就绪');
  },
  // 7: 集成检查 + 交付汇总
  () => {
    updateTask('T10', {
      status: 'SUCCEEDED', attempt_id: 1,
      outputs: [{ path: 'tests/integration/report.md', version: 'r1' }],
      evidence: [{ case_id: 'TC-ORCH-GATE', passed: true, detail: '缺证据不成功的门槛已验证' }],
      attempts: [{ attempt_id: 1, retry_count: 0, started_at: now(), finished_at: now(), result: 'success' }],
    });
    updateTask('T11', { status: 'READY' });
    log('success', '集成检查通过，T11 交付汇总 READY', 'T10');
  },
  () => {
    updateTask('T11', {
      status: 'SUCCEEDED', attempt_id: 1,
      outputs: [{ path: 'deliverables/traceability.csv', version: 'r1' }],
      attempts: [{ attempt_id: 1, retry_count: 0, started_at: now(), finished_at: now(), result: 'success' }],
    });
    log('success', '全部任务完成，交付物已汇总', 'T11');
  },
];

function advance() {
  if (paused) return;
  if (stepIndex >= timeline.length) return;
  try {
    timeline[stepIndex]();
  } catch (err) {
    log('error', `演示步骤执行失败: ${err.message}`);
  }
  stepIndex += 1;
}

function startTimer() {
  if (timer) clearInterval(timer);
  timer = setInterval(advance, 3500);
}

function handleControl(ws, msg, source) {
  const command = msg.command || {};
  const action = command.action;
  let accepted = true;
  let message = '';

  switch (action) {
    case 'pause':
      paused = true;
      message = '调度已暂停：停止新派发，已运行任务允许提交候选结果';
      log('warn', message);
      break;
    case 'resume':
      paused = false;
      message = '调度已恢复：重新检查版本与资源后继续派发';
      log('info', message);
      break;
    case 'cancel': {
      const id = command.task_id;
      const task = tasks.find((t) => t.task_id === id);
      if (!task) { accepted = false; message = `任务 ${id} 不存在`; break; }
      updateTask(id, {
        status: 'FAILED',
        error: `已取消：${command.reason || '人工取消'}`,
        blocked_reason: null,
      });
      message = `任务 ${id} 已取消（记录原因并隔离未结束调用）`;
      log('warn', message, id);
      break;
    }
    case 'retry': {
      const id = command.task_id;
      const task = tasks.find((t) => t.task_id === id);
      if (!task) { accepted = false; message = `任务 ${id} 不存在`; break; }
      const nextAttempt = task.attempt_id + 1;
      const nextRetry = task.retry_count + 1;
      if (nextRetry > 2) { accepted = false; message = `任务 ${id} 重试预算已用尽（retry_budget=2）`; break; }
      updateTask(id, {
        status: 'RUNNING',
        attempt_id: nextAttempt,
        retry_count: nextRetry,
        error: null,
        attempts: [
          ...task.attempts,
          { attempt_id: nextAttempt, retry_count: nextRetry, started_at: now(), result: 'running', note: command.reason || '人工重派' },
        ],
      });
      message = `任务 ${id} 重派：attempt_id=${nextAttempt}, retry_count=${nextRetry}`;
      log('info', message, id);
      break;
    }
    case 'confirm_change':
      message = '变更已确认：建立新基线 R2/S2/C2，受影响任务将重算 DAG（演示中保持当前快照）';
      log('warn', message);
      break;
    default:
      accepted = false;
      message = `未知控制指令: ${action}`;
  }

  ack(command, accepted, message, source);
  void ws;
}

wss.on('connection', (ws, req) => {
  const source = sourceFromRequest(req);
  lastSource = source;
  clients.add(ws);
  console.log(`前端已连接 (source=${source})`);
  sendSnapshot(ws, source);

  ws.on('message', (raw) => {
    let msg;
    try { msg = JSON.parse(raw.toString()); } catch { return; }
    if (msg && msg.type === 'control') handleControl(ws, msg, source);
  });

  ws.on('close', () => {
    clients.delete(ws);
    console.log('前端连接断开');
  });
});

startTimer();
