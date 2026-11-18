import type { TaskStatus } from '../types/task';

/** 状态配色与文案（供节点、图例、详情面板共用） */
export const statusColors: Record<TaskStatus, string> = {
  PENDING: '#94a3b8',
  READY: '#3b82f6',
  RUNNING: '#f59e0b',
  REVIEWING: '#8b5cf6',
  SUCCEEDED: '#22c55e',
  FAILED: '#ef4444',
  BLOCKED: '#64748b',
};

export const statusLabels: Record<TaskStatus, string> = {
  PENDING: '等待中',
  READY: '就绪',
  RUNNING: '执行中',
  REVIEWING: '验收中',
  SUCCEEDED: '已通过',
  FAILED: '失败',
  BLOCKED: '已阻塞',
};

export const ALL_STATUSES: TaskStatus[] = [
  'PENDING', 'READY', 'RUNNING', 'REVIEWING', 'SUCCEEDED', 'FAILED', 'BLOCKED',
];
