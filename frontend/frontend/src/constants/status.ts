import type { TaskStatus } from '../types/task';

/**
 * 状态配色与文案（供节点、图例、详情面板共用）
 *
 * 与 docs/TASK_ORCHESTRATION.md §1 的九态一一对应：
 * PENDING / READY / RUNNING / WAITING_DEPENDENCY / REVIEWING
 * / FAILED / RETRYING / BLOCKED / SUCCEEDED
 */
export const statusColors: Record<TaskStatus, string> = {
  PENDING: '#94a3b8',
  READY: '#3b82f6',
  RUNNING: '#f59e0b',
  WAITING_DEPENDENCY: '#a5b4fc',
  REVIEWING: '#8b5cf6',
  SUCCEEDED: '#22c55e',
  FAILED: '#ef4444',
  RETRYING: '#f97316',
  BLOCKED: '#64748b',
};

export const statusLabels: Record<TaskStatus, string> = {
  PENDING: '已生成',
  READY: '就绪',
  RUNNING: '执行中',
  WAITING_DEPENDENCY: '等依赖',
  REVIEWING: '验收中',
  SUCCEEDED: '已通过',
  FAILED: '失败',
  RETRYING: '重试中',
  BLOCKED: '已阻塞',
};

export const ALL_STATUSES: TaskStatus[] = [
  'PENDING',
  'READY',
  'RUNNING',
  'WAITING_DEPENDENCY',
  'REVIEWING',
  'FAILED',
  'RETRYING',
  'BLOCKED',
  'SUCCEEDED',
];

/** 视为“进行中”的状态，用于统计与连线动画。 */
export const ACTIVE_STATUSES: TaskStatus[] = ['READY', 'RUNNING', 'WAITING_DEPENDENCY', 'REVIEWING', 'RETRYING'];

/** 视为“需要人工关注”的状态。 */
export const PROBLEM_STATUSES: TaskStatus[] = ['FAILED', 'BLOCKED'];

const KNOWN = new Set<string>(ALL_STATUSES);

/** 后端可能新增状态值；未知值按 PENDING 处理，避免界面崩溃。 */
export function normalizeStatus(raw: unknown): TaskStatus {
  return typeof raw === 'string' && KNOWN.has(raw) ? (raw as TaskStatus) : 'PENDING';
}
