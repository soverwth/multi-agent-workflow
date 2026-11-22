/**
 * B05-D24/D26：从 B02 真实接口加载任务运行（快照 + DAG + 事件）。
 *
 * 设计约束：
 * - 真实接口失败时**不得**把模拟数据当作真实数据展示；
 * - 首次加载失败会清空数据；之后轮询失败只标记「降级」，保留最近一次
 *   成功快照，并在界面上明确提示，避免把旧数据误认为当前状态；
 * - 事件流用后端 `/events?after=<sequence>` 做增量游标，按 sequence 去重；
 * - 轮询间隔可配置，卸载时清理定时器与在途请求。
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  controlTaskRun,
  fetchTaskRun,
  replayTaskRun,
  restoreTaskRun,
  type RunEvent,
  type TaskApiResult,
} from '../api/taskRunApi';
import type { Task } from '../types/task';

export interface UseTaskRunOptions {
  baseUrl: string;
  runId: string;
  /** 轮询间隔（毫秒）；0 表示只加载一次。 */
  pollIntervalMs?: number;
  enabled?: boolean;
}

/** 监控连接状态：在线 / 单次失败（降级） / 连续失败（离线） / 同步中 / 未开始。 */
export type RunConnection = 'idle' | 'syncing' | 'online' | 'degraded' | 'offline';

export interface ReplayResult {
  consistent: boolean;
  mismatches: { task_id: string; snapshot: string; replayed: string }[];
  eventCount: number;
  lastSequence: number;
}

export interface TaskRunState {
  tasks: Task[];
  meta: TaskApiResult['meta'] | null;
  events: RunEvent[];
  dag: TaskApiResult['dag'] | null;
  loading: boolean;
  error: string | null;
  lastUpdated: string | null;
  /** 连接状态，用于界面显示「断线重连中 / 最近一次快照」。 */
  connection: RunConnection;
  /** 已经同步到的事件序号（增量游标）。 */
  eventCursor: number;
  /** 最近一次回放一致性检查结果。 */
  replayResult: ReplayResult | null;
  reload: () => void;
  step: () => Promise<void>;
  runToCompletion: (maxSteps?: number) => Promise<void>;
  replay: () => Promise<void>;
  restore: () => Promise<void>;
}

const MAX_EVENTS = 5000;

function mergeEvents(previous: RunEvent[], incoming: RunEvent[]): RunEvent[] {
  const byKey = new Map<string, RunEvent>();
  for (const event of previous) byKey.set(event.event_id || `seq-${event.sequence}`, event);
  for (const event of incoming) byKey.set(event.event_id || `seq-${event.sequence}`, event);
  return [...byKey.values()].sort((a, b) => a.sequence - b.sequence).slice(-MAX_EVENTS);
}

