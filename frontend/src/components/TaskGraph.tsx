import { ReactFlow, Background, Controls, useNodesState, useEdgesState } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useEffect, useMemo } from 'react';
import { layoutTasks } from '../layout/dagreLayout';
import type { Task } from '../types/task';
import { TaskNode } from './TaskNode';

const nodeTypes = { taskNode: TaskNode };

export function TaskGraph({ tasks, onNodeClick }: { tasks: Task[]; onNodeClick?: (task: Task) => void }) {
  const { nodes: layoutedNodes, edges: layoutedEdges } = useMemo(() => layoutTasks(tasks), [tasks]);
  const [nodes, setNodes, onNodesChange] = useNodesState(layoutedNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(layoutedEdges);

  useEffect(() => {
    setNodes(layoutedNodes);
    setEdges(layoutedEdges);
  }, [layoutedNodes, layoutedEdges, setNodes, setEdges]);

   return (
    <div style={{ width: '100%', height: '100%' }}> {/* 修改高度，适应新布局 */}
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        fitView
        // 增加点击事件
        onNodeClick={(_, node) => {
          // 从 tasks 里找出被点击的节点数据，传给 App.tsx
          const clickedTask = tasks.find(t => t.task_id === node.id);
          if (clickedTask && onNodeClick) {
            onNodeClick(clickedTask);
          }
        }}
      >
        <Background />
        <Controls />
      </ReactFlow>
    </div>
  );
}