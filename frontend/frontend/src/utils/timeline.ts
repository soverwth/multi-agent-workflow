/**
 * B05 时间视图的本地推导逻辑（纯函数，便于单测）。
 *
 * 后端只提供每个任务的 started_at / finished_at / duration_seconds 与依赖边，
 * 这里在前端做两件展示层的事情：
 * 1. 把任务投影到统一时间轴（有真实时间戳用绝对时间，没有则按依赖顺序估算）；
 * 2. 按「依赖链上耗时之和」估算关键路径，用于给时间条加标记。
 * 不写回后端，不改变任何任务状态。
 */

import type { Task } from '../types/task';

export interface TimelineRow {
  task: Task;
  /** 相对时间轴起点，毫秒 */
  start: number;
  /** 相对时间轴起点，毫秒 */
  end: number;
  /** 是否基于真实时间戳（false 表示按依赖顺序估算） */
  timed: boolean;
  critical: boolean;
}

export interface TimelineTick {
  at: number;
  label: string;
}

export interface TimelineModel {
  rows: TimelineRow[];
  domainStart: number;
  domainEnd: number;
  ticks: TimelineTick[];
  criticalPath: string[];
  /** 至少有一个任务带真实开始时间戳 */
  hasRealTime: boolean;
}

/** 任务耗时（毫秒）。优先级：真实起止时间 > duration_seconds > 展示用的最小值。 */
export function taskDurationMs(task: Task): number {
  const fromTimestamps = parseTime(task.finished_at) - parseTime(task.started_at);
  if (Number.isFinite(fromTimestamps) && fromTimestamps > 0) return fromTimestamps;
  if (typeof task.duration_seconds === 'number' && Number.isFinite(task.duration_seconds) && task.duration_seconds > 0) {
    return task.duration_seconds * 1000;
  }
  return 1000;
}

function parseTime(value?: string | null): number {
  if (!value) return Number.NaN;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : Number.NaN;
}

/** 只保留依赖图中存在的上游，避免脏数据导致递归异常。 */
function dependencies(task: Task, byId: Map<string, Task>): string[] {
  return (task.depends_on ?? []).filter((id) => id !== task.task_id && byId.has(id));
}

/**
 * 关键路径 = 依赖链上累计耗时最长的一条路径。
 * 采用记忆化 DFS，并对环做保护（异常数据不会导致死循环）。
 */
export function computeCriticalPath(tasks: Task[]): string[] {
  const byId = new Map(tasks.map((task) => [task.task_id, task]));
  const memo = new Map<string, { length: number; path: string[] }>();
  const visiting = new Set<string>();

  const solve = (id: string): { length: number; path: string[] } => {
    const cached = memo.get(id);
    if (cached) return cached;
    if (visiting.has(id)) return { length: 0, path: [] };
    visiting.add(id);
    const task = byId.get(id);
    if (!task) {
      visiting.delete(id);
      return { length: 0, path: [] };
    }
    const self = taskDurationMs(task);
    let best: { length: number; path: string[] } = { length: self, path: [id] };
    for (const dep of dependencies(task, byId)) {
      const upstream = solve(dep);
      const candidate = { length: upstream.length + self, path: [...upstream.path, id] };
      if (candidate.length > best.length) best = candidate;
    }
    visiting.delete(id);
    memo.set(id, best);
    return best;
  };

  let winner: { length: number; path: string[] } = { length: -1, path: [] };
  for (const task of tasks) {
    const result = solve(task.task_id);
    if (result.length > winner.length) winner = result;
  }
  return winner.path;
}

/** 按依赖关系估算最早开始时间（无真实时间戳时使用）。 */
function earliestStarts(tasks: Task[]): Map<string, number> {
  const byId = new Map(tasks.map((task) => [task.task_id, task]));
  const memo = new Map<string, number>();
  const visiting = new Set<string>();

  const solve = (id: string): number => {
    const cached = memo.get(id);
    if (cached !== undefined) return cached;
    if (visiting.has(id)) return 0;
    visiting.add(id);
    const task = byId.get(id);
    if (!task) {
      visiting.delete(id);
      return 0;
    }
    const upstreamEnd = dependencies(task, byId).reduce((max, dep) => {
      const upstream = byId.get(dep);
      return upstream ? Math.max(max, solve(dep) + taskDurationMs(upstream)) : max;
    }, 0);
    visiting.delete(id);
    memo.set(id, upstreamEnd);
    return upstreamEnd;
  };

  for (const task of tasks) solve(task.task_id);
  return memo;
}

function formatTick(at: number, domainStart: number, hasRealTime: boolean): string {
  if (hasRealTime) {
    const date = new Date(domainStart + at);
    if (!Number.isNaN(date.getTime())) {
      return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
    }
  }
  const seconds = at / 1000;
  return seconds >= 60 ? `${(seconds / 60).toFixed(1)}min` : `${seconds.toFixed(0)}s`;
}

export function buildTimeline(tasks: Task[]): TimelineModel {
  const criticalPath = computeCriticalPath(tasks);
  const critical = new Set(criticalPath);
  const starts = new Map<string, number>();
  for (const task of tasks) {
    const start = parseTime(task.started_at);
    if (Number.isFinite(start)) starts.set(task.task_id, start);
  }
  const hasRealTime = starts.size > 0;

  const rows: TimelineRow[] = [];
  if (hasRealTime) {
    const domainStart = Math.min(...starts.values());
    const estimated = earliestStarts(tasks);
    for (const task of tasks) {
      const duration = taskDurationMs(task);
      const realStart = starts.get(task.task_id);
      const finish = parseTime(task.finished_at);
      const start = realStart !== undefined ? realStart - domainStart : estimated.get(task.task_id) ?? 0;
      const end = realStart !== undefined && Number.isFinite(finish) && finish >= realStart
        ? finish - domainStart
        : start + duration;
      rows.push({ task, start, end: Math.max(end, start + 1), timed: realStart !== undefined, critical: critical.has(task.task_id) });
    }
  } else {
    const estimated = earliestStarts(tasks);
    for (const task of tasks) {
      const start = estimated.get(task.task_id) ?? 0;
      const duration = taskDurationMs(task);
      rows.push({ task, start, end: start + duration, timed: false, critical: critical.has(task.task_id) });
    }
  }

  const domainEnd = rows.reduce((max, row) => Math.max(max, row.end), 0);
  const domainStart = hasRealTime ? Math.min(...starts.values()) : 0;
  const ticks = Array.from({ length: 6 }, (_, index) => {
    const at = (domainEnd * index) / 5;
    return { at, label: formatTick(at, domainStart, hasRealTime) };
  });

  return { rows, domainStart, domainEnd, ticks, criticalPath, hasRealTime };
}
