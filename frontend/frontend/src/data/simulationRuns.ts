/**
 * B05：本地快照样例（模拟数据源）
 *
 * 数据来源是 `workflow_runtime/make_frontend_fixture.py` 用**真实编排器**
 *（B02 + B03 + B04 + B06）跑出来的运行结果，不是手工编造。
 * 因此「模拟数据」与「真实接口」只在**传输方式**上不同，字段结构完全一致。
 */

import raw from '../data/taskRunFixture.json';
import { normalizeStatus } from '../constants/status';
import type { Task, TaskStatus } from '../types/task';

interface FixtureTask {
  task_id: string;
  goal: string;
  block_id: string;
  role_id: string;
  capability: string;
  priority: string;
  depends_on: string[];
  req_refs: string[];
  design_refs: string[];
  inputs: string[];
  outputs: string[];
  acceptance: string[];
  required_test_ids: string[];
  write_scope: string[];
  state: string;
  attempt_id: number;
  retry_count: number;
  candidate_commit: string | null;
  evidence_refs: string[];
  known_issues: { code?: string; message?: string; severity?: string }[];
  blocked_reason: string | null;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  artifacts: { path: string; kind: string; sha256: string }[];
  review: { decision?: string; findings?: { code: string; severity: string; message: string }[] } | null;
  attempts: {
    attempt_id: number;
    retry_count: number;
    state: string;
    started_at?: string | null;
    finished_at?: string | null;
    reason?: string | null;
  }[];
}

interface FixtureRun {
  label: string;
  run: {
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
    topological_order: string[];
    tasks: FixtureTask[];
  };
  dag: {
    run_id: string;
    plan_version: string;
    nodes: { id: string; label: string; block_id: string; role_id: string; state: string }[];
    edges: { from: string; to: string; revalidation?: boolean }[];
    counts: Record<string, number>;
    topological_order: string[];
  };
  events: {
    event_id: string;
    sequence: number;
    type: string;
    task_id: string | null;
    attempt_id: number | null;
    occurred_at: string;
  }[];
}

interface FixtureFile {
  generated_at: string;
  note: string;
  runs: Record<string, FixtureRun>;
}

const fixture = raw as unknown as FixtureFile;

export interface SimulationRun {
  key: string;
  label: string;
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
    events_count: number;
  };
  events: { sequence: number; type: string; task_id: string | null; attempt_id: number | null; occurred_at: string }[];
}

export const FIXTURE_GENERATED_AT = fixture.generated_at;
export const FIXTURE_NOTE = fixture.note;

function toTask(item: FixtureTask, inputSnapshot: string): Task {
  return {
    task_id: item.task_id,
    goal: item.goal,
    depends_on: item.depends_on,
    status: normalizeStatus(item.state) as TaskStatus,
    assignee: item.role_id || item.capability || item.block_id,
    spec_version: '',
    contract_version: '',
    input_snapshot: inputSnapshot,
    attempt_id: item.attempt_id,
    retry_count: item.retry_count,
    write_scope: item.write_scope,
    outputs: item.artifacts.map((artifact) => ({
      path: artifact.path,
      version: artifact.sha256.slice(0, 8),
      desc: artifact.kind,
    })),
    evidence: item.evidence_refs.map((ref) => ({ case_id: ref, passed: true, detail: '' })),
    objections: (item.review?.findings ?? [])
      .filter((finding) => finding.severity === 'blocking')
      .map((finding, index) => ({
        id: `${item.task_id}-F${index + 1}`,
        from: finding.severity ?? 'B06',
        reason: `${finding.code}: ${finding.message}`,
        status: 'open' as const,
        created_at: item.finished_at ?? '',
      })),
    attempts: item.attempts.map((attempt) => ({
      attempt_id: attempt.attempt_id,
      retry_count: attempt.retry_count,
      started_at: attempt.started_at ?? '',
      finished_at: attempt.finished_at ?? null,
      result:
        attempt.state === 'SUCCEEDED'
          ? ('success' as const)
          : attempt.state === 'RUNNING'
            ? ('running' as const)
            : ('failure' as const),
      note: attempt.reason ?? undefined,
    })),
    blocked_reason: item.blocked_reason,
    error: item.error,
    source: 'simulation',
    block_id: item.block_id,
    role_id: item.role_id,
    capability: item.capability,
    priority: item.priority,
    inputs: item.inputs,
    design_refs: item.design_refs,
    req_refs: item.req_refs,
    acceptance: item.acceptance,
    required_test_ids: item.required_test_ids,
    candidate_commit: item.candidate_commit,
    logs: [],
    duration_seconds: item.duration_seconds,
    started_at: item.started_at,
    finished_at: item.finished_at,
    review: item.review
      ? { decision: item.review.decision, findings: item.review.findings ?? [] }
      : null,
  };
}

export function listSimulationRuns(): { key: string; label: string }[] {
  return Object.entries(fixture.runs).map(([key, value]) => ({ key, label: value.label }));
}

export function loadSimulationRun(key: string): SimulationRun | null {
  const run = fixture.runs[key];
  if (!run) return null;
  return {
    key,
    label: run.label,
    tasks: run.run.tasks.map((item) => toTask(item, run.run.input_snapshot)),
    meta: {
      run_id: run.run.run_id,
      plan_version: run.run.plan_version,
      spec_version: run.run.spec_version,
      contract_version: run.run.contract_version,
      input_snapshot: run.run.input_snapshot,
      project_id: run.run.project_id,
      status: run.run.status,
      completed: run.run.completed,
      total: run.run.total,
      events_count: run.run.events_count,
    },
    events: run.events.map((event) => ({
      sequence: event.sequence,
      type: event.type,
      task_id: event.task_id,
      attempt_id: event.attempt_id,
      occurred_at: event.occurred_at,
    })),
  };
}
