import { useCallback, useEffect, useRef, useState } from 'react';
import type { ControlCommand, ServerEvent } from '../types/events';
import type { DataSource, Task } from '../types/task';

export interface ConnectionState {
  connected: boolean;
  source: DataSource;
}

export interface LogEntry {
  id: string;
  level: 'info' | 'warn' | 'error' | 'success';
  message: string;
  task_id?: string;
  timestamp: string;
}

export interface AckEntry {
  id: string;
  command: string;
  accepted: boolean;
  message: string;
  timestamp: string;
}

let logSeq = 0;

/**
 * 订阅 Orchestrator 事件流。界面只读任务快照，控制动作经 control API 发出。
 * @param url         WebSocket 地址
 * @param source      期望的数据源标识（用于与服务端事件交叉校验，明确区分模拟/真实）
 * @param onCommand   发送控制指令的回调（由 createControlApi 提供 transport）
 */
export function useTaskWebSocket(
  url: string,
  source: DataSource,
  onCommandReady?: (transport: (payload: ControlCommand) => void) => void,
) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [meta, setMeta] = useState({ spec_version: '', contract_version: '', run_id: '' });
  const [connection, setConnection] = useState<ConnectionState>({ connected: false, source });
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [acks, setAcks] = useState<AckEntry[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const mountedRef = useRef(true);

  const pushLog = useCallback((e: Extract<ServerEvent, { type: 'log' }>) => {
    setLogs((prev) => [
      { id: `log-${++logSeq}`, level: e.level, message: e.message, task_id: e.task_id, timestamp: e.timestamp },
      ...prev,
    ].slice(0, 200));
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let closed = false;

    const connect = () => {
      const separator = url.includes('?') ? '&' : '?';
      const ws = new WebSocket(`${url}${separator}source=${source}`);
      wsRef.current = ws;

      ws.onopen = () => {
        if (!mountedRef.current) return;
        setConnection({ connected: true, source });
      };

      ws.onmessage = (event) => {
        if (!mountedRef.current) return;
        let msg: (ServerEvent & { _source?: DataSource }) | undefined;
        try {
          msg = JSON.parse(event.data);
        } catch {
          return;
        }
        if (!msg) return;

        switch (msg.type) {
          case 'snapshot':
            setTasks(msg.tasks);
            setMeta({
              spec_version: msg.spec_version,
              contract_version: msg.contract_version,
              run_id: msg.run_id,
            });
            break;
          case 'update':
            setTasks((prev) =>
              prev.map((t) => (t.task_id === msg!.task_id ? { ...t, ...msg!.patch } : t)),
            );
            break;
          case 'log':
            pushLog(msg);
            break;
          case 'control_ack': {
            const ack = msg as Extract<ServerEvent, { type: 'control_ack' }>;
            setAcks((prev) => [
              {
                id: ack.request_id || `ack-${++logSeq}`,
                command: ack.command,
                accepted: ack.accepted,
                message: ack.message,
                timestamp: ack.timestamp,
              },
              ...prev,
            ].slice(0, 100));
            break;
          }
        }
      };

      ws.onclose = () => {
        if (!mountedRef.current || closed) return;
        setConnection({ connected: false, source });
        reconnectTimer = setTimeout(connect, 2000);
      };

      ws.onerror = () => {
        // close 事件会触发重连，这里只标记一下，避免控制台噪音
        setConnection({ connected: false, source });
      };
    };

    // transport：所有控制指令统一以 {type:'control', command} 发给 B02
    const transport = (command: ControlCommand) => {
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'control', command }));
      } else {
        setAcks((prev) => [
          {
            id: command.request_id,
            command: command.action,
            accepted: false,
            message: '连接未建立，控制指令未送达 Orchestrator',
            timestamp: command.timestamp,
          },
          ...prev,
        ].slice(0, 100));
      }
    };
    onCommandReady?.(transport);

    connect();
    return () => {
      closed = true;
      mountedRef.current = false;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      wsRef.current?.close();
    };
  }, [url, source, pushLog, onCommandReady]);

  return { tasks, meta, connection, logs, acks };
}
