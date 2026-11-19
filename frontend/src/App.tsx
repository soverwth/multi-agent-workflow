import { useCallback, useEffect, useMemo, useState } from 'react';
import { loadSimulationRun, listSimulationRuns, type SimulationRun } from './data/simulationRuns';
import { TaskDetailPanel } from './components/TaskDetailPanel';
import { TaskGraph } from './components/TaskGraph';
import { TaskTimeline } from './components/TaskTimeline';
import { ALL_STATUSES, statusColors, statusLabels } from './constants/status';
import {
  advanceDiscussion,
  confirmDiscussion,
  createDiscussionRun,
  createTaskRunFromDiscussion,
  createTaskRunFromSpec,
  fetchDesignSpec,
  fetchLlmConfig,
  type DiscussionRun,
  type LlmConfigStatus,
  type RunEvent,
  updateLlmConfig,
} from './api/taskRunApi';
import { useTaskRun } from './hooks/useTaskRun';
import type { DataSource, Task } from './types/task';
import {
  exportDefects,
  exportRunReport,
  exportSnapshot,
  exportTaskMarkdown,
  exportTraceability,
  exportWorkflow,
  type ExportContext,
} from './utils/export';
import './App.css';
import type { AckEntry, LogEntry } from './hooks/useTaskWebSocket';

/**
 * 真实接口默认使用当前页面的 origin。
 *
 * 集成运行时 B02 同时托管 B05 构建产物，因此浏览器只需要访问
 * http://127.0.0.1:7100；保留环境变量覆盖，便于可选的独立 Vite 联调。
 */
const DEFAULT_API_BASE = import.meta.env.VITE_API_BASE || window.location.origin;
const CONFIRMATION_MEMBERS = ['成员 A', '成员 B', '成员 C', '成员 D', '成员 E', '成员 F'];

type ReportEvent = Pick<RunEvent, 'sequence' | 'type' | 'task_id' | 'occurred_at'> & { event_id?: string };

