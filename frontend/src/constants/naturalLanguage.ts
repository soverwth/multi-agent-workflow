/**
 * B05 面向普通用户的自然语言展示（需求文档第 9 条）
 *
 * 只负责把后端状态翻译成人话，不参与任何业务判定。
 */

import type { TaskStatus } from '../types/task';

/** 九态的任务进度说明：比状态枚举更容易理解。 */
export const statusNarrative: Record<TaskStatus, string> = {
  PENDING: '任务已记录，正在等待依赖检查',
  READY: '前置工作已完成，准备交给 Agent 执行',
  RUNNING: 'Agent 正在执行这个任务',
  WAITING_DEPENDENCY: '还在等前面的任务完成，暂时不能开始',
  REVIEWING: '成果已提交，正在等待质量验收',
  SUCCEEDED: '任务已通过验收，成果可用',
  FAILED: '这次没有通过，且已用完重试机会',
  RETRYING: '这次没通过，系统正在按规则重试',
  BLOCKED: '上游任务出了问题，这个任务被暂停放行',
};

export function narrativeForStatus(value: string): string {
  return statusNarrative[value as TaskStatus] ?? `状态：${value}`;
}

/** 讨论阶段（A—H）的自然语言说明。 */
export const discussionStageNarrative: Record<string, string> = {
  INTAKE: '正在整理你的想法与边界条件',
  DIVERGE: '各角色正在独立提出观点，彼此看不到对方',
  CLUSTER: '正在把相近的观点归为一类',
  CRITIQUE: '角色之间正在互相质疑、验证观点',
  EVALUATE: '正在评估分歧，有分歧则 agent 自动辩论',
  PROPOSAL_REVIEW: '正在审阅方案，收集 agent 角色签核',
  HUMAN_CONFIRMATION: 'agent 角色正在互相确认需求（无人工审批）',
  DESIGN_SPEC: '正在细化接口、错误码、字段边界与数据模型',
  COMPLETED: '需求已由 agent 共识确认，可以进入开发阶段',
  STOPPED: '达到控制预算，流程已诚实停止（不代表达成共识）',
};

export function narrativeForDiscussionStage(stage: string): string {
  return discussionStageNarrative[stage] ?? `当前阶段：${stage}`;
}

/** 讨论运行控制状态的自然语言说明。 */
export const discussionStatusNarrative: Record<string, string> = {
  READY: '可以推进到下一步',
  RUNNING: '正在推进中',
  WAITING_HUMAN: '停在 agent 共识确认点（无人工审批，可继续推进）',
  PAUSED: '已暂停，恢复前不会派发新任务',
  STOPPED: '已停止，没有生成需求结论',
  BLOCKED: '执行失败，流程被阻断',
  COMPLETED: '讨论已完成',
};

export function narrativeForDiscussionStatus(status: string): string {
  return discussionStatusNarrative[status] ?? `状态：${status}`;
}

/** 编排事件类型的自然语言说明（用于 Agent 执行中心与活动日志）。 */
const eventNarrative: Record<string, string> = {
  RUN_CREATED: '任务运行已创建',
  PLAN_LOADED: '任务计划已载入',
  TASK_READY: '任务已就绪，等待派发',
  TASK_DISPATCHED: '任务已派发给 Agent',
  TASK_STARTED: 'Agent 已开始执行任务',
  TASK_OUTPUT_SUBMITTED: 'Agent 已提交候选成果',
  TASK_REVIEW_REQUESTED: '已请求质量验收',
  TASK_ACCEPTED: '成果通过质量验收',
  TASK_COMPLETED: '任务完成',
  TASK_REJECTED: '成果未通过质量验收',
  TASK_RETRY_SCHEDULED: '系统已安排重试',
  TASK_FAILED: '任务执行失败',
  TASK_BLOCKED: '任务因上游问题被阻断',
  RUN_COMPLETED: '整个运行已完成',
};

export function narrativeForEvent(type: string): string {
  return eventNarrative[type] ?? type;
}

/** 把秒数格式化成用户能读懂的耗时。 */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return '—';
  if (seconds < 60) return `${Math.round(seconds)} 秒`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  if (minutes < 60) return rest ? `${minutes} 分 ${rest} 秒` : `${minutes} 分钟`;
  const hours = Math.floor(minutes / 60);
  return `${hours} 小时 ${minutes % 60} 分`;
}

/** 把完成度格式化成「已完成 / 总数」与百分比。 */
export function progressPercent(completed: number | undefined, total: number | undefined): number {
  if (!total || total <= 0) return 0;
  return Math.min(100, Math.max(0, Math.round(((completed ?? 0) / total) * 100)));
}
