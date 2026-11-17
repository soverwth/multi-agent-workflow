import { useState } from 'react';
import { TaskGraph } from './components/TaskGraph';
import { useTaskWebSocket } from './hooks/useTaskWebSocket';
import type { Task, TaskStatus } from './types/task';
import './App.css';

const statusColors: Record<TaskStatus, string> = {
  PENDING: '#9ca3af', READY: '#3b82f6', RUNNING: '#f59e0b',
  REVIEWING: '#8b5cf6', SUCCEEDED: '#22c55e', FAILED: '#ef4444',
};

function App() {
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);
  const tasks = useTaskWebSocket('ws://localhost:8000');

  return (
    <div style={{ display: 'flex', flexDirection: 'column', position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: '#f8fafc', fontFamily: 'system-ui, sans-serif' }}>
      {/* 顶部导航栏 */}
      <header style={{ background: '#fff', padding: '16px 24px', borderBottom: '1px solid #e2e8f0', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: '20px', color: '#1e293b' }}>多智能体协作开发平台 - 任务编排视图</h1>
          <span style={{ color: '#64748b', fontSize: '13px' }}>当前案例：校园失物招领系统 (R1/S1/C1 基线)</span>
        </div>
        <div>
          <span style={{ padding: '6px 12px', background: '#dcfce7', color: '#166534', borderRadius: '16px', fontSize: '13px', fontWeight: 'bold' }}>
            🟢 实时同步中
          </span>
        </div>
      </header>

      {/* 主体内容区 */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        
        {/* ================= 左侧画布区 ================= */}
        <div style={{ flex: 1, position: 'relative', display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          
          {/* 图例工具条 */}
          <div style={{ padding: '12px 24px', background: '#fff', borderBottom: '1px solid #e2e8f0', display: 'flex', gap: '16px', fontSize: '12px' }}>
            <strong>状态图例：</strong>
            {Object.entries(statusColors).map(([status, color]) => (
              <div key={status} style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                <span style={{ width: '12px', height: '12px', borderRadius: '50%', background: color }}></span>
                {status}
              </div>
            ))}
          </div>

          {/* 画布组件 */}
          <div style={{ flex: 1 }}>
            {tasks.length === 0 ? (
              <div style={{ display: 'flex', height: '100%', justifyContent: 'center', alignItems: 'center', color: '#64748b' }}>
                正在等待后端推送任务数据...
              </div>
            ) : (
              <TaskGraph tasks={tasks} onNodeClick={(task) => setSelectedTask(task)} />
            )}
          </div>

          {/* 底部 Agent 状态栏 */}
          <div style={{ padding: '12px 24px', background: '#fff', borderTop: '1px solid #e2e8f0', display: 'flex', gap: '12px', alignItems: 'center' }}>
            <strong style={{ fontSize: '14px', color: '#475569' }}>Agent 资源状态：</strong>
            {['Orchestrator', 'DB-01', 'BE-01', 'FE-01', 'QA-01'].map(agent => {
               const runningTask = tasks.find(t => t.assignee === agent && t.status === 'RUNNING');
               return (
                 <div key={agent} style={{ padding: '4px 12px', borderRadius: '16px', fontSize: '12px', background: runningTask ? '#fef3c7' : '#f1f5f9', color: runningTask ? '#d97706' : '#64748b', border: runningTask ? '1px solid #fcd34d' : '1px solid #e2e8f0' }}>
                   {agent}: {runningTask ? `执行中 (${runningTask.task_id})` : '空闲'}
                 </div>
               )
            })}
          </div>
        </div>

        {/* ================= 右侧详情面板 ================= */}
        <div style={{ width: '320px', flexShrink: 0, background: '#fff', borderLeft: '1px solid #e2e8f0', display: 'flex', flexDirection: 'column' }}>
          
          {/* 修复点：这里是标题的头，必须要有 div 包裹 */}
          <div style={{ padding: '20px', borderBottom: '1px solid #e2e8f0', background: '#f8fafc' }}>
            <h2 style={{ margin: 0, fontSize: '18px', color: '#1e293b' }}>任务详情面板</h2>
          </div>
          
          {/* 详情内容区 */}
          <div style={{ padding: '20px', overflowY: 'auto' }}>
            {selectedTask ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: '24px', fontWeight: 'bold', color: '#1e293b' }}>{selectedTask.task_id}</span>
                  <span style={{ 
                    padding: '4px 10px', borderRadius: '12px', fontSize: '12px', fontWeight: 'bold', color: '#fff',
                    background: statusColors[selectedTask.status] || '#9ca3af'
                  }}>
                    {selectedTask.status}
                  </span>
                </div>

                <div style={{ height: '1px', background: '#e2e8f0' }}></div>

                <div>
                  <div style={{ fontSize: '12px', color: '#64748b', marginBottom: '4px' }}>负责 Agent</div>
                  <div style={{ fontSize: '16px', fontWeight: '500', color: '#334155' }}>{selectedTask.assignee}</div>
                </div>

                <div>
                  <div style={{ fontSize: '12px', color: '#64748b', marginBottom: '4px' }}>前置依赖</div>
                  <div style={{ fontSize: '14px', color: '#334155' }}>
                    {selectedTask.depends_on.length ? selectedTask.depends_on.join(', ') : '无 (起始节点)'}
                  </div>
                </div>

                <div>
                  <div style={{ fontSize: '12px', color: '#64748b', marginBottom: '4px' }}>重试次数 / 预算</div>
                  <div style={{ fontSize: '14px', color: selectedTask.attempt_count > 0 ? '#ef4444' : '#334155' }}>
                    {selectedTask.attempt_count} 次
                  </div>
                </div>

                {selectedTask.error && (
                  <div style={{ padding: '12px', background: '#fef2f2', border: '1px solid #fecaca', borderRadius: '8px', color: '#ef4444', fontSize: '13px' }}>
                    ⚠️ 错误信息：{selectedTask.error}
                  </div>
                )}
              </div>
            ) : (
              <div style={{ color: '#94a3b8', textAlign: 'center', marginTop: '40px', fontSize: '14px' }}>
                请在左侧点击任意任务节点<br/>查看详细信息
              </div>
            )}
          </div>
        </div>

      </div>
    </div>
  );
}

export default App;