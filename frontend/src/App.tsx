import { useCallback, useMemo, useState } from 'react';
import { createControlApi, type ControlApi } from './api/controlApi';
import { CaseSamples } from './components/CaseSamples';
import { TaskGraph } from './components/TaskGraph';
import { ALL_STATUSES, statusColors, statusLabels } from './constants/status';
import { useTaskWebSocket } from './hooks/useTaskWebSocket';
import type { ControlCommand } from './types/events';
import type { DataSource, Task } from './types/task';
import { exportDefects, exportRunReport, exportSnapshot, exportTraceability } from './utils/export';
import './App.css';

const WS_URL = 'ws://localhost:8000';

function StatCard({ label, value, color, bg }: { label: string; value: number | string; color: string; bg: string }) {
  return (
    <div style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 10, padding: '10px 16px', minWidth: 92 }}>
      <div style={{ fontSize: 11, color: '#64748b' }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color, background: bg, borderRadius: 6, paddingLeft: 2 }}>{value}</div>
    </div>
  );
}

function App() {
  const [source, setSource] = useState<DataSource>('simulation');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tab, setTab] = useState<'dashboard' | 'samples'>('dashboard');
  const [panelTab, setPanelTab] = useState<'detail' | 'logs' | 'control'>('detail');
  const [controlApi, setControlApi] = useState<ControlApi | null>(null);

  const handleTransportReady = useCallback((transport: (cmd: ControlCommand) => void) => {
    setControlApi(createControlApi(transport, 'human-operator'));
  }, []);

  const { tasks, meta, connection, logs, acks } = useTaskWebSocket(WS_URL, source, handleTransportReady);

  const selectedTask = tasks.find((t) => t.task_id === selectedId) || null;

  const stats = useMemo(() => {
    const done = tasks.filter((t) => t.status === 'SUCCEEDED').length;
    const running = tasks.filter((t) => t.status === 'RUNNING' || t.status === 'REVIEWING').length;
    const blocked = tasks.filter((t) => t.status === 'FAILED' || t.status === 'BLOCKED').length;
    const retries = tasks.reduce((s, t) => s + t.retry_count, 0);
    const openDefects = tasks.flatMap((t) => t.objections).filter((o) => o.status === 'open').length;
    return { done, running, blocked, retries, openDefects };
  }, [tasks]);

  const getExportCtx = () => ({
    source,
    runId: meta.run_id || 'N/A',
    specVersion: meta.spec_version || 'S1',
    contractVersion: meta.contract_version || 'C1',
    exportedAt: new Date().toISOString(),
  });

  const isReal = source === 'real';

  return (
    <div className="app-shell">
      {/* ================= 顶部导航 ================= */}
      <header className="app-header">
        <div>
          <h1>多智能体协作开发平台 · 任务编排视图</h1>
          <span className="subtitle">B05 交互展示 Agent ｜ 校园失物招领系统（R1 / S1 / C1 基线）</span>
        </div>
        <div className="header-right">
          {/* 数据源切换：模拟 / 真实明确区分 */}
          <div className="source-switch" role="group" aria-label="数据源切换">
            <button className={!isReal ? 'active' : ''} onClick={() => setSource('simulation')}>模拟推演</button>
            <button className={isReal ? 'active real' : ''} onClick={() => setSource('real')}>真实接口</button>
          </div>
          <span className={`source-badge ${isReal ? 'real' : 'sim'}`}>
            {isReal ? '真实接口' : '模拟数据'} · {connection.connected ? '实时同步中' : '连接中…'}
          </span>
        </div>
      </header>

      {/* ================= 主体 ================= */}
      <div className="app-main">
        <div className="app-content">
          {/* 顶部统计 + 导出 */}
          <div className="toolbar">
            <div className="stats">
              <StatCard label="已通过" value={stats.done} color="#15803d" bg="#f0fdf4" />
              <StatCard label="执行/验收" value={stats.running} color="#b45309" bg="#fffbeb" />
              <StatCard label="失败/阻塞" value={stats.blocked} color="#b91c1c" bg="#fef2f2" />
              <StatCard label="累计重试" value={stats.retries} color="#6d28d9" bg="#f5f3ff" />
              <StatCard label="未关闭缺陷" value={stats.openDefects} color="#b91c1c" bg="#fef2f2" />
            </div>
            <div className="exports">
              <span className="exports-label">成果导出</span>
              <button onClick={() => exportSnapshot(tasks, getExportCtx())}>快照 JSON</button>
              <button onClick={() => exportTraceability(tasks, getExportCtx())}>追溯表 CSV</button>
              <button onClick={() => exportDefects(tasks, getExportCtx())}>缺陷清单</button>
              <button onClick={() => exportRunReport(tasks, logs, acks, getExportCtx())}>运行报告</button>
            </div>
          </div>

          {/* 视图切换 */}
          <div className="view-tabs">
            <button className={tab === 'dashboard' ? 'active' : ''} onClick={() => setTab('dashboard')}>任务编排视图</button>
            <button className={tab === 'samples' ? 'active' : ''} onClick={() => setTab('samples')}>T06–T08 案例样例</button>
          </div>

          {tab === 'dashboard' ? (
            <div className="graph-area">
              {/* 图例 */}
              <div className="legend">
                <strong>状态图例：</strong>
                {ALL_STATUSES.map((s) => (
                  <span key={s} className="legend-item">
                    <i style={{ background: statusColors[s] }} />{statusLabels[s]}
                  </span>
                ))}
              </div>

              <div className="canvas">
                {tasks.length === 0 ? (
                  <div className="canvas-empty">正在等待 Orchestrator 推送任务数据…</div>
                ) : (
                  <TaskGraph tasks={tasks} selectedId={selectedId} onNodeClick={(t) => { setSelectedId(t.task_id); setPanelTab('detail'); }} />
                )}
              </div>

              {/* Agent 资源状态 */}
              <div className="agent-bar">
                <strong>Agent 资源：</strong>
                {['Orchestrator', 'DB-01', 'BE-01', 'FE-01', 'QA-01'].map((agent) => {
                  const runningTask = tasks.find((t) => t.assignee === agent && t.status === 'RUNNING');
                  return (
                    <span key={agent} className={`agent-chip ${runningTask ? 'busy' : ''}`}>
                      {agent}: {runningTask ? `执行中 (${runningTask.task_id})` : '空闲'}
                    </span>
                  );
                })}
              </div>
            </div>
          ) : (
            <div className="samples-area">
              <CaseSamples source={source} />
            </div>
          )}
        </div>

        {/* ================= 右侧面板 ================= */}
        <aside className="side-panel">
          <div className="side-tabs">
            <button className={panelTab === 'detail' ? 'active' : ''} onClick={() => setPanelTab('detail')}>任务详情</button>
            <button className={panelTab === 'logs' ? 'active' : ''} onClick={() => setPanelTab('logs')}>事件日志</button>
            <button className={panelTab === 'control' ? 'active' : ''} onClick={() => setPanelTab('control')}>控制</button>
          </div>

          <div className="side-body">
            {panelTab === 'detail' && (
              selectedTask ? <TaskDetail task={selectedTask} /> :
              <div className="side-empty">点击左侧任务节点查看<br />尝试、输入版本与验收详情</div>
            )}

            {panelTab === 'logs' && (
              <div>
                <div className="panel-note">来自 Orchestrator 事件流（{isReal ? '真实' : '模拟'}）</div>
                {logs.length === 0 ? <div className="side-empty">暂无事件</div> : (
                  <div className="log-list">
                    {logs.map((l) => (
                      <div key={l.id} className={`log-item ${l.level}`}>
                        <span className="log-time">{l.timestamp.slice(11, 19)}</span>
                        <span>{l.message}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {panelTab === 'control' && (
              <ControlPanel
                api={controlApi}
                connected={connection.connected}
                selectedTask={selectedTask}
                acks={acks}
              />
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}

function TaskDetail({ task }: { task: Task }) {
  return (
    <div className="detail">
      <div className="detail-title">
        <span>{task.task_id}</span>
        <span className="status-pill" style={{ background: statusColors[task.status] }}>{statusLabels[task.status]}</span>
      </div>
      <p className="detail-goal">{task.goal}</p>

      <Section title="执行信息">
        <Row label="负责 Agent" value={task.assignee} />
        <Row label="直接依赖" value={task.depends_on.length ? task.depends_on.join(', ') : '无（起始节点）'} />
        <Row label="派发编号 attempt_id" value={`#${task.attempt_id}`} />
        <Row label="失败重派 retry_count" value={String(task.retry_count)} warn={task.retry_count > 0} />
        {task.revalidation_id && <Row label="上游重验" value={task.revalidation_id} />}
      </Section>

      <Section title="版本与输入快照">
        <Row label="设计基线" value={task.spec_version} mono />
        <Row label="契约版本" value={task.contract_version} mono />
        <Row label="输入快照" value={task.input_snapshot} mono />
        <Row label="数据来源" value={task.source ? (task.source === 'real' ? '真实接口' : '模拟推演') : '全局'} />
      </Section>

      {task.blocked_reason && (
        <Section title="阻塞原因">
          <div className="alert blocked">{task.blocked_reason}</div>
        </Section>
      )}
      {task.error && (
        <Section title="失败信息">
          <div className="alert error">{task.error}</div>
        </Section>
      )}

      <Section title={`交付产物 (${task.outputs.length})`}>
        {task.outputs.length ? task.outputs.map((o, i) => (
          <div key={i} className="artifact"><code>{o.path}</code> <span>@{o.version}</span></div>
        )) : <div className="muted">尚未提交候选产物</div>}
      </Section>

      <Section title={`验收证据 (${task.evidence.length})`}>
        {task.evidence.length ? task.evidence.map((e) => (
          <div key={e.case_id} className="evidence">
            <span className={e.passed ? 'pass' : 'fail'}>{e.passed ? '✓' : '✗'}</span>
            <code>{e.case_id}</code> {e.detail}
          </div>
        )) : <div className="muted">尚未提交规定用例证据</div>}
      </Section>

      {task.objections.length > 0 && (
        <Section title="异议 / 缺陷">
          {task.objections.map((o) => (
            <div key={o.id} className={`objection ${o.status}`}>
              <div className="obj-head"><strong>{o.id}</strong> <span>{o.from}</span> <em>{o.status === 'open' ? '未关闭' : '已关闭'}</em></div>
              <div className="obj-reason">{o.reason}</div>
            </div>
          ))}
        </Section>
      )}

      <Section title="尝试历史">
        {task.attempts.length ? task.attempts.map((a) => (
          <div key={`${a.attempt_id}-${a.started_at}`} className="attempt">
            <span className={`attempt-dot ${a.result}`} />
            <code>#{a.attempt_id}</code>
            <span>retry {a.retry_count}</span>
            <span className="attempt-result">{a.result}</span>
            {a.note && <span className="attempt-note">{a.note}</span>}
          </div>
        )) : <div className="muted">尚未派发</div>}
      </Section>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="section">
      <div className="section-title">{title}</div>
      {children}
    </div>
  );
}

function Row({ label, value, mono, warn }: { label: string; value: string; mono?: boolean; warn?: boolean }) {
  return (
    <div className="row">
      <span className="row-label">{label}</span>
      <span className={`row-value ${mono ? 'mono' : ''} ${warn ? 'warn' : ''}`}>{value}</span>
    </div>
  );
}

function ControlPanel({ api, connected, selectedTask, acks }: {
  api: ControlApi | null;
  connected: boolean;
  selectedTask: Task | null;
  acks: ReturnType<typeof useTaskWebSocket>['acks'];
}) {
  const disabled = !api || !connected;
  return (
    <div>
      <div className="panel-note">
        所有控制动作以指令发给 Orchestrator（B02），界面不直接改动任务状态；结果以回执为准。
      </div>
      <div className="control-grid">
        <button disabled={disabled} onClick={() => api?.pause()}>暂停派发</button>
        <button disabled={disabled} onClick={() => api?.resume()}>恢复派发</button>
        <button
          disabled={disabled || !selectedTask}
          onClick={() => selectedTask && api?.retry(selectedTask.task_id, '人工重派')}
        >重派选中任务</button>
        <button
          disabled={disabled || !selectedTask}
          onClick={() => selectedTask && api?.cancel(selectedTask.task_id, '人工取消')}
        >取消选中任务</button>
        <button disabled={disabled} onClick={() => api?.confirmChange('人工确认 R2/S2/C2')} className="wide">
          确认变更（建立新基线）
        </button>
      </div>
      <div className="section-title" style={{ marginTop: 20 }}>控制回执</div>
      {acks.length === 0 ? <div className="muted">暂无控制操作</div> : (
        <div className="ack-list">
          {acks.map((a) => (
            <div key={a.id} className={`ack ${a.accepted ? 'ok' : 'no'}`}>
              <strong>{a.command}</strong> {a.accepted ? '已受理' : '未受理'}
              <div>{a.message}</div>
              <time>{a.timestamp.slice(11, 19)}</time>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default App;
