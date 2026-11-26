import { useCallback, useEffect, useMemo, useState } from 'react';
import { loadSimulationRun, listSimulationRuns, type SimulationRun } from './data/simulationRuns';
import { ActivityLog } from './components/ActivityLog';
import { AgentExecutionView } from './components/AgentExecutionView';
import { HistoryView } from './components/HistoryView';
import { ProjectOverview, type CurrentProject } from './components/ProjectOverview';
import { RequirementsView } from './components/RequirementsView';
import { StageNav, type StageKey } from './components/StageNav';
import { TaskDetailPanel } from './components/TaskDetailPanel';
import { TaskGraph } from './components/TaskGraph';
import { TaskTimeline } from './components/TaskTimeline';
import { TimelineView } from './components/TimelineView';
import { VersionChain } from './components/VersionChain';
import { ALL_STATUSES, statusColors, statusLabels } from './constants/status';
import {
  createTaskRunFromDiscussion,
  createTaskRunFromSpec,
  fetchLlmConfig,
  type LlmConfigStatus,
  type RunEvent,
  updateLlmConfig,
} from './api/taskRunApi';
import {
  advanceDiscussion,
  confirmDiscussion,
  createDiscussionRun,
  getDesignSpec,
  type DiscussionRun,
} from './api/workbenchApi';
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
type PlanView = 'dag' | 'gantt' | 'timeline' | 'activity';

const STAGE_TITLES: Record<StageKey, string> = {
  overview: '项目总览',
  discussion: '项目主理人',
  requirements: '需求与方案',
  spec: '规格与计划',
  orchestrate: '开发任务 DAG',
  agents: 'Agent 执行中心',
  delivery: '成果交付',
  history: '历史项目',
};

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
    <div className="stat-card">
      <span className="stat-label">{label}</span>
      <b className="stat-value" style={{ color, background: bg }}>{value}</b>
    </div>
  );
}