function eventLogs(events: ReportEvent[]): LogEntry[] {
  return events.map((event) => ({
    id: event.event_id || `event-${event.sequence}`,
    level: event.type.includes('FAILED') || event.type.includes('BLOCKED')
      ? 'error'
      : event.type.includes('COMPLETED') || event.type.includes('ACCEPTED')
        ? 'success'
        : 'info',
    message: `${event.type}${event.task_id ? ` · ${event.task_id}` : ''}`,
    task_id: event.task_id ?? undefined,
    timestamp: event.occurred_at,
  }));
}

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
  const [panelOpen, setPanelOpen] = useState(true);
  const [planView, setPlanView] = useState<'dag' | 'timeline'>('dag');

  // 模拟数据源：选择由真实编排器跑出的历史运行
  const runs = useMemo(() => listSimulationRuns(), []);
  const [simRunKey, setSimRunKey] = useState<string>(() => runs[0]?.key ?? '');
  const simulation = useMemo<SimulationRun | null>(() => loadSimulationRun(simRunKey), [simRunKey]);

  // 真实数据源：连接 B02 的任务运行
  const [apiBase, setApiBase] = useState(DEFAULT_API_BASE);
  const [runIdInput, setRunIdInput] = useState('TASK-RUN-DEMO');
  const [submittedRunId, setSubmittedRunId] = useState('');
  const [specPath, setSpecPath] = useState('b01-spec-planner/docs/fixtures/campus-lost-found.spec.json');
  const [launching, setLaunching] = useState(false);
  const [discussionIdea, setDiscussionIdea] = useState('');
  const [discussionConstraints, setDiscussionConstraints] = useState('');
  const [discussion, setDiscussion] = useState<DiscussionRun | null>(null);
  const [discussionBusy, setDiscussionBusy] = useState(false);
  const [discussionError, setDiscussionError] = useState<string | null>(null);
  const [sourceRunId, setSourceRunId] = useState('');
  const [designSpec, setDesignSpec] = useState<Record<string, unknown> | null>(null);
  const [specLoading, setSpecLoading] = useState(false);
  const [llmConfig, setLlmConfig] = useState<LlmConfigStatus | null>(null);
  const [llmApiKey, setLlmApiKey] = useState('');
  const [llmBaseUrl, setLlmBaseUrl] = useState('https://api.deepseek.com');
  const [llmModel, setLlmModel] = useState('deepseek-chat');
  const [llmSaving, setLlmSaving] = useState(false);
  const isReal = source === 'real';
  const real = useTaskRun({
    baseUrl: apiBase,
    runId: submittedRunId,
    enabled: isReal,
    pollIntervalMs: isReal ? 3000 : 0,
  });

  const tasks = useMemo<Task[]>(
    () => (isReal ? real.tasks : simulation?.tasks ?? []),
    [isReal, real.tasks, simulation],
  );
  const meta = useMemo(
    () => (isReal ? real.meta : simulation?.meta ?? null),
    [isReal, real.meta, simulation],
  );
  const selectedTask = tasks.find((task) => task.task_id === selectedId) ?? null;
  const reportLogs = eventLogs(isReal ? real.events : simulation?.events ?? []);
  const reportAcks: AckEntry[] = [];

  useEffect(() => {
    void fetchLlmConfig(apiBase)
      .then((config) => {
        setLlmConfig(config);
        setLlmBaseUrl(config.base_url);
        setLlmModel(config.model);
      })
      .catch(() => setLlmConfig(null));
  }, [apiBase]);

  const stats = useMemo(() => {
    const done = tasks.filter((task) => task.status === 'SUCCEEDED').length;
    const active = tasks.filter((task) =>
      ['READY', 'RUNNING', 'WAITING_DEPENDENCY', 'REVIEWING', 'RETRYING'].includes(task.status),
    ).length;
    const problems = tasks.filter((task) => task.status === 'FAILED' || task.status === 'BLOCKED').length;
    const retries = tasks.reduce((sum, task) => sum + task.retry_count, 0);
    const defects = tasks.flatMap((task) => task.objections).filter((item) => item.status === 'open').length;
    return { done, active, problems, retries, defects };
  }, [tasks]);

  const selectRun = useCallback((key: string) => {
    setSimRunKey(key);
    setSelectedId(null);
  }, []);

  const switchSource = useCallback((next: DataSource) => {
    setSource(next);
    setSelectedId(null);
  }, []);

  const handleLoadRun = useCallback(() => {
    setSubmittedRunId(runIdInput.trim());
    setSource('real');
    setSelectedId(null);
  }, [runIdInput]);

  const handleCreateFromSpec = useCallback(async () => {
    setLaunching(true);
    try {
      const created = await createTaskRunFromSpec({ baseUrl: apiBase, specPath });
      setRunIdInput(created.run.run_id);
      setSubmittedRunId(created.run.run_id);
      setSource('real');
      setSelectedId(null);
    } catch (caught) {
      window.alert(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setLaunching(false);
    }
  }, [apiBase, specPath]);

  const handleCreateDiscussion = useCallback(async () => {
    if (!discussionIdea.trim()) return;
    setDiscussionBusy(true);
    setDiscussionError(null);
    try {
      const created = await createDiscussionRun(apiBase, discussionIdea, discussionConstraints);
      setDiscussion(created);
      setSourceRunId(created.run_id);
      setDesignSpec(null);
    } catch (caught) {
      setDiscussionError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setDiscussionBusy(false);
    }
  }, [apiBase, discussionConstraints, discussionIdea]);

  const handleAdvanceDiscussion = useCallback(async () => {
    if (!discussion) return;
    setDiscussionBusy(true);
    setDiscussionError(null);
    try {
      setDiscussion(await advanceDiscussion(apiBase, discussion.run_id));
    } catch (caught) {
      setDiscussionError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setDiscussionBusy(false);
    }
  }, [apiBase, discussion]);

  const handleConfirmDiscussion = useCallback(async () => {
    if (!discussion) return;
    setDiscussionBusy(true);
    setDiscussionError(null);
    try {
      setDiscussion(await confirmDiscussion(apiBase, discussion.run_id, CONFIRMATION_MEMBERS));
    } catch (caught) {
      setDiscussionError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setDiscussionBusy(false);
    }
  }, [apiBase, discussion]);

  const handleBridgeDiscussion = useCallback(async () => {
    if (!discussion || discussion.status !== 'COMPLETED') return;
    setDiscussionBusy(true);
    setDiscussionError(null);
    try {
      const created = await createTaskRunFromDiscussion(apiBase, discussion.run_id);
      setDesignSpec(created.source);
      setRunIdInput(created.run.run_id);
      setSubmittedRunId(created.run.run_id);
      setSource('real');
      setSelectedId(null);
    } catch (caught) {
      setDiscussionError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setDiscussionBusy(false);
    }
  }, [apiBase, discussion]);

  const handleLoadDesignSpec = useCallback(async () => {
    if (!sourceRunId.trim()) return;
    setSpecLoading(true);
    setDiscussionError(null);
    try {
      setDesignSpec(await fetchDesignSpec(apiBase, sourceRunId.trim()));
    } catch (caught) {
      setDiscussionError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setSpecLoading(false);
    }
  }, [apiBase, sourceRunId]);

  const handleSaveLlmConfig = useCallback(async () => {
    setLlmSaving(true);
    try {
      const updated = await updateLlmConfig(apiBase, {
        base_url: llmBaseUrl,
        model: llmModel,
        api_key: llmApiKey,
        enabled: true,
      });
      setLlmConfig(updated);
      setLlmApiKey('');
    } catch (caught) {
      setDiscussionError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setLlmSaving(false);
    }
  }, [apiBase, llmApiKey, llmBaseUrl, llmModel]);

  // 导出上下文在“点击导出时”构造：时间戳必须反映真实导出时刻，
  // 不能在渲染期求值（否则每次重渲染都会变，且违反 React 纯函数约束）。
  const buildExportContext = useCallback(
    (): ExportContext => ({
      source,
      runId: meta?.run_id ?? 'N/A',
      specVersion: meta?.spec_version ?? 'S1',
      contractVersion: meta?.contract_version ?? 'C1',
      exportedAt: new Date().toISOString(),
    }),
    [source, meta],
  );

  return (
    <div className="app-shell">
      <header className="app-header">
        <div>
          <h1>多智能体协作开发平台 · 开发任务 DAG</h1>
          <span className="subtitle">
            规格 → 计划 → 编排 → 执行 → 验收 → 展示
            {meta ? ` ｜ ${meta.plan_version} ｜ ${meta.project_id}` : ''}
          </span>
        </div>

        <div className="header-right">
          {/* 双数据源对照区：真实运行 ID 输入 + 模拟运行选择 */}
          {isReal ? (
            <div className="header-inputs">
              <input
                aria-label="后端地址"
                value={apiBase}
                onChange={(event) => setApiBase(event.target.value)}
                placeholder="http://127.0.0.1:7100"
                size={22}
              />
              <input
                aria-label="任务运行编号"
                value={runIdInput}
                onChange={(event) => setRunIdInput(event.target.value)}
                placeholder="TASK-RUN-XXXXXXXX"
                size={18}
              />
              <button onClick={handleLoadRun}>加载运行</button>
            </div>
          ) : (
            <select
              aria-label="模拟运行"
              value={simRunKey}
              onChange={(event) => selectRun(event.target.value)}
              style={{ padding: '6px 8px', borderRadius: 6, border: '1px solid #cbd5e1' }}
            >
              {runs.map((run) => (
                <option key={run.key} value={run.key}>
                  {run.label}
                </option>
              ))}
            </select>
          )}

          <div className="source-switch" role="group" aria-label="数据源切换">
            <button className={!isReal ? 'active' : ''} onClick={() => switchSource('simulation')}>
              模拟推演
            </button>
            <button className={isReal ? 'active real' : ''} onClick={() => switchSource('real')}>
              真实接口
            </button>
          </div>

          <span className={`source-badge ${isReal ? 'real' : 'sim'}`}>
            {isReal
              ? real.error
                ? `真实接口 · 连接失败`
                : real.loading
                  ? '真实接口 · 加载中…'
                  : '真实接口 · 已同步'
              : '模拟数据 · 真实编排器产物'}
          </span>
        </div>
      </header>

      <div className="app-main">
        <div className="app-content">
          <section className="workbench-panel">
            <div className="workbench-heading">
              <div>
                <strong>统一 SE Workflow 工作台</strong>
                <span>用户想法 → 多体讨论 → R1 → design spec → PM Agent → 编排器 → 执行验收</span>
              </div>
              <span className={`llm-status ${llmConfig?.enabled ? 'ready' : 'local'}`}>
                {llmConfig?.enabled ? `模型已连接 · ${llmConfig.model}` : '本地规则兜底'}
              </span>
            </div>
            <div className="workflow-rail" aria-label="通用软件工程流程">
              {['用户想法', '多体讨论', 'R1 确认', '设计规格', '任务分解', '任务编排', '执行验收', '可视化'].map((stage, index) => (
                <span key={stage} className={index < 4 && discussion?.status === 'COMPLETED' ? 'done' : ''}>
                  <b>{index + 1}</b>{stage}
                </span>
              ))}
            </div>
            <div className="workbench-grid">
              <div className="workbench-card">
                <h3>第一阶段：用户想法与 R1</h3>
                <textarea
                  aria-label="用户想法"
                  value={discussionIdea}
                  onChange={(event) => setDiscussionIdea(event.target.value)}
                  placeholder="例如：我想制作一个校园失物招领系统"
                  rows={2}
                />
                <input
                  aria-label="第一阶段约束"
                  value={discussionConstraints}
                  onChange={(event) => setDiscussionConstraints(event.target.value)}
                  placeholder="可选约束，例如首期只做 MVP"
                />
                <div className="workbench-actions">
                  <button onClick={() => void handleCreateDiscussion()} disabled={discussionBusy || !discussionIdea.trim()}>
                    创建讨论运行
                  </button>
                  <button onClick={() => void handleAdvanceDiscussion()} disabled={discussionBusy || !discussion}>
                    运行到需求确认
                  </button>
                  <button onClick={() => void handleConfirmDiscussion()} disabled={discussionBusy || !discussion || discussion.stage !== 'HUMAN_CONFIRMATION'}>
                    六人确认 R1
                  </button>
                  <button onClick={() => void handleBridgeDiscussion()} disabled={discussionBusy || !discussion || discussion.status !== 'COMPLETED'}>
                    进入第二阶段
                  </button>
                </div>
                {discussion && (
                  <div className="workbench-meta">
                    <span>{discussion.run_id}</span>
                    <span>{discussion.stage} · {discussion.status}</span>
                    <span>R1 {discussion.blackboard?.r1 ? '已发布' : '未发布'}</span>
                  </div>
                )}
              </div>
              <div className="workbench-card">
                <h3>模型 API 配置</h3>
                <p className="muted">支持 DeepSeek 和其他 OpenAI-compatible 服务。密钥只保存在当前后端进程内。</p>
                <div className="config-grid">
                  <input aria-label="模型 API 地址" value={llmBaseUrl} onChange={(event) => setLlmBaseUrl(event.target.value)} placeholder="https://api.deepseek.com" />
                  <input aria-label="模型名称" value={llmModel} onChange={(event) => setLlmModel(event.target.value)} placeholder="deepseek-chat" />
                  <input aria-label="模型 API Key" type="password" value={llmApiKey} onChange={(event) => setLlmApiKey(event.target.value)} placeholder={llmConfig?.key_configured ? '已配置，输入新 Key 可替换' : '输入 API Key'} />
                  <button onClick={() => void handleSaveLlmConfig()} disabled={llmSaving || !llmApiKey.trim()}>{llmSaving ? '保存中…' : '保存并启用'}</button>
                </div>
              </div>
              <div className="workbench-card">
                <h3>设计规格查看</h3>
                <p className="muted">输入第一阶段 RUN 编号，查看实际桥接后的 design spec。</p>
                <div className="spec-source-row">
                  <input aria-label="第一阶段运行编号" value={sourceRunId} onChange={(event) => setSourceRunId(event.target.value)} placeholder="RUN-XXXXXXXXXX" />
                  <button onClick={() => void handleLoadDesignSpec()} disabled={specLoading || !sourceRunId.trim()}>{specLoading ? '读取中…' : '查看规格'}</button>
                </div>
                {designSpec && (
                  <details className="spec-preview" open>
                    <summary>{String(designSpec.title ?? '已加载 design spec')} · {Array.isArray(designSpec.requirements) ? designSpec.requirements.length : 0} 项需求</summary>
                    <pre>{JSON.stringify(designSpec, null, 2)}</pre>
                  </details>
                )}
              </div>
            </div>
            {discussionError && <div className="alert error" role="alert">{discussionError}</div>}
          </section>
          <div className="spec-launch-bar">
            <div>
              <strong>第二阶段入口：设计规格 → PM Agent → 编排器</strong>
              <span>输入规格路径后创建真实任务运行，可逐步执行或运行至完成。</span>
            </div>
            <input
              aria-label="设计规格路径"
              value={specPath}
              onChange={(event) => setSpecPath(event.target.value)}
              placeholder="b01-spec-planner/docs/fixtures/your.spec.json"
            />
            <button onClick={handleCreateFromSpec} disabled={launching || !specPath.trim()}>
              {launching ? '正在生成计划…' : '从设计规格启动'}
            </button>
            <button onClick={() => void real.step()} disabled={!isReal || !submittedRunId || real.loading}>
              推进一步
            </button>
            <button onClick={() => void real.runToCompletion()} disabled={!isReal || !submittedRunId || real.loading}>
              运行至完成
            </button>
          </div>
          <div className="toolbar">
            <div className="stats">
              <StatCard label="已通过" value={stats.done} color="#15803d" bg="#f0fdf4" />
              <StatCard label="进行中" value={stats.active} color="#b45309" bg="#fffbeb" />
              <StatCard label="失败/阻塞" value={stats.problems} color="#b91c1c" bg="#fef2f2" />
              <StatCard label="累计重试" value={stats.retries} color="#6d28d9" bg="#f5f3ff" />
              <StatCard label="未关闭缺陷" value={stats.defects} color="#b91c1c" bg="#fef2f2" />
            </div>
            {meta && (
              <div className="meta-line">
                <span>{meta.run_id}</span>
                <span>{meta.spec_version} / {meta.contract_version}</span>
                <span className="mono" title="输入快照">snap {meta.input_snapshot.slice(0, 12)}</span>
                <span>完成 {meta.completed}/{meta.total}</span>
              </div>
            )}
            <div className="exports">
              <span className="exports-label">成果导出</span>
              <button onClick={() => exportSnapshot(tasks, buildExportContext())}>快照 JSON</button>
              <button onClick={() => exportWorkflow(tasks, buildExportContext())}>workflow.json</button>
              <button onClick={() => exportTaskMarkdown(tasks, buildExportContext())}>task.md</button>
              <button onClick={() => exportTraceability(tasks, buildExportContext())}>追溯表 CSV</button>
              <button onClick={() => exportDefects(tasks, buildExportContext())}>缺陷清单</button>
              <button onClick={() => exportRunReport(tasks, reportLogs, reportAcks, buildExportContext())}>运行报告</button>
            </div>
          </div>

          {isReal && real.error && (
            <div className="alert error" role="alert">
              无法读取真实任务运行：{real.error}
              <div className="muted" style={{ marginTop: 4 }}>
                请确认 B02 服务已启动（python -m backend.app），并已通过
                <code> POST /api/task-runs</code> 创建该运行编号。
              </div>
            </div>
          )}

          <div className="graph-area">
            <div className="plan-view-switch" role="group" aria-label="任务计划视图">
              <strong>任务计划视图</strong>
              <button className={planView === 'dag' ? 'active' : ''} onClick={() => setPlanView('dag')}>依赖 DAG</button>
              <button className={planView === 'timeline' ? 'active' : ''} onClick={() => setPlanView('timeline')}>甘特排期</button>
              <span>{tasks.length} 个任务 · {new Set(tasks.flatMap((task) => task.depends_on)).size} 条依赖引用</span>
            </div>
            {planView === 'dag' && <div className="legend">
              <strong>状态图例：</strong>
              {ALL_STATUSES.map((status) => (
                <span key={status} className="legend-item">
                  <i style={{ background: statusColors[status] }} />
                  {statusLabels[status]}
                </span>
              ))}
            </div>}

            <div className="canvas">
              {tasks.length === 0 ? (
                <div className="canvas-empty">
                  {isReal
                    ? '尚未加载真实任务运行：请输入运行编号后点击「加载运行」。'
                    : '正在等待任务数据…'}
                </div>
              ) : planView === 'dag' ? (
                <TaskGraph
                  tasks={tasks}
                  selectedId={selectedId}
                  onNodeClick={(task) => {
                    setSelectedId(task.task_id);
                    setPanelOpen(true);
                  }}
                />
              ) : (
                <TaskTimeline
                  tasks={tasks}
                  selectedId={selectedId}
                  onTaskClick={(task) => {
                    setSelectedId(task.task_id);
                    setPanelOpen(true);
                  }}
                />
              )}
            </div>
          </div>

          <div className="agent-bar">
            <strong>Block 状态：</strong>
            {['B01', 'B02', 'B03', 'B04', 'B05', 'B06'].map((block) => {
              const owned = tasks.filter((task) => task.block_id === block);
              const running = owned.filter((task) => task.status === 'RUNNING' || task.status === 'REVIEWING').length;
              return (
                <span key={block} className={`agent-chip ${running > 0 ? 'busy' : ''}`}>
                  {block}: {owned.length === 0 ? '无任务' : running > 0 ? `进行中 ${running}` : `${owned.length} 个任务`}
                </span>
              );
            })}
          </div>
        </div>

        {panelOpen && (
          <TaskDetailPanel
            task={selectedTask}
            dataSource={source}
            onClose={() => setPanelOpen(false)}
          />
        )}
      </div>
    </div>
  );
}

export default App;
