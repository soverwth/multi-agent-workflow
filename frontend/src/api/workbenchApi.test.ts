import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  createDiscussionRun,
  getDesignSpec,
  getDiscussionRun,
  listDiscussionRuns,
  listTaskRuns,
} from './workbenchApi';

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, ok = true) {
  return {
    ok,
    json: async () => body,
    status: ok ? 200 : 400,
    statusText: ok ? 'OK' : 'Bad Request',
  };
}

describe('workbenchApi 真实接口适配', () => {
  it('读取讨论运行列表并去掉地址尾部斜杠', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ runs: [{ run_id: 'RUN-1', idea: '报名工具', stage: 'INTAKE', status: 'READY' }] }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const data = await listDiscussionRuns('http://127.0.0.1:7100/');

    expect(fetchMock).toHaveBeenCalledWith('http://127.0.0.1:7100/api/runs', expect.anything());
    expect(data.runs[0].run_id).toBe('RUN-1');
  });

  it('提交项目想法走 POST /api/runs 并携带完整字段', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ run: { run_id: 'RUN-2', idea: '活动签到', stage: 'INTAKE', status: 'READY' } }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const data = await createDiscussionRun('http://127.0.0.1:7100', {
      idea: '活动签到',
      constraints: '不接入支付',
      scenario: 'normal',
      max_rounds: 2,
    });

    expect(fetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:7100/api/runs',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          idea: '活动签到',
          constraints: '不接入支付',
          scenario: 'normal',
          max_rounds: 2,
        }),
      }),
    );
    expect(data.run.run_id).toBe('RUN-2');
  });

  it('读取讨论详情与设计规格时转义运行编号', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ run: { run_id: 'RUN/3', idea: 'x', stage: 'INTAKE', status: 'READY' } }))
      .mockResolvedValueOnce(jsonResponse({ design_spec: { project_id: 'demo' }, source_run_id: 'RUN/3' }));
    vi.stubGlobal('fetch', fetchMock);

    await getDiscussionRun('http://127.0.0.1:7100', 'RUN/3');
    const spec = await getDesignSpec('http://127.0.0.1:7100', 'RUN/3');

    expect(fetchMock).toHaveBeenNthCalledWith(1, 'http://127.0.0.1:7100/api/runs/RUN%2F3', expect.anything());
    expect(fetchMock).toHaveBeenNthCalledWith(2, 'http://127.0.0.1:7100/api/runs/RUN%2F3/design-spec', expect.anything());
    expect(spec.design_spec).toEqual({ project_id: 'demo' });
  });

  it('读取任务运行列表，并在接口报错时抛出后端错误信息', async () => {
    const okFetch = vi.fn().mockResolvedValue(jsonResponse({ runs: [{ run_id: 'TASK-RUN-1' }] }));
    vi.stubGlobal('fetch', okFetch);
    const data = await listTaskRuns('http://127.0.0.1:7100');
    expect(data.runs[0].run_id).toBe('TASK-RUN-1');

    const failFetch = vi.fn().mockResolvedValue(jsonResponse({ error: '运行不存在' }, false));
    vi.stubGlobal('fetch', failFetch);
    await expect(listTaskRuns('http://127.0.0.1:7100')).rejects.toThrow('运行不存在');
  });
});
