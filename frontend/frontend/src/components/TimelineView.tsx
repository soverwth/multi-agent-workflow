/**
 * B05 时间线视图：把任务投影到时间轴，和 DAG 共用选中任务。
 *
 * 数据全部来自快照已有字段（started_at / finished_at / duration_seconds / depends_on）；
 * 关键路径是展示层估算，不读取后端「critical」字段，也不修改任何状态。
 */

import { useMemo } from 'react';
import { statusColors, statusLabels } from '../constants/status';
import type { Task } from '../types/task';
import { buildTimeline, taskDurationMs } from '../utils/timeline';

interface Props {
  tasks: Task[];
  selectedId?: string | null;
  onSelect?: (task: Task) => void;
}

export function TimelineView({ tasks, selectedId, onSelect }: Props) {
  const model = useMemo(() => buildTimeline(tasks), [tasks]);

  if (!tasks.length) {
    return <div className="canvas-empty">暂无任务，无法生成时间线。</div>;
  }

  const span = Math.max(model.domainEnd, 1);

  return (
    <div className="timeline">
      <div className="timeline-summary">
        <div>
          <strong>任务排期视图</strong>
          <span>
            {model.hasRealTime
              ? '基于真实 start/finish 时间戳；无时间戳的任务按依赖顺序估算放置'
              : '快照无真实时间戳，按依赖链与耗时估算相对排期'}
          </span>
        </div>
        <div className="timeline-critical">
          <span className="critical-dot" />
          关键路径（按耗时估算）：{model.criticalPath.length ? model.criticalPath.join(' → ') : '—'}
        </div>
      </div>

      <div className="timeline-scroll">
        <div className="timeline-grid">
          <div className="timeline-axis">
            <div className="timeline-axis-label" />
            <div className="timeline-axis-track">
              {model.ticks.map((tick) => (
                <span key={tick.at} className="timeline-tick" style={{ left: `${(tick.at / span) * 100}%` }}>
                  {tick.label}
                </span>
              ))}
            </div>
          </div>

          {model.rows.map((row) => {
            const width = Math.max(((row.end - row.start) / span) * 100, 1.2);
            const isSelected = row.task.task_id === selectedId;
            return (
              <button
                type="button"
                key={row.task.task_id}
                className={`timeline-row${isSelected ? ' selected' : ''}`}
                onClick={() => onSelect?.(row.task)}
                title={`${row.task.task_id} · ${statusLabels[row.task.status]} · ${(taskDurationMs(row.task) / 1000).toFixed(2)}s${row.timed ? '' : '（估算位置）'}`}
              >
                <span className="timeline-row-label">
                  <b>{row.task.task_id}</b>
                  <small>{row.task.block_id ?? row.task.assignee ?? '—'}</small>
                </span>
                <span className="timeline-track">
                  <span className="timeline-gridlines" aria-hidden="true">
                    {model.ticks.slice(1).map((tick) => (
                      <i key={tick.at} style={{ left: `${(tick.at / span) * 100}%` }} />
                    ))}
                  </span>
                  <span
                    className={`timeline-bar${row.critical ? ' critical' : ''}`}
                    style={{
                      left: `${(row.start / span) * 100}%`,
                      width: `${width}%`,
                      background: statusColors[row.task.status] ?? '#94a3b8',
                    }}
                  >
                    <span>{statusLabels[row.task.status]}</span>
                  </span>
                </span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="timeline-foot">
        {ALL_LEGEND.map((status) => (
          <span key={status} className="legend-item">
            <i style={{ background: statusColors[status] }} />
            {statusLabels[status]}
          </span>
        ))}
        <span className="timeline-foot-note">点击任意行可在右侧查看详情（与 DAG 联动）</span>
      </div>
    </div>
  );
}

const ALL_LEGEND = Object.keys(statusLabels) as (keyof typeof statusLabels)[];
