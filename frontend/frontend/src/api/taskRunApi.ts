/**
 * B05 真实接口适配层（D24/D25/D26）
 *
 * 只负责把 B02 的任务编排接口翻译成界面使用的 `Task` 结构，
 * 不做任何业务判定；界面必须能区分「模拟数据」与「真实接口」。
 *
 * 对应后端（docs/TASK_ORCHESTRATION.md §3）：
 *   GET /api/task-runs/{run_id}      → 运行快照
 *   GET /api/task-runs/{run_id}/dag  → DAG 视图
 *   GET /api/task-runs/{run_id}/events → 事件流
 */

import { normalizeStatus } from '../constants/status';
import type { DataSource, Task, TaskStatus } from '../types/task';

export interface RunSnapshot {
  run_id: string;
  plan_id: string;
  plan_version: string;
  input_snapshot: string;
  project_id: string;
  spec_version: string;
  contract_version: string;
  status: string;
  counts: Record<string, number>;
  completed: number;
  total: number;
  events_count: number;
  tasks: Record<string, unknown>[];
  topological_order: string[];
}

export interface DagNode {
  id: string;
  label: string;
  goal?: string;
  block_id?: string;
  role_id?: string;
  state: string;
  priority?: string;
  attempt_id?: number;
  retry_count?: number;
  duration_seconds?: number | null;
  blocked_reason?: string | null;
  acceptance?: string[];
  required_test_ids?: string[];
  candidate_commit?: string | null;
}

export interface DagPayload {
  run_id: string;
  plan_version: string;
  nodes: DagNode[];
  edges: { from: string; to: string; revalidation?: boolean }[];
  counts: Record<string, number>;
  topological_order: string[];
}

export interface RunEvent {
  event_id: string;
  sequence: number;
  type: string;
  task_id?: string | null;
  attempt_id?: number | null;
  plan_version: string;
  input_snapshot: string;
  candidate_commit?: string | null;
  producer?: string;
  payload?: Record<string, unknown>;
  occurred_at: string;
}

export interface TaskApiConfig {
  /** 后端根地址，例如 http://127.0.0.1:7100 */
  baseUrl: string;
  runId: string;
}

export interface CreateRunFromSpecConfig {
  baseUrl: string;
  specPath?: string;
  specText?: string;
  discussionRunId?: string;
}

