import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  mapSnapshotTask,
  replayTaskRun,
  restoreTaskRun,
  statusFromEvents,
  type RunEvent,
} from './taskRunApi';

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

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown) {
  return { ok: true, json: async () => body, status: 200, statusText: 'OK' };
}

/**
 * 回归：B02 的 replay/restore 响应带一层包装（`{replay: {...}}` / `{restore: {...}}`）。
 * 早期实现直接读顶层 `consistent`，导致回放校验永远显示“发现 0 处不一致”之外的失败态。
 */
describe('replay/restore 解包 B02 的响应包装', () => {
  it('replayTaskRun 读取 replay 包装体里的判定结果', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      replay: {
        run_id: 'TASK-RUN-1',
        consistent: true,
        mismatches: [],
        event_count: 42,
        last_sequence: 42,
      },
    }));
    vi.stubGlobal('fetch', fetchMock);

    const result = await replayTaskRun({ baseUrl: 'http://127.0.0.1:7100', runId: 'TASK-RUN-1' });

    expect(result.consistent).toBe(true);
    expect(result.event_count).toBe(42);
    expect(fetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:7100/api/task-runs/TASK-RUN-1/replay',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('restoreTaskRun 读取 restore 包装体', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      restore: { run_id: 'TASK-RUN-1', completed: 8, pending: [] },
    }));
    vi.stubGlobal('fetch', fetchMock);

    const result = await restoreTaskRun({ baseUrl: 'http://127.0.0.1:7100/', runId: 'TASK-RUN-1' });

    expect(result.completed).toBe(8);
    expect(fetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:7100/api/task-runs/TASK-RUN-1/restore',
      expect.anything(),
    );
  });
});
