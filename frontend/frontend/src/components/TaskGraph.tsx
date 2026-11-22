import { ReactFlow, Background, Controls, MiniMap, useNodesState, useEdgesState } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useEffect, useMemo } from 'react';
import { statusColors } from '../constants/status';
import { layoutTasks } from '../layout/dagreLayout';
import type { Task, TaskStatus } from '../types/task';
import { TaskNode } from './TaskNode';

const nodeTypes = { taskNode: TaskNode };

interface Props {
  tasks: Task[];
  selectedId?: string | null;
  onNodeClick?: (task: Task) => void;
}

export function TaskGraph({ tasks, selectedId, onNodeClick }: Props) {
  const { nodes: layoutedNodes, edges: layoutedEdges } = useMemo(() => layoutTasks(tasks), [tasks]);
  const [nodes, setNodes, onNodesChange] = useNodesState(layoutedNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(layoutedEdges);

  useEffect(() => {
    setNodes(layoutedNodes.map((n) => ({ ...n, selected: n.id === selectedId })));
    setEdges(layoutedEdges);
  }, [layoutedNodes, layoutedEdges, selectedId, setNodes, setEdges]);

  return (
    <div style={{ width: '100%', height: '100%' }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.15 }}
        proOptions={{ hideAttribution: true }}
        onNodeClick={(_, node) => {
          const clicked = tasks.find((t) => t.task_id === node.id);
          if (clicked && onNodeClick) onNodeClick(clicked);
        }}
      >
        <Background gap={18} size={1} color="#e2e8f0" />
        <Controls showInteractive={false} />
        <MiniMap
          pannable
          zoomable
          nodeColor={(n) => {
            const status = (n.data as { task?: { status?: TaskStatus } })?.task?.status;
            return status ? statusColors[status] : '#cbd5e1';
          }}
          style={{ background: '#f8fafc', border: '1px solid #e2e8f0' }}
        />
      </ReactFlow>
    </div>
  );
}