export interface TaskApiResult {
  tasks: Task[];
  meta: {
    run_id: string;
    plan_version: string;
    spec_version: string;
    contract_version: string;
    input_snapshot: string;
    project_id: string;
    status: string;
    completed: number;
    total: number;
  };
  dag: DagPayload;
  events: RunEvent[];
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

function asNumber(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

/** 把 B02 快照里的单个任务记录映射成界面 Task。 */
export function mapSnapshotTask(raw: Record<string, unknown>, source: DataSource = 'real'): Task {
  const artifacts = Array.isArray(raw.artifacts) ? raw.artifacts : [];
  const knownIssues = Array.isArray(raw.known_issues) ? raw.known_issues : [];
  const review = (raw.review ?? null) as Task['review'];
  const findings = review?.findings ?? [];

  return {
    task_id: String(raw.task_id ?? ''),
    goal: String(raw.goal ?? ''),
    depends_on: asStringArray(raw.depends_on),
    status: normalizeStatus(raw.state) as TaskStatus,
    assignee: String(raw.role_id ?? raw.capability ?? raw.block_id ?? ''),
    spec_version: String(raw.spec_version ?? ''),
    contract_version: String(raw.contract_version ?? ''),
    input_snapshot: String(raw.input_snapshot ?? ''),
    attempt_id: asNumber(raw.attempt_id),
    retry_count: asNumber(raw.retry_count),
    write_scope: asStringArray(raw.write_scope),
    outputs: artifacts.map((item) => {
      const artifact = item as Record<string, unknown>;
      return {
        path: String(artifact.path ?? ''),
        version: String(artifact.sha256 ?? '').slice(0, 8),
        desc: String(artifact.kind ?? ''),
      };
    }),
    evidence: (Array.isArray(raw.attempts) ? raw.attempts : []).length
      ? []
      : asStringArray(raw.evidence_refs).map((ref) => ({ case_id: ref, passed: true, detail: '' })),
    objections: knownIssues.concat(findings as unknown as Record<string, unknown>[]).map((item, index) => {
      const issue = item as Record<string, unknown>;
      return {
        id: `${raw.task_id}-${index + 1}`,
        from: String(issue.severity ?? 'B06'),
        reason: String(issue.message ?? ''),
        status: 'open' as const,
        created_at: String(raw.finished_at ?? ''),
      };
    }),
    attempts: (Array.isArray(raw.attempts) ? raw.attempts : []).map((item) => {
      const attempt = item as Record<string, unknown>;
      const state = String(attempt.state ?? '');
      const result = state === 'SUCCEEDED' ? 'success' : state === 'RUNNING' ? 'running' : 'failure';
      return {
        attempt_id: asNumber(attempt.attempt_id),
        retry_count: asNumber(attempt.retry_count),
        started_at: String(attempt.started_at ?? ''),
        finished_at: attempt.finished_at ? String(attempt.finished_at) : null,
        result: result as 'success' | 'failure' | 'running',
        note: attempt.reason ? String(attempt.reason) : undefined,
      };
    }),
    blocked_reason: raw.blocked_reason ? String(raw.blocked_reason) : null,
    error: raw.error ? String(raw.error) : null,
    source,
    block_id: raw.block_id ? String(raw.block_id) : undefined,
    role_id: raw.role_id ? String(raw.role_id) : undefined,
    capability: raw.capability ? String(raw.capability) : undefined,
    priority: raw.priority ? String(raw.priority) : undefined,
    inputs: asStringArray(raw.inputs),
    design_refs: asStringArray(raw.design_refs),
    req_refs: asStringArray(raw.req_refs),
    acceptance: asStringArray(raw.acceptance),
    required_test_ids: asStringArray(raw.required_test_ids),
    candidate_commit: raw.candidate_commit ? String(raw.candidate_commit) : null,
    logs: (Array.isArray(raw.logs) ? raw.logs : []).map((item) => {
      const log = item as Record<string, unknown>;
      return { name: String(log.name ?? ''), sha256: String(log.sha256 ?? '') };
    }),
    duration_seconds: typeof raw.duration_seconds === 'number' ? raw.duration_seconds : null,
    started_at: raw.started_at ? String(raw.started_at) : null,
    finished_at: raw.finished_at ? String(raw.finished_at) : null,
    review,
  };
}

async function fetchJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, { signal, headers: { Accept: 'application/json' } });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as { error?: string };
      if (body?.error) detail = body.error;
    } catch {
      // 非 JSON 错误体：保留状态码描述
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

async function postJson<T>(url: string, body: unknown): Promise<T> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const raw = (await response.json()) as { error?: string };
      if (raw?.error) detail = raw.error;
    } catch {
      // 非 JSON 错误体：保留状态码描述
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export async function createTaskRunFromSpec(config: CreateRunFromSpecConfig): Promise<{
  plan: { plan_id: string; plan_version: string; task_count: number };
  run: RunSnapshot;
}> {
  const base = config.baseUrl.replace(/\/+$/, '');
  const body: Record<string, string> = {};
  if (config.specPath?.trim()) body.spec_path = config.specPath.trim();
  if (config.specText?.trim()) body.spec_text = config.specText;
  if (config.discussionRunId?.trim()) body.discussion_run_id = config.discussionRunId.trim();
  const endpoint = config.discussionRunId?.trim()
    ? '/api/task-runs/from-discussion'
    : '/api/task-runs/from-spec';
  return postJson(`${base}${endpoint}`, body);
}

export async function controlTaskRun(
  config: TaskApiConfig,
  action: 'step' | 'run',
  maxSteps = 200,
): Promise<void> {
  const base = config.baseUrl.replace(/\/+$/, '');
  const runId = encodeURIComponent(config.runId);
  await postJson(`${base}/api/task-runs/${runId}/${action}`, action === 'run' ? { max_steps: maxSteps } : {});
}

export interface RunEventsResult {
  run_id: string;
  events: RunEvent[];
}

/**
 * 增量拉取事件：后端 `/events?after=<sequence>` 只返回序号之后的新事件。
 * 监控循环用它替代全量事件请求，避免每次轮询都重复拉取整条事件流。
 */
export async function fetchRunEvents(
  config: TaskApiConfig,
  after: number,
  signal?: AbortSignal,
): Promise<RunEventsResult> {
  const base = config.baseUrl.replace(/\/+$/, '');
  const runId = encodeURIComponent(config.runId);
  const query = new URLSearchParams({ limit: '1000' });
  if (after >= 0) query.set('after', String(after));
  return fetchJson<RunEventsResult>(`${base}/api/task-runs/${runId}/events?${query}`, signal);
}

/** 触发后端按事件流重放状态，并与当前快照比对；返回一致性结果。 */
export async function replayTaskRun(config: TaskApiConfig): Promise<Record<string, unknown>> {
  const base = config.baseUrl.replace(/\/+$/, '');
  const runId = encodeURIComponent(config.runId);
  return postJson<Record<string, unknown>>(`${base}/api/task-runs/${runId}/replay`, {});
}

/** 断点恢复：由后端从持久化状态重建该运行。 */
export async function restoreTaskRun(config: TaskApiConfig): Promise<Record<string, unknown>> {
  const base = config.baseUrl.replace(/\/+$/, '');
  const runId = encodeURIComponent(config.runId);
  return fetchJson<Record<string, unknown>>(`${base}/api/task-runs/${runId}/restore`);
}

/** 拉取一个任务运行的真实快照 + DAG + 事件（首次全量加载）。 */
export async function fetchTaskRun(
  config: TaskApiConfig,
  signal?: AbortSignal,
  afterSequence?: number,
): Promise<TaskApiResult> {
  const base = config.baseUrl.replace(/\/+$/, '');
  const runId = encodeURIComponent(config.runId);
  const [snapshotResponse, dagResponse, eventsResponse] = await Promise.all([
    fetchJson<{ run: RunSnapshot }>(`${base}/api/task-runs/${runId}`, signal),
    fetchJson<{ dag: DagPayload }>(`${base}/api/task-runs/${runId}/dag`, signal),
    afterSequence === undefined
      ? fetchJson<{ events: RunEvent[] }>(`${base}/api/task-runs/${runId}/events?limit=5000`, signal)
      : fetchRunEvents(config, afterSequence, signal),
  ]);
  const run = snapshotResponse.run;
  if (!run || !Array.isArray(run.tasks)) {
    throw new Error('后端返回的 run 快照缺少 tasks 字段');
  }
  const tasks = run.tasks.map((item) => {
    const merged = { ...item, input_snapshot: run.input_snapshot };
    return mapSnapshotTask(merged, 'real');
  });
  return {
    tasks,
    meta: {
      run_id: run.run_id,
      plan_version: run.plan_version,
      spec_version: run.spec_version,
      contract_version: run.contract_version,
      input_snapshot: run.input_snapshot,
      project_id: run.project_id,
      status: run.status,
      completed: run.completed,
      total: run.total,
    },
    dag: dagResponse.dag,
    events: eventsResponse.events ?? [],
  };
}

/** 用事件流把 DAG 节点状态覆盖为「当前视图」，用于回放演示。 */
export function statusFromEvents(events: RunEvent[]): Record<string, TaskStatus> {
  const map: Record<string, TaskStatus> = {};
  const transitions: Record<string, TaskStatus> = {
    TASK_READY: 'READY',
    TASK_DISPATCHED: 'RUNNING',
    TASK_STARTED: 'RUNNING',
    TASK_OUTPUT_SUBMITTED: 'REVIEWING',
    TASK_REVIEW_REQUESTED: 'REVIEWING',
    TASK_ACCEPTED: 'SUCCEEDED',
    TASK_COMPLETED: 'SUCCEEDED',
    TASK_REJECTED: 'FAILED',
    TASK_RETRY_SCHEDULED: 'RETRYING',
    TASK_BLOCKED: 'BLOCKED',
    TASK_FAILED: 'FAILED',
  };
  for (const event of events) {
    const target = transitions[event.type];
    if (event.task_id && target) map[event.task_id] = target;
  }
  return map;
}
