import { useEffect, useState } from 'react';
import type { Task } from '../types/task';

export function useTaskWebSocket(url: string) {
  const [tasks, setTasks] = useState<Task[]>([]);

  useEffect(() => {
    const ws = new WebSocket(url);

    ws.onopen = () => console.log('WebSocket 已连接成功！');

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      
      if (msg.type === 'snapshot') {
        // 收到全量快照，直接覆盖
        setTasks(msg.tasks);
      } else if (msg.type === 'update') {
        // 收到增量更新，只修改对应的任务
        setTasks((prev) =>
          prev.map((t) =>
            t.task_id === msg.task_id
              ? { ...t, status: msg.status, attempt_count: msg.attempt_count, error: msg.error }
              : t
          )
        );
      }
    };

    ws.onclose = () => console.log('WebSocket 连接断开');
    ws.onerror = (err) => console.error('WebSocket 发生错误', err);

    return () => ws.close();
  }, [url]);

  return tasks;
}