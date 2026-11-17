import { Handle, Position } from '@xyflow/react';
import type { TaskStatus } from '../types/task';

const statusColors: Record<TaskStatus, string> = {
  PENDING: '#9ca3af',   // 灰
  READY: '#3b82f6',     // 蓝
  RUNNING: '#f59e0b',   // 橙
  REVIEWING: '#8b5cf6', // 紫
  SUCCEEDED: '#22c55e', // 绿
  FAILED: '#ef4444',    // 红
};

export function TaskNode({ data }: { data: { task: { task_id: string; status: TaskStatus; assignee: string; attempt_count: number } } }) {
  const { task } = data;
  
  // 根据状态生成不同的样式
  const isRunning = task.status === 'RUNNING';
  const isReviewing = task.status === 'REVIEWING';
  const isFailed = task.status === 'FAILED';

  return (
    <div style={{
      width: 180, 
      minHeight: 60, 
      borderRadius: 8,
      border: `2px solid ${statusColors[task.status]}`,
      background: '#fff', 
      display: 'flex', 
      flexDirection: 'column',
      alignItems: 'center', 
      justifyContent: 'center', 
      padding: '8px',
      fontSize: 12,
      // RUNNING 状态加一个橙色发光效果
      boxShadow: isRunning ? `0 0 12px ${statusColors.RUNNING}` : 'none',
      // REVIEWING 状态加虚线边框提示“还没通过”
      borderStyle: isReviewing ? 'dashed' : 'solid',
    }}>
      <Handle type="target" position={Position.Left} />
      
      <strong>{task.task_id}</strong>
      <span style={{ color: '#666', marginTop: 2 }}>{task.assignee}</span>
      
      {/* 如果失败了，显示重试次数 */}
      {isFailed && task.attempt_count > 0 && (
        <span style={{ color: statusColors.FAILED, fontSize: 10, marginTop: 4 }}>
          ⚠️ Retry: {task.attempt_count}
        </span>
      )}

      <Handle type="source" position={Position.Right} />
    </div>
  );
}