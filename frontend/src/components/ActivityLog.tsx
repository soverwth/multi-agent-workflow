/**
 * B05 活动日志：把事件流按时间倒序展示，作为 DAG / 时间线之外的第三种观察视角。
 * 事件来自快照与 /events 增量游标，界面只做展示，不改写任何状态。
 */

import { useMemo } from 'react';

export interface ActivityEvent {
  sequence: number;
  type: string;
  task_id?: string | null;
  attempt_id?: number | null;
  occurred_at: string;
}

interface Props {
  events: ActivityEvent[];
  cursor?: number;
  max?: number;
}

function levelOf(type: string): 'success' | 'error' | 'warn' | 'info' {
  if (/FAILED|BLOCKED|REJECTED/.test(type)) return 'error';
  if (/ACCEPTED|COMPLETED|SUCCEEDED/.test(type)) return 'success';
  if (/RETRY|REVALID/.test(type)) return 'warn';
  return 'info';
}

function shortTime(value: string): string {
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) return value.slice(11, 19) || value;
  const date = new Date(parsed);
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}:${String(date.getSeconds()).padStart(2, '0')}`;
}

export function ActivityLog({ events, cursor = 0, max = 160 }: Props) {
  const rows = useMemo(
    () => [...events].sort((a, b) => b.sequence - a.sequence).slice(0, max),
    [events, max],
  );

  if (!rows.length) {
    return <div className="activity-empty">暂无事件。点击「推进一步」或「运行至完成」后这里会出现状态迁移记录。</div>;
  }

  return (
    <div className="activity">
      <div className="activity-head">
        <strong>事件流</strong>
        <span>
          共 {events.length} 条 · 已同步至序号 #{cursor || events[events.length - 1]?.sequence || 0} · 倒序显示最近 {rows.length} 条
        </span>
      </div>
      <ol className="activity-list">
        {rows.map((event) => (
          <li key={`${event.sequence}-${event.type}`} className={`activity-item ${levelOf(event.type)}`}>
            <span className="activity-seq">#{event.sequence}</span>
            <span className="activity-time">{shortTime(event.occurred_at)}</span>
            <span className="activity-type">{event.type}</span>
            {event.task_id ? <span className="activity-task">{event.task_id}</span> : null}
            {typeof event.attempt_id === 'number' ? <span className="activity-attempt">尝试 #{event.attempt_id}</span> : null}
          </li>
        ))}
      </ol>
    </div>
  );
}
