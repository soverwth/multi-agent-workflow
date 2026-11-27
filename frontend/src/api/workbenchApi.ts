/**
 * B05 工作台接口适配层
 *
 * 只读取 B02 已经提供的 HTTP 接口，不在前端生成任何项目、需求或执行结果。
 * 覆盖：
 *   GET  /api/runs                     讨论运行列表（历史项目 / 项目总览）
 *   GET  /api/runs/{id}                讨论详情（需求分析与人工确认）
 *   POST /api/runs                     提交项目想法，创建讨论运行
 *   GET  /api/runs/{id}/design-spec    设计规格（规格与计划）
 *   GET  /api/task-runs                任务运行列表（项目进度 / 历史项目）
 */

export interface RequirementItem {
  req_id: string;
  description: string;
  acceptance: string | string[];
  priority?: string;
  status?: string;
}

export interface R1Result {
  requirements: RequirementItem[];
  confirmed_by: string[];
  [key: string]: unknown;
}

export interface DiscussionClaim {
  claim_id: string;
  role: string;
  claim: string;
  reason?: string;
  evidence?: string;
  impact?: string;
  round?: number;
}

export interface DiscussionObjection {
  objection_id: string;
  raised_by: string;
  target_id?: string;
  content: string;
  category?: string;
  severity?: string;
  status?: string;
  response?: string;
}

export interface DiscussionSignoff {
  role: string;
  stance: string;
  reason?: string;
}

export interface Blackboard {
  idea?: string;
  constraints?: string;
  problem?: string;
  assumptions?: string[];
  claims?: DiscussionClaim[];
  objections?: DiscussionObjection[];
  decisions?: { decision_id?: string; decided_by?: string; content?: string; time?: string }[];
  open_questions?: string[];
  proposal_draft?: string;
  signoffs?: DiscussionSignoff[];
  requirements_draft?: { requirements?: RequirementItem[] } | null;
  r1?: R1Result | null;
}

export interface DiscussionRun {
  run_id: string;
  idea: string;
  constraints?: string;
  scenario?: string;
  stage: string;
  status: string;
  round?: number;
  max_rounds?: number;
  created_at?: string;
  updated_at?: string;
  blackboard?: Blackboard;
  latest_consensus?: {
    reason?: string;
    open_count?: number;
    high_count?: number;
    needs_human?: boolean;
    can_proceed?: boolean;
  } | null;
  failure?: { message?: string; stage?: string } | null;
  events?: { type?: string; time?: string; stage?: string; status?: string }[];
}

export interface TaskRunSummary {
  run_id: string;
  plan_id?: string;
  plan_version?: string;
  project_id?: string;
  status?: string;
  created_at?: string;
  updated_at?: string;
}

export interface CreateDiscussionPayload {
  idea: string;
  constraints?: string;
  scenario?: string;
  max_rounds?: number;
}

async function fetchJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, { signal, headers: { Accept: 'application/json' } });
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { error?: string };
      if (body?.error) detail = body.error;
    } catch {
      // 非 JSON 错误体：保留状态码
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
    let detail = `HTTP ${response.status}`;
    try {
      const data = (await response.json()) as { error?: string };
      if (data?.error) detail = data.error;
    } catch {
      // 非 JSON 错误体：保留状态码
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

function baseOf(baseUrl: string): string {
  return baseUrl.replace(/\/+$/, '');
}

/** 讨论运行列表：项目总览与历史项目的数据源。 */
export function listDiscussionRuns(baseUrl: string, signal?: AbortSignal): Promise<{ runs: DiscussionRun[] }> {
  return fetchJson(`${baseOf(baseUrl)}/api/runs`, signal);
}

/** 单个讨论运行详情：需求分析与人工确认结果。 */
export function getDiscussionRun(
  baseUrl: string,
  runId: string,
  signal?: AbortSignal,
): Promise<{ run: DiscussionRun }> {
  return fetchJson(`${baseOf(baseUrl)}/api/runs/${encodeURIComponent(runId)}`, signal);
}

/** 项目主理人提交项目想法，创建讨论运行（真实写入 B02，前端不伪造）。 */
export function createDiscussionRun(
  baseUrl: string,
  payload: CreateDiscussionPayload,
): Promise<{ run: DiscussionRun }> {
  return postJson(`${baseOf(baseUrl)}/api/runs`, payload);
}

/** 由讨论结论生成的设计规格。 */
export function getDesignSpec(
  baseUrl: string,
  runId: string,
  signal?: AbortSignal,
): Promise<{ design_spec: Record<string, unknown>; source_run_id: string }> {
  return fetchJson(`${baseOf(baseUrl)}/api/runs/${encodeURIComponent(runId)}/design-spec`, signal);
}

/** 推进讨论到下一个控制点（阶段边界 / 诚实停止）。 */
export function advanceDiscussion(baseUrl: string, runId: string): Promise<{ run: DiscussionRun }> {
  return postJson(`${baseOf(baseUrl)}/api/runs/${encodeURIComponent(runId)}/until-control-point`, {});
}

/**
 * agent 共识确认并发布 R1。
 *
 * 任务文档要求无人工审批门：确认由 agent 角色各自表态达成共识后完成，前端不再提交"六名成员"名单。
 * 后端 `POST /api/runs/{id}/confirm` 目前仍要求 members 字段；过渡期传入 agent 角色名单（ROLES），
 * 后端改造为 agent 互相确认后，此接口将不再需要参数。
 */
export function confirmDiscussionByConsensus(
  baseUrl: string,
  runId: string,
  roles: string[],
): Promise<{ run: DiscussionRun }> {
  return postJson(`${baseOf(baseUrl)}/api/runs/${encodeURIComponent(runId)}/confirm`, { members: roles });
}

/** 任务运行列表：展示项目阶段与完成进度的真实来源。 */
export function listTaskRuns(baseUrl: string, signal?: AbortSignal): Promise<{ runs: TaskRunSummary[] }> {
  return fetchJson(`${baseOf(baseUrl)}/api/task-runs`, signal);
}
