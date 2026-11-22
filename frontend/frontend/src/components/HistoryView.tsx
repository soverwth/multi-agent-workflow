/**
 * B05 历史项目页（需求文档第 8 条、验收第 5 条）
 *
 * 读取 /api/runs 与 /api/task-runs，展示历史需求讨论与任务运行记录；
 * 点击可回到对应页面查看完整需求、任务与执行结果。
 */

import { useCallback, useEffect, useState } from 'react';
import {
  listDiscussionRuns,
  listTaskRuns,
  type DiscussionRun,
  type TaskRunSummary,
} from '../api/workbenchApi';
import {
  narrativeForDiscussionStage,
  narrativeForDiscussionStatus,
  narrativeForStatus,
} from '../constants/naturalLanguage';
import type { DataSource } from '../types/task';

interface Props {
  apiBase: string;
  source: DataSource;
  onOpenDiscussion: (runId: string) => void;
  onOpenRun: (runId: string) => void;
}

export function HistoryView({ apiBase, source, onOpenDiscussion, onOpenRun }: Props) {
  const isReal = source === 'real';
  const [discussions, setDiscussions] = useState<DiscussionRun[]>([]);
  const [runs, setRuns] = useState<TaskRunSummary[]>([]);
  const [error, setError] = useState('');

  const load = useCallback(async (signal?: AbortSignal) => {
    const [discussionData, taskData] = await Promise.all([
      listDiscussionRuns(apiBase, signal),
      listTaskRuns(apiBase, signal),
    ]);
    return { discussions: discussionData.runs ?? [], runs: taskData.runs ?? [] };
  }, [apiBase]);

  useEffect(() => {
    if (!isReal) return undefined;
    const controller = new AbortController();
    let active = true;
    void load(controller.signal)
      .then((data) => {
        if (!active) return;
        setDiscussions(data.discussions);
        setRuns(data.runs);
        setError('');
      })
      .catch((caught: unknown) => {
        if (active && !controller.signal.aborted) {
          setError(caught instanceof Error ? caught.message : String(caught));
        }
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [isReal, load]);

  return (
    <div className="stage-panel">
      <div className="stage-panel-head">
        <h2>07 · 历史项目</h2>
        <p>查看平台里已经发生过的需求讨论和任务运行。记录由 B03 持久化，前端只读取和展示。</p>
      </div>

      <div className={`source-note ${isReal ? 'real' : 'sim'}`}>
        {isReal
          ? '真实数据：来自 B02 /api/runs 与 /api/task-runs 的持久化记录。'
          : '演示数据：历史记录保存在后端数据库中，请切换到「真实接口」查看。'}
      </div>

      {error && <div className="alert error" role="alert">读取历史记录失败：{error}</div>}

      {!isReal ? (
        <div className="stage-card">
          <h3>为什么这里没有列表</h3>
          <p>本地快照只有若干任务运行结果，没有完整的历史项目记录。切换到「真实接口」即可看到后端持久化的全部历史。</p>
        </div>
      ) : (
        <>
          <section className="requirement-section">
            <h3>历史需求讨论（{discussions.length}）</h3>
            {discussions.length === 0 ? (
              <p className="empty-state">暂无历史讨论</p>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr><th>运行编号</th><th>项目想法</th><th>阶段 / 状态</th><th>轮次</th><th>更新时间</th><th>操作</th></tr>
                  </thead>
                  <tbody>
                    {discussions.map((run) => (
                      <tr key={run.run_id}>
                        <td><span className="id-text">{run.run_id}</span></td>
                        <td>{run.idea}</td>
                        <td>{narrativeForDiscussionStage(run.stage)} · {narrativeForDiscussionStatus(run.status)}</td>
                        <td>{run.round ?? 0} / {run.max_rounds ?? '—'}</td>
                        <td>{run.updated_at ?? '—'}</td>
                        <td><button type="button" className="text-link" onClick={() => onOpenDiscussion(run.run_id)}>查看需求与方案</button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="requirement-section">
            <h3>历史任务运行（{runs.length}）</h3>
            {runs.length === 0 ? (
              <p className="empty-state">暂无任务运行</p>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr><th>运行编号</th><th>项目 / 计划</th><th>状态</th><th>版本</th><th>创建时间</th><th>操作</th></tr>
                  </thead>
                  <tbody>
                    {runs.map((run) => (
                      <tr key={run.run_id}>
                        <td><span className="id-text">{run.run_id}</span></td>
                        <td>{run.project_id ?? '—'} / {run.plan_id ?? '—'}</td>
                        <td>{narrativeForStatus(run.status ?? 'PENDING')}</td>
                        <td>{run.plan_version ?? '—'}</td>
                        <td>{run.created_at ?? '—'}</td>
                        <td><button type="button" className="text-link" onClick={() => onOpenRun(run.run_id)}>查看执行结果</button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