function App() {
  const [source, setSource] = useState<DataSource>('simulation');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [panelOpen, setPanelOpen] = useState(true);
  // 默认停留在「编排与执行」：保留原有工作流监控、DAG 与调试入口。
  const [stage, setStage] = useState<StageKey>('orchestrate');
  const [planView, setPlanView] = useState<PlanView>('dag');

  // 模拟数据源：选择由真实编排器跑出的历史运行
  const runs = useMemo(() => listSimulationRuns(), []);
  const [simRunKey, setSimRunKey] = useState<string>(() => runs[0]?.key ?? '');
  const simulation = useMemo<SimulationRun | null>(() => loadSimulationRun(simRunKey), [simRunKey]);

  // 真实数据源：连接 B02 的任务运行
  const [apiBase, setApiBase] = useState(DEFAULT_API_BASE);
  const [runIdInput, setRunIdInput] = useState('TASK-RUN-DEMO');
  const [submittedRunId, setSubmittedRunId] = useState('');

  // 第二阶段入口：设计规格 → PM Agent → 编排器
  const [specPath, setSpecPath] = useState('b01-spec-planner/docs/fixtures/campus-lost-found.spec.json');
  const [launching, setLaunching] = useState(false);

  // 第一阶段：用户想法 → 讨论 → R1
  const [discussionIdea, setDiscussionIdea] = useState('');
  const [discussionConstraints, setDiscussionConstraints] = useState('');
  const [discussion, setDiscussion] = useState<DiscussionRun | null>(null);
  const [discussionBusy, setDiscussionBusy] = useState(false);
  const [discussionRunId, setDiscussionRunId] = useState('');
  const [workbenchError, setWorkbenchError] = useState('');

  // 设计规格查看
  const [sourceRunId, setSourceRunId] = useState('');
  const [designSpec, setDesignSpec] = useState<Record<string, unknown> | null>(null);
  const [specLoading, setSpecLoading] = useState(false);

  // 模型 API 配置
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
  const activityEvents = isReal ? real.events : simulation?.events ?? [];

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

  const currentProject = useMemo<CurrentProject | null>(() => {
    if (!meta) return null;
    return {
      runId: meta.run_id,
      projectId: meta.project_id,
      status: meta.status,
      completed: meta.completed,
      total: meta.total,
      specVersion: meta.spec_version,
    };
  }, [meta]);

  const simulationProjects = useMemo<CurrentProject[]>(
    () => runs.flatMap((item) => {
      const data = loadSimulationRun(item.key);
      if (!data) return [];
      return [{
        runId: data.meta.run_id,
        projectId: data.meta.project_id,
        status: data.meta.status,
        completed: data.meta.completed,
        total: data.meta.total,
        specVersion: data.meta.spec_version,
      }];
    }),
    [runs],
  );

  const deliverables = useMemo(
    () => tasks.flatMap((task) => task.outputs.map((output) => ({ ...output, task_id: task.task_id }))),
    [tasks],
  );
  const deliveryEvidences = useMemo(
    () => tasks.flatMap((task) => task.evidence.map((item) => ({ ...item, task_id: task.task_id }))),
    [tasks],
  );

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

  /** 从项目总览 / 历史项目进入某个任务运行。 */
  const handleOpenRun = useCallback((runId: string) => {
    setRunIdInput(runId);
    setSubmittedRunId(runId);
    setSource('real');
    setSelectedId(null);
    setStage('orchestrate');
  }, []);

  /** 从项目总览 / 历史项目进入某次需求讨论。 */
  const handleOpenDiscussion = useCallback((runId: string) => {
    setDiscussionRunId(runId);
    setStage('requirements');
  }, []);

  /** 项目主理人提交想法：真实写入 B02 讨论服务。 */
  const handleCreateDiscussion = useCallback(async (payload: {
    idea: string;
    constraints: string;
    scenario: string;
    max_rounds: number;
  }) => {
    const created = await createDiscussionRun(apiBase, payload);
    setDiscussion(created.run);
    setDiscussionRunId(created.run.run_id);
    setSourceRunId(created.run.run_id);
    setDesignSpec(null);
    setWorkbenchError('');
    setStage('requirements');
  }, [apiBase]);

  const handleAdvanceDiscussion = useCallback(async () => {
    if (!discussion) return;
    setDiscussionBusy(true);
    setWorkbenchError('');
    try {
      const advanced = await advanceDiscussion(apiBase, discussion.run_id);
      setDiscussion(advanced.run);
    } catch (caught) {
      setWorkbenchError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setDiscussionBusy(false);
    }
  }, [apiBase, discussion]);

  const handleConfirmDiscussion = useCallback(async () => {
    if (!discussion) return;
    setDiscussionBusy(true);
    setWorkbenchError('');
    try {
      const confirmed = await confirmDiscussion(apiBase, discussion.run_id, CONFIRMATION_MEMBERS);
      setDiscussion(confirmed.run);
    } catch (caught) {
      setWorkbenchError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setDiscussionBusy(false);
    }
  }, [apiBase, discussion]);

  /** 已确认 R1 → 设计规格 → 任务运行（阶段桥接）。 */
  const handleBridgeDiscussion = useCallback(async (runId?: string) => {
    const target = (runId ?? discussion?.run_id ?? discussionRunId).trim();
    if (!target) return;
    setDiscussionBusy(true);
    setWorkbenchError('');
    try {
      const created = await createTaskRunFromDiscussion(apiBase, target);
      setDesignSpec(created.source);
      setSourceRunId(target);
      setRunIdInput(created.run.run_id);
      setSubmittedRunId(created.run.run_id);
      setSource('real');
      setSelectedId(null);
      setStage('orchestrate');
    } catch (caught) {
      setWorkbenchError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setDiscussionBusy(false);
    }
  }, [apiBase, discussion?.run_id, discussionRunId]);

  const handleCreateFromSpec = useCallback(async () => {
    setLaunching(true);
    try {
      const created = await createTaskRunFromSpec({ baseUrl: apiBase, specPath });
      setRunIdInput(created.run.run_id);
      setSubmittedRunId(created.run.run_id);
      setSource('real');
      setSelectedId(null);
      setStage('orchestrate');
    } catch (caught) {
      setWorkbenchError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setLaunching(false);
    }
  }, [apiBase, specPath]);

  const handleLoadDesignSpec = useCallback(async () => {
    if (!sourceRunId.trim()) return;
    setSpecLoading(true);
    setWorkbenchError('');
    try {
      const spec = await getDesignSpec(apiBase, sourceRunId.trim());
      setDesignSpec(spec.design_spec);
    } catch (caught) {
      setWorkbenchError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setSpecLoading(false);
    }
  }, [apiBase, sourceRunId]);

  const handleSaveLlmConfig = useCallback(async () => {
    setLlmSaving(true);
    setWorkbenchError('');
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
      setWorkbenchError(caught instanceof Error ? caught.message : String(caught));
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

  const selectTask = useCallback((taskId: string) => {
    setSelectedId(taskId);
    setPanelOpen(true);
  }, []);

  const openTaskInGraph = useCallback((taskId: string) => {
    setStage('orchestrate');
    setPlanView('dag');
    selectTask(taskId);
  }, [selectTask]);

  const connectionLabel = isReal
    ? real.error
      ? '真实接口 · 连接失败'
      : real.connection === 'offline'
        ? '真实接口 · 已离线（最近快照）'
        : real.connection === 'degraded'
          ? '真实接口 · 重连中'
          : real.connection === 'syncing'
            ? '真实接口 · 同步中…'
            : '真实接口 · 已同步'
    : '模拟数据 · 真实编排器产物';

  const exportButtons = (withWorkflow: boolean) => (
    <div className="exports">
      <span className="exports-label">成果导出</span>
      <button onClick={() => exportSnapshot(tasks, buildExportContext())}>快照 JSON</button>
      {withWorkflow && (
        <>
          <button onClick={() => exportWorkflow(tasks, buildExportContext())}>workflow.json</button>
          <button onClick={() => exportTaskMarkdown(tasks, buildExportContext())}>task.md</button>
        </>
      )}
      <button onClick={() => exportTraceability(tasks, buildExportContext())}>追溯表 CSV</button>
      <button onClick={() => exportDefects(tasks, buildExportContext())}>缺陷清单</button>
      <button onClick={() => exportRunReport(tasks, reportLogs, reportAcks, buildExportContext())}>运行报告</button>
    </div>
  );

  const planViewLabel: Record<PlanView, string> = {
    dag: '依赖 DAG',
    gantt: '甘特排期',
    timeline: '时间线',
    activity: '事件流',
  };

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="header-title">
          <h1>多智能体协作开发平台 · {STAGE_TITLES[stage]}</h1>
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
              className="run-select"
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

          <span className={`source-badge ${isReal ? 'real' : 'sim'}`}>{connectionLabel}</span>
        </div>
      </header>

      <StageNav value={stage} onChange={setStage} />

      {workbenchError && (
        <div className="global-workbench-error" role="alert">
          工作台操作失败：{workbenchError}
          <button type="button" onClick={() => setWorkbenchError('')}>关闭</button>
        </div>
      )}

      <div className="app-main">
        <div className="app-content">
          {stage === 'overview' && (
            <ProjectOverview
              key={`overview-${source}`}
              apiBase={apiBase}
              source={source}
              currentProject={currentProject}
              simulationProjects={simulationProjects}
              selectedRunId={submittedRunId}
              onOpenRun={handleOpenRun}
              onOpenDiscussion={handleOpenDiscussion}
              onCreate={handleCreateDiscussion}
            />
          )}

          {stage === 'discussion' && (
            <div className="stage-panel">
              <div className="stage-panel-head">
                <h2>02 · 项目主理人</h2>
                <p>
                  输入用户想法，交给多智能体讨论；推进到需求确认、完成六人确认后发布 R1，
                  再由已确认的 R1 进入第二阶段任务编排。
                </p>
              </div>

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
                  {['用户想法', '多体讨论', 'R1 确认', '设计规格', '任务分解', '任务编排', '执行验收', '可视化'].map((item, index) => (
                    <span key={item} className={index < 4 && (discussion?.status === 'COMPLETED' || Boolean(meta)) ? 'done' : ''}>
                      <b>{index + 1}</b>{item}
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
                      <button onClick={() => void handleCreateDiscussion({
                        idea: discussionIdea,
                        constraints: discussionConstraints,
                        scenario: 'normal',
                        max_rounds: 2,
                      })} disabled={discussionBusy || !discussionIdea.trim()}>
                        创建讨论运行
                      </button>
                      <button onClick={() => void handleAdvanceDiscussion()} disabled={discussionBusy || !discussion}>
                        运行到需求确认
                      </button>
                      <button
                        onClick={() => void handleConfirmDiscussion()}
                        disabled={discussionBusy || !discussion || discussion.stage !== 'HUMAN_CONFIRMATION'}
                      >
                        六人确认 R1
                      </button>
                      <button
                        onClick={() => void handleBridgeDiscussion()}
                        disabled={discussionBusy || !discussion || discussion.status !== 'COMPLETED'}
                      >
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
                    <h3>由已有讨论结果创建任务运行</h3>
                    <p className="muted">
                      输入讨论运行编号，调用后端 <code>POST /api/task-runs/from-discussion</code>，
                      由已确认的 R1 生成设计规格与任务计划。
                    </p>
                    <div className="spec-source-row">
                      <input
                        aria-label="讨论运行编号"
                        value={discussionRunId}
                        onChange={(event) => setDiscussionRunId(event.target.value)}
                        placeholder="RUN-XXXXXXXXXX"
                      />
                      <button
                        onClick={() => void handleBridgeDiscussion(discussionRunId)}
                        disabled={discussionBusy || !discussionRunId.trim()}
                      >
                        进入第二阶段
                      </button>
                    </div>
                    <div className="workbench-actions">
                      <button type="button" onClick={() => setStage('requirements')} disabled={!discussionRunId.trim()}>
                        查看需求与方案
                      </button>
                    </div>
                    <a
                      className="link-button"
                      href={`${apiBase.replace(/\/+$/, '')}/`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      打开 B02 讨论页 ↗
                    </a>
                  </div>

                  <div className="workbench-card">
                    <h3>六人确认与阶段门槛</h3>
                    <p className="muted">
                      R1 只在六名成员全部确认后发布；未确认的讨论不能进入第二阶段。
                      确认动作由 B02 状态机裁决，前端只发送指令。
                    </p>
                    <ul className="plain-list">
                      {CONFIRMATION_MEMBERS.map((member) => (
                        <li key={member}>
                          {member}
                          {discussion?.blackboard?.r1 ? ' · 已确认' : ' · 待确认'}
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              </section>
            </div>
          )}

          {stage === 'requirements' && (
            <RequirementsView
              key={`requirements-${source}`}
              apiBase={apiBase}
              source={source}
              selectedRunId={discussionRunId}
              onSelectRun={setDiscussionRunId}
              onCreateTaskRun={(runId) => void handleBridgeDiscussion(runId)}
            />
          )}

          {stage === 'spec' && (
            <div className="stage-panel">
              <div className="stage-panel-head">
                <h2>04 · 规格与计划</h2>
                <p>
                  设计规格经 PM Agent 生成任务计划；版本链展示当前运行绑定的规格 / 契约 / 计划 / 快照。
                  模型 API 配置决定第一阶段需求草案由真实模型还是本地规则生成。
                </p>
              </div>

              <VersionChain meta={meta} sourceLabel={isReal ? '真实运行' : '模拟运行'} />

              <section className="workbench-panel">
                <div className="workbench-heading">
                  <div>
                    <strong>模型 API 配置</strong>
                    <span>支持 DeepSeek 和其他 OpenAI-compatible 服务。密钥只保存在当前后端进程内。</span>
                  </div>
                  <span className={`llm-status ${llmConfig?.enabled ? 'ready' : 'local'}`}>
                    {llmConfig?.enabled ? `模型已连接 · ${llmConfig.model}` : '本地规则兜底'}
                  </span>
                </div>
                <div className="config-grid">
                  <input
                    aria-label="模型 API 地址"
                    value={llmBaseUrl}
                    onChange={(event) => setLlmBaseUrl(event.target.value)}
                    placeholder="https://api.deepseek.com"
                  />
                  <input
                    aria-label="模型名称"
                    value={llmModel}
                    onChange={(event) => setLlmModel(event.target.value)}
                    placeholder="deepseek-chat"
                  />
                  <input
                    aria-label="模型 API Key"
                    type="password"
                    value={llmApiKey}
                    onChange={(event) => setLlmApiKey(event.target.value)}
                    placeholder={llmConfig?.key_configured ? '已配置，输入新 Key 可替换' : '输入 API Key'}
                  />
                  <button onClick={() => void handleSaveLlmConfig()} disabled={llmSaving || !llmApiKey.trim()}>
                    {llmSaving ? '保存中…' : '保存并启用'}
                  </button>
                </div>
              </section>

              <section className="workbench-panel">
                <div className="workbench-heading">
                  <div>
                    <strong>设计规格查看</strong>
                    <span>输入第一阶段 RUN 编号，查看实际桥接后的 design spec。</span>
                  </div>
                </div>
                <div className="spec-source-row">
                  <input
                    aria-label="第一阶段运行编号"
                    value={sourceRunId}
                    onChange={(event) => setSourceRunId(event.target.value)}
                    placeholder="RUN-XXXXXXXXXX"
                  />
                  <button onClick={() => void handleLoadDesignSpec()} disabled={specLoading || !sourceRunId.trim()}>
                    {specLoading ? '读取中…' : '查看规格'}
                  </button>
                </div>
                {designSpec && (
                  <details className="spec-preview" open>
                    <summary>
                      {String(designSpec.title ?? '已加载 design spec')} ·{' '}
                      {Array.isArray(designSpec.requirements) ? designSpec.requirements.length : 0} 项需求
                    </summary>
                    <pre>{JSON.stringify(designSpec, null, 2)}</pre>
                  </details>
                )}
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
                <button onClick={() => void handleCreateFromSpec()} disabled={launching || !specPath.trim()}>
                  {launching ? '正在生成计划…' : '从设计规格启动'}
                </button>
              </div>

              <div className="stage-card">
                <h3>为什么保留模拟数据源</h3>
                <p className="muted">
                  模拟快照由真实编排器跑出，只在传输方式上与真实接口不同。切换数据源后所有版本字段都会随之更新，
                  便于答辩时对照演示。
                </p>
              </div>
            </div>
          )}

          {stage === 'orchestrate' && (
            <>
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
                {exportButtons(true)}
              </div>

              <div className="run-controls">
                <strong>运行控制：</strong>
                <button onClick={() => void real.step()} disabled={!isReal || !submittedRunId || real.loading}>
                  推进一步
                </button>
                <button onClick={() => void real.runToCompletion()} disabled={!isReal || !submittedRunId || real.loading}>
                  运行至完成
                </button>
                <button onClick={() => void real.replay()} disabled={!isReal || !submittedRunId || real.loading}>
                  回放校验
                </button>
                <button onClick={() => void real.restore()} disabled={!isReal || !submittedRunId || real.loading}>
                  断点恢复
                </button>
                <span className="hint">
                  事件游标 #{real.eventCursor} · {isReal && real.lastUpdated
                    ? `最近同步 ${new Date(real.lastUpdated).toLocaleTimeString()}`
                    : '模拟数据不发送控制指令'}
                </span>
              </div>

              {real.replayResult && isReal && (
                <div className={`alert ${real.replayResult.consistent ? 'success-alert' : 'error'}`}>
                  回放校验：{real.replayResult.consistent
                    ? '与快照一致'
                    : `发现 ${real.replayResult.mismatches.length} 处不一致`}
                  （{real.replayResult.eventCount} 条事件，末序号 #{real.replayResult.lastSequence}）
                </div>
              )}

              {isReal && real.error && (
                <div className="alert error" role="alert">
                  无法读取真实任务运行：{real.error}
                  <div className="muted detail-hint">
                    请确认 B02 服务已启动（python -m backend.app），并已通过
                    <code> POST /api/task-runs</code> 创建该运行编号。
                    {tasks.length > 0 ? ' 当前显示的是最近一次成功同步的快照。' : ''}
                  </div>
                </div>
              )}

              <div className="graph-area">
                <div className="plan-view-switch" role="group" aria-label="任务计划视图">
                  <strong>任务计划视图</strong>
                  {(['dag', 'gantt', 'timeline', 'activity'] as PlanView[]).map((option) => (
                    <button
                      key={option}
                      className={planView === option ? 'active' : ''}
                      onClick={() => setPlanView(option)}
                    >
                      {planViewLabel[option]}
                    </button>
                  ))}
                  <span>{tasks.length} 个任务 · {new Set(tasks.flatMap((task) => task.depends_on)).size} 条依赖引用</span>
                </div>
                {planView === 'dag' && (
                  <div className="legend">
                    <strong>状态图例：</strong>
                    {ALL_STATUSES.map((status) => (
                      <span key={status} className="legend-item">
                        <i style={{ background: statusColors[status] }} />
                        {statusLabels[status]}
                      </span>
                    ))}
                  </div>
                )}

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
                      onNodeClick={(task) => selectTask(task.task_id)}
                    />
                  ) : planView === 'gantt' ? (
                    <TaskTimeline
                      tasks={tasks}
                      selectedId={selectedId}
                      onTaskClick={(task) => selectTask(task.task_id)}
                    />
                  ) : planView === 'timeline' ? (
                    <TimelineView
                      tasks={tasks}
                      selectedId={selectedId}
                      onSelect={(task) => selectTask(task.task_id)}
                    />
                  ) : (
                    <ActivityLog events={activityEvents} cursor={real.eventCursor} />
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
                <button type="button" className="text-link" onClick={() => setStage('agents')}>
                  查看 Agent 执行中心 →
                </button>
              </div>
            </>
          )}

          {stage === 'agents' && (
            <AgentExecutionView
              tasks={tasks}
              events={activityEvents}
              source={source}
              onSelectTask={openTaskInGraph}
            />
          )}

          {stage === 'delivery' && (
            <div className="stage-panel delivery-stage">
              <div className="stage-panel-head">
                <h2>07 · 成果交付</h2>
                <p>
                  展示项目代码、生成文件、测试报告和最终交付物。真实产物来自任务快照，
                  案例界面按 C1 契约字段映射并标注为样例。
                </p>
              </div>

              <div className={`source-note ${isReal ? 'real' : 'sim'}`}>
                {isReal
                  ? '真实数据：以下交付物来自任务快照的 artifacts / evidence / logs 字段。'
                  : '演示数据：交付物来自真实编排器产出的本地快照，案例界面为样例数据。'}
              </div>

              {tasks.length === 0 ? (
                <div className="stage-card">
                  <p>尚未加载任务运行，没有可展示的交付物。请到「编排与执行」输入运行编号。</p>
                </div>
              ) : (
                <div className="delivery-grid">
                  <section className="requirement-section">
                    <h3>生成文件与产物（{deliverables.length}）</h3>
                    {deliverables.length === 0 ? (
                      <p className="empty-state">当前运行还没有登记产物</p>
                    ) : (
                      <div className="table-wrap">
                        <table>
                          <thead><tr><th>任务</th><th>路径</th><th>版本 / 哈希</th><th>说明</th></tr></thead>
                          <tbody>
                            {deliverables.map((item, index) => (
                              <tr key={`${item.task_id}-${item.path}-${index}`}>
                                <td>
                                  <button type="button" className="text-link" onClick={() => openTaskInGraph(item.task_id)}>
                                    {item.task_id}
                                  </button>
                                </td>
                                <td className="mono">{item.path}</td>
                                <td className="mono">{item.version}</td>
                                <td>{item.desc || '—'}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </section>

                  <section className="requirement-section">
                    <h3>测试报告（{deliveryEvidences.length} 项证据）</h3>
                    {deliveryEvidences.length === 0 ? (
                      <p className="empty-state">当前运行还没有登记测试证据</p>
                    ) : (
                      <ul className="delivery-evidence">
                        {deliveryEvidences.map((item, index) => (
                          <li key={`${item.task_id}-${item.case_id}-${index}`}>
                            <span className={item.passed ? 'ok' : 'bad'}>{item.passed ? '通过' : '未通过'}</span>
                            <strong>{item.case_id}</strong>
                            <small>{item.task_id}</small>
                            <span>{item.detail || '—'}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </section>

                  <section className="requirement-section">
                    <h3>运行导出</h3>
                    {exportButtons(true)}
                  </section>
                </div>
              )}
            </div>
          )}

          {stage === 'history' && (
            <HistoryView
              key={`history-${source}`}
              apiBase={apiBase}
              source={source}
              onOpenDiscussion={handleOpenDiscussion}
              onOpenRun={handleOpenRun}
            />
          )}
        </div>

        {panelOpen && stage === 'orchestrate' && (
          <TaskDetailPanel
            task={selectedTask}
            dataSource={source}
            onClose={() => setPanelOpen(false)}
            onSelectTask={selectTask}
            onStep={() => void real.step()}
            onRun={() => void real.runToCompletion()}
            canControl={isReal && Boolean(submittedRunId)}
            busy={real.loading}
          />
        )}
      </div>
    </div>
  );
}

export default App;
