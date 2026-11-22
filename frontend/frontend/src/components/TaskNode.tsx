import { Handle, Position } from '@xyflow/react';
import { statusColors, statusLabels } from '../constants/status';
import type { TaskStatus } from '../types/task';

export interface TaskNodeData extends Record<string, unknown> {
  task: {
    task_id: string;
    status: TaskStatus;
    assignee: string;
    attempt_id: number;
    retry_count: number;
    input_snapshot?: string;
    goal?: string;
    block_id?: string;
    priority?: string;
    duration_seconds?: number | null;
    blocked_reason?: string | null;
  };
}

const BLOCK_LABELS: Record<string, string> = {
  B01: 'B01 计划',
  B02: 'B02 编排',
  B03: 'B03 黑板',
  B04: 'B04 执行',
  B05: 'B05 展示',
  B06: 'B06 质量',
};

function formatDuration(seconds: number | null | undefined): string | null {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds < 0) return null;
  if (seconds < 1) return `${Math.round(seconds * 1000)}ms`;
  return `${seconds.toFixed(1)}s`;
}

export function TaskNode({ data, selected }: { data: TaskNodeData; selected?: boolean }) {
  const { task } = data;
  const color = statusColors[task.status] || '#94a3b8';
  const isRunning = task.status === 'RUNNING';
  const isReviewing = task.status === 'REVIEWING';
  const isRetrying = task.status === 'RETRYING';
  const isFailed = task.status === 'FAILED' || task.status === 'BLOCKED';
  const hasRetried = task.retry_count > 0;
  const duration = formatDuration(task.duration_seconds);
  const blockLabel = task.block_id ? BLOCK_LABELS[task.block_id] || task.block_id : null;

  return (
    <div
      title={[task.goal, task.blocked_reason].filter(Boolean).join('\n')}
      style={{
        width: 208,
        minHeight: 82,
        borderRadius: 10,
        border: `2px solid ${color}`,
        background: '#fff',
        display: 'flex',
        flexDirection: 'column',
        padding: '10px 12px',
        fontSize: 12,
        boxShadow: selected
          ? `0 0 0 3px ${color}33, 0 6px 16px rgba(0,0,0,.12)`
          : isRunning
            ? `0 0 14px ${color}88`
            : '0 2px 6px rgba(0,0,0,.06)',
        borderStyle: isReviewing || isRetrying ? 'dashed' : 'solid',
        opacity: task.status === 'PENDING' ? 0.75 : 1,
        transition: 'box-shadow .2s, opacity .2s',
      }}
    >
      <Handle type="target" position={Position.Left} style={{ background: color }} />

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 6 }}>
        <strong style={{ fontSize: 15, color: '#0f172a' }}>{task.task_id}</strong>
        <span style={{ fontSize: 11, color: '#fff', background: color, borderRadius: 10, padding: '1px 7px' }}>
          {statusLabels[task.status]}
        </span>
      </div>

      {/* 负责 Block + 执行角色（D24：展示负责 Block） */}
      <span style={{ color: '#475569', marginTop: 3, fontSize: 11 }}>
        {blockLabel ? `${blockLabel} · ` : ''}
        {task.assignee}
      </span>

      {/* 可追踪：当前尝试 + 重试次数 + 耗时 + 输入版本 */}
      <div style={{ display: 'flex', gap: 8, marginTop: 6, fontSize: 10, color: '#64748b', flexWrap: 'wrap' }}>
        <span title="派发编号 attempt_id">#{task.attempt_id || 0}</span>
        {hasRetried && (
          <span title="失败重派次数 retry_count" style={{ color: '#dc2626', fontWeight: 600 }}>
            retry {task.retry_count}
          </span>
        )}
        {duration && <span title="耗时">{duration}</span>}
        {task.priority && <span title="优先级">{task.priority}</span>}
        {task.input_snapshot && (
          <span title="输入快照版本" style={{ marginLeft: 'auto', fontFamily: 'monospace' }}>
            {task.input_snapshot.slice(0, 7)}
          </span>
        )}
      </div>

      {isFailed && (
        <span style={{ color: '#dc2626', fontSize: 10, marginTop: 4 }}>
          {task.status === 'BLOCKED'
            ? `⛔ ${task.blocked_reason || '上游失效，暂停放行'}`
            : '⚠ 需返修'}
        </span>
      )}

      <Handle type="source" position={Position.Right} style={{ background: color }} />
    </div>
  );
}
