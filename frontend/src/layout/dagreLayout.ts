import dagre from '@dagrejs/dagre';
import type { Node, Edge } from '@xyflow/react';
import type { Task } from '../types/task';

const NODE_WIDTH = 180;
const NODE_HEIGHT = 60;

export function layoutTasks(tasks: Task[]): { nodes: Node[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: 'LR', nodesep: 40, ranksep: 80 });
  g.setDefaultEdgeLabel(() => ({}));

   const edges: Edge[] = [];
  tasks.forEach((t) => {
    g.setNode(t.task_id, { width: NODE_WIDTH, height: NODE_HEIGHT });
    
    // 查找当前节点的状态，如果它是 RUNNING 或 REVIEWING，指向它的线就动起来
    const isActive = t.status === 'RUNNING' || t.status === 'REVIEWING';

    t.depends_on.forEach((dep) => {
      if (tasks.some((x) => x.task_id === dep)) {
        g.setEdge(dep, t.task_id);
        edges.push({ 
          id: `${dep}-${t.task_id}`, 
          source: dep, 
          target: t.task_id, 
          animated: isActive // <--- 改这里，加上 animated
        });
      }
    });
  });

  dagre.layout(g);

  const nodes: Node[] = tasks.map((t) => {
    const pos = g.node(t.task_id);
    return {
      id: t.task_id,
      type: 'taskNode',
      position: { x: pos.x - NODE_WIDTH / 2, y: pos.y - NODE_HEIGHT / 2 },
      data: { task: t },
    };
  });

  return { nodes, edges };
}