export function useTaskRun(options: UseTaskRunOptions): TaskRunState {
  const { baseUrl, runId, pollIntervalMs = 0, enabled = true } = options;
  const [tasks, setTasks] = useState<Task[]>([]);
  const [meta, setMeta] = useState<TaskApiResult['meta'] | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [dag, setDag] = useState<TaskApiResult['dag'] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [connection, setConnection] = useState<RunConnection>('idle');
  const [eventCursor, setEventCursor] = useState(0);
  const [replayResult, setReplayResult] = useState<ReplayResult | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  const controllerRef = useRef<AbortController | null>(null);
  const cursorRef = useRef(0);
  const failuresRef = useRef(0);
  const inflightRef = useRef(false);

  const reload = useCallback(() => setReloadToken((value) => value + 1), []);

  const applyResult = useCallback((result: TaskApiResult, incremental: boolean) => {
    setTasks(result.tasks);
    setMeta(result.meta);
    setDag(result.dag);
    setEvents((prev) => mergeEvents(incremental ? prev : [], result.events));
    const nextCursor = result.events.reduce((max, event) => Math.max(max, event.sequence), cursorRef.current);
    cursorRef.current = nextCursor;
    setEventCursor(nextCursor);
    failuresRef.current = 0;
    setConnection('online');
    setError(null);
    setLastUpdated(new Date().toISOString());
  }, []);

  const load = useCallback(
    async (incremental: boolean) => {
      if (!enabled || !baseUrl || !runId || inflightRef.current) return;
      inflightRef.current = true;
      const controller = new AbortController();
      controllerRef.current = controller;
      setLoading(true);
      setConnection((prev) => (prev === 'offline' ? 'syncing' : prev));
      try {
        const result = await fetchTaskRun(
          { baseUrl, runId },
          controller.signal,
          incremental ? Math.max(cursorRef.current, 0) : undefined,
        );
        if (controller.signal.aborted) return;
        applyResult(result, incremental);
      } catch (caught) {
        if (controller.signal.aborted) return;
        failuresRef.current += 1;
        setConnection(failuresRef.current >= 3 ? 'offline' : 'degraded');
        setError(caught instanceof Error ? caught.message : String(caught));
        // 首次加载失败必须清空：不能让旧运行的数据冒充当前运行。
        // 后续轮询失败保留最近一次成功快照，由 connection 状态负责标注降级。
        if (!incremental) {
          setTasks([]);
          setMeta(null);
          setDag(null);
          setEvents([]);
          cursorRef.current = 0;
          setEventCursor(0);
        }
      } finally {
        inflightRef.current = false;
        if (!controller.signal.aborted) setLoading(false);
      }
    },
    [applyResult, baseUrl, enabled, runId],
  );

  useEffect(() => {
    // 未启用时无需清空：调用方在模拟数据源下不会读取这里的真实数据。
    if (!enabled || !baseUrl || !runId) return undefined;

    controllerRef.current?.abort();
    cursorRef.current = 0;
    failuresRef.current = 0;
    // 不在这里同步 setState：全量加载完成后 applyResult 会用新事件整体替换旧列表，
    // 同时重置游标与连接状态，避免 effect 触发级联渲染。
    void load(false);

    let timer: ReturnType<typeof setInterval> | null = null;
    if (pollIntervalMs > 0) {
      timer = setInterval(() => void load(true), pollIntervalMs);
    }
    return () => {
      if (timer) clearInterval(timer);
      controllerRef.current?.abort();
    };
  }, [baseUrl, runId, pollIntervalMs, enabled, reloadToken, load]);

  const command = useCallback(
    async (invoke: () => Promise<void>) => {
      if (!enabled || !baseUrl || !runId) return;
      setLoading(true);
      try {
        await invoke();
        setError(null);
        reload();
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      } finally {
        setLoading(false);
      }
    },
    [baseUrl, enabled, reload, runId],
  );

  const step = useCallback(
    () => {
      setReplayResult(null);
      return command(() => controlTaskRun({ baseUrl, runId }, 'step'));
    },
    [baseUrl, command, runId],
  );
  const runToCompletion = useCallback(
    (maxSteps = 200) => {
      setReplayResult(null);
      return command(() => controlTaskRun({ baseUrl, runId }, 'run', maxSteps));
    },
    [baseUrl, command, runId],
  );
  const restore = useCallback(
    () => {
      setReplayResult(null);
      return command(async () => {
        await restoreTaskRun({ baseUrl, runId });
      });
    },
    [baseUrl, command, runId],
  );
  const replay = useCallback(
    () => command(async () => {
      const result = await replayTaskRun({ baseUrl, runId });
      const mismatches = Array.isArray(result.mismatches)
        ? (result.mismatches as { task_id?: unknown; snapshot?: unknown; replayed?: unknown }[]).map((item) => ({
            task_id: String(item.task_id ?? ''),
            snapshot: String(item.snapshot ?? ''),
            replayed: String(item.replayed ?? ''),
          }))
        : [];
      setReplayResult({
        consistent: result.consistent === true,
        mismatches,
        eventCount: typeof result.event_count === 'number' ? result.event_count : 0,
        lastSequence: typeof result.last_sequence === 'number' ? result.last_sequence : 0,
      });
    }),
    [baseUrl, command, runId],
  );

  return {
    tasks,
    meta,
    events,
    dag,
    loading,
    error,
    lastUpdated,
    connection,
    eventCursor,
    replayResult,
    reload,
    step,
    runToCompletion,
    replay,
    restore,
  };
}
