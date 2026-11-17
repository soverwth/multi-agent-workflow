import { WebSocketServer } from 'ws';

// 在 8000 端口启动 WebSocket 服务
const wss = new WebSocketServer({ port: 8000 });
console.log('Mock WebSocket 服务器已启动: ws://localhost:8000');

let tasks = [
  { task_id: 'T01', depends_on: [], status: 'SUCCEEDED', assignee: 'Orchestrator', attempt_count: 1 },
  { task_id: 'T02', depends_on: ['T01'], status: 'PENDING', assignee: 'DB-01', attempt_count: 0 },
  { task_id: 'T03', depends_on: ['T02'], status: 'PENDING', assignee: 'BE-01', attempt_count: 0 },
  { task_id: 'T04', depends_on: ['T03'], status: 'PENDING', assignee: 'BE-01', attempt_count: 0 },
];

wss.on('connection', (ws) => {
  console.log('前端已连接！');
  ws.send(JSON.stringify({ type: 'snapshot', tasks }));

  let step = 0;
  const interval = setInterval(() => {
    step++;
    if (step === 1) {
      tasks[1].status = 'RUNNING';
      ws.send(JSON.stringify({ type: 'update', task_id: 'T02', status: 'RUNNING', attempt_count: 1 }));
    } else if (step === 2) {
      tasks[1].status = 'SUCCEEDED';
      ws.send(JSON.stringify({ type: 'update', task_id: 'T02', status: 'SUCCEEDED', attempt_count: 1 }));
      
      tasks[2].status = 'READY';
      ws.send(JSON.stringify({ type: 'update', task_id: 'T03', status: 'READY', attempt_count: 0 }));
    }  else if (step >= 3) {
      tasks[2].status = 'FAILED';
      ws.send(JSON.stringify({ type: 'update', task_id: 'T03', status: 'FAILED', attempt_count: 1, error: 'timeout' }));
      
      // 10秒后重置状态，重新开始演示
      setTimeout(() => {
        tasks = [
          { task_id: 'T01', depends_on: [], status: 'SUCCEEDED', assignee: 'Orchestrator', attempt_count: 1 },
          { task_id: 'T02', depends_on: ['T01'], status: 'PENDING', assignee: 'DB-01', attempt_count: 0 },
          { task_id: 'T03', depends_on: ['T02'], status: 'PENDING', assignee: 'BE-01', attempt_count: 0 },
          { task_id: 'T04', depends_on: ['T03'], status: 'PENDING', assignee: 'BE-01', attempt_count: 0 },
        ];
        ws.send(JSON.stringify({ type: 'snapshot', tasks }));
        step = 0; // 重置步数
      }, 5000);
      clearInterval(interval);
    }
  }, 3000);

  ws.on('close', () => clearInterval(interval));
});