import { describe, expect, it } from 'vitest';
import { mapSnapshotTask, statusFromEvents, type RunEvent } from './taskRunApi';

function event(type: string, taskId: string | null, sequence: number): RunEvent {
  return {
    event_id: `e-${sequence}`,
    sequence,
    type,
    task_id: taskId,
    plan_version: 'P1',
    input_snapshot: 'snap-1',
    occurred_at: '2026-11-20T10:00:00+08:00',
  };
}

describe('mapSnapshotTask', () => {
  it('把后端快照字段映射为界面 Task，并保留版本与尝试信息', () => {
    const task = mapSnapshotTask(
      {
        task_id: 'T-01',
        goal: '实现接口',
        state: 'REVIEWING',
        role_id: 'BE-01',
        block_id: 'B04',
        depends_on: ['T-00'],
        input_snapshot: 'snap-9',
        artifacts: [{ path: 'backend/handler.py', sha256: 'abcdef123456', kind: 'source' }],
        attempts: [{ attempt_id: 2, retry_count: 1, state: 'SUCCEEDED', started_at: 't1', finished_at: 't2' }],
        review: { decision: 'changes_requested', findings: [{ code: 'F-1', severity: 'blocking', message: '缺少测试' }] },
        duration_seconds: 1.25,
      },
      'real',
    );

    expect(task.status).toBe('REVIEWING');
    expect(task.assignee).toBe('BE-01');
    expect(task.depends_on).toEqual(['T-00']);
    expect(task.input_snapshot).toBe('snap-9');
    expect(task.outputs[0].version).toBe('abcdef12');
    expect(task.attempts[0].result).toBe('success');
    expect(task.review?.decision).toBe('changes_requested');
    expect(task.objections).toHaveLength(1);
    expect(task.objections[0].reason).toContain('缺少测试');
    expect(task.duration_seconds).toBe(1.25);
    expect(task.source).toBe('real');
  });

  it('未知状态归一化为 PENDING，避免界面崩溃', () => {
    expect(mapSnapshotTask({ task_id: 'T', state: 'SOMETHING_NEW' }).status).toBe('PENDING');
  });
});

describe('statusFromEvents', () => {
  it('按事件顺序覆盖任务状态，未知事件不改变结果', () => {
    const states = statusFromEvents([
      event('TASK_READY', 'T-1', 1),
      event('TASK_STARTED', 'T-1', 2),
      event('TASK_ACCEPTED', 'T-1', 3),
      event('TASK_RETRY_SCHEDULED', 'T-2', 4),
      event('SOMETHING_ELSE', 'T-2', 5),
    ]);
    expect(states['T-1']).toBe('SUCCEEDED');
    expect(states['T-2']).toBe('RETRYING');
  });
});
