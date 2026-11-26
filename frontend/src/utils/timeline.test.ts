import { describe, expect, it } from 'vitest';
import type { Task } from '../types/task';
import { buildTimeline, computeCriticalPath, taskDurationMs } from './timeline';

function makeTask(
  taskId: string,
  dependsOn: string[],
  durationSeconds: number,
  startedAt: string | null = null,
  finishedAt: string | null = null,
): Task {
  return {
    task_id: taskId,
    goal: taskId,
    depends_on: dependsOn,
    status: 'SUCCEEDED',
    assignee: 'B04',
    spec_version: 'S1',
    contract_version: 'C1',
    input_snapshot: 'snap-1',
    attempt_id: 1,
    retry_count: 0,
    write_scope: [],
    outputs: [],
    evidence: [],
    objections: [],
    attempts: [],
    duration_seconds: durationSeconds,
    started_at: startedAt,
    finished_at: finishedAt,
  };
}

describe('taskDurationMs', () => {
  it('优先使用真实起止时间', () => {
    const task = makeTask('T', [], 99, '2026-11-20T10:00:00+08:00', '2026-11-20T10:00:03+08:00');
    expect(taskDurationMs(task)).toBe(3000);
  });

  it('没有时间戳时退回 duration_seconds，再退回展示最小值', () => {
    expect(taskDurationMs(makeTask('T', [], 2.5))).toBe(2500);
    expect(taskDurationMs(makeTask('T', [], null as unknown as number))).toBe(1000);
  });
});

describe('computeCriticalPath', () => {
  it('线性依赖返回整条链', () => {
    const tasks = [
      makeTask('A', [], 2),
      makeTask('B', ['A'], 3),
      makeTask('C', ['B'], 1),
    ];
    expect(computeCriticalPath(tasks)).toEqual(['A', 'B', 'C']);
  });

  it('分支中选择累计耗时最长的一条', () => {
    const tasks = [
      makeTask('A', [], 2),
      makeTask('B', ['A'], 1),
      makeTask('C', ['A'], 5),
      makeTask('D', ['B', 'C'], 1),
    ];
    expect(computeCriticalPath(tasks)).toEqual(['A', 'C', 'D']);
  });

  it('异常依赖环不会导致死循环', () => {
    const tasks = [makeTask('A', ['B'], 1), makeTask('B', ['A'], 1)];
    expect(computeCriticalPath(tasks).length).toBeGreaterThan(0);
  });
});

describe('buildTimeline', () => {
  it('无时间戳时按依赖估算相对排期并标记关键路径', () => {
    const tasks = [
      makeTask('A', [], 2),
      makeTask('B', ['A'], 1),
      makeTask('C', ['A'], 5),
      makeTask('D', ['B', 'C'], 1),
    ];
    const model = buildTimeline(tasks);
    expect(model.hasRealTime).toBe(false);
    expect(model.domainEnd).toBe(8000);
    expect(model.rows.find((row) => row.task.task_id === 'D')?.start).toBe(7000);
    expect(model.criticalPath).toEqual(['A', 'C', 'D']);
    expect(model.rows.filter((row) => row.critical).map((row) => row.task.task_id)).toEqual(['A', 'C', 'D']);
    expect(model.ticks).toHaveLength(6);
  });

  it('有时间戳时使用绝对起点并保留真实间隔', () => {
    const tasks = [
      makeTask('A', [], 2, '2026-11-20T10:00:00+08:00', '2026-11-20T10:00:02+08:00'),
      makeTask('B', ['A'], 3, '2026-11-20T10:00:03+08:00', '2026-11-20T10:00:06+08:00'),
    ];
    const model = buildTimeline(tasks);
    expect(model.hasRealTime).toBe(true);
    const rows = new Map(model.rows.map((row) => [row.task.task_id, row]));
    expect(rows.get('A')?.start).toBe(0);
    expect(rows.get('A')?.end).toBe(2000);
    expect(rows.get('B')?.start).toBe(3000);
    expect(rows.get('B')?.end).toBe(6000);
    expect(rows.get('B')?.timed).toBe(true);
  });
});
