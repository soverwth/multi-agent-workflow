import { statusColors, statusLabels } from '../constants/status';
import type { Task } from '../types/task';

/**
 * 甘特排期视图：按依赖层级估算开始位置与时长。
 *
 * 类名统一使用 `gantt-` 前缀，避免与 `TimelineView` 的 `.timeline-*` 冲突
 * （两套视图共用同一个任务数组，但排期语义不同）。
 */

interface Props {
  tasks: Task[];
  selectedId?: string | null;
  onTaskClick?: (task: Task) => void;
}

function depthOf(task: Task, byId: Map<string, Task>, visiting = new Set<string>()): number {
  if (!task.depends_on.length) return 0;
  if (visiting.has(task.task_id)) return 0;
  const next = new Set(visiting).add(task.task_id);
  return Math.max(...task.depends_on.map((id) => {
    const parent = byId.get(id);
    return parent ? depthOf(parent, byId, next) + 1 : 0;
  }));
}

export function TaskTimeline({ tasks, selectedId, onTaskClick }: Props) {
  const byId = new Map(tasks.map((task) => [task.task_id, task]));
  const rows = tasks
    .map((task) => ({ task, depth: depthOf(task, byId) }))
    .sort((left, right) => left.depth - right.depth || left.task.task_id.localeCompare(right.task.task_id));
  const maxDepth = Math.max(1, ...rows.map((row) => row.depth));

  return (
    <div className="gantt-wrap" aria-label="任务甘特排期">
      <div className="gantt-header">
        <span>任务与依赖</span>
        <div className="gantt-scale">
          {Array.from({ length: maxDepth + 2 }, (_, index) => <span key={index}>{index * 10}m</span>)}
        </div>
      </div>
      <div className="gantt-rows">
        {rows.map(({ task, depth }) => {
          const duration = Math.max(4, Math.min(30, Math.round(task.duration_seconds ?? 8)));
          const start = depth * 10;
          const selected = task.task_id === selectedId;
          return (
            <button
              type="button"
              className={`gantt-row ${selected ? 'selected' : ''}`}
              key={task.task_id}
              onClick={() => onTaskClick?.(task)}
              title={`${task.task_id} · ${statusLabels[task.status]}`}
            >
              <span className="gantt-label">
                <strong>{task.task_id} · {task.goal}</strong>
                <small>{task.depends_on.length ? `前置 ${task.depends_on.join(', ')}` : '无前置任务'}</small>
              </span>
              <span className="gantt-track">
                <span
                  className="gantt-bar"
                  style={{ left: `${start * 2.2}%`, width: `${Math.max(7, duration * 1.7)}%`, background: statusColors[task.status] }}
                >
                  {duration}m
                </span>
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
