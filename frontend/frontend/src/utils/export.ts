import type { DataSource, Task } from '../types/task';
import type { AckEntry, LogEntry } from '../hooks/useTaskWebSocket';

/**
 * B05 成果导出（文档 10.5：成果导出，导出清单交 B01/B06 复核）
 * 导出内容均带数据源标识，模拟与真实结果明确区分。
 */

export interface ExportContext {
  source: DataSource;
  runId: string;
  specVersion: string;
  contractVersion: string;
  exportedAt: string;
}

function download(filename: string, content: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function stamp() {
  return new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
}

/** 导出完整任务快照 JSON（含输入版本、尝试历史、异议证据） */
export function exportSnapshot(tasks: Task[], ctx: ExportContext) {
  const payload = {
    export_type: 'task_snapshot',
    data_source: ctx.source,
    source_note: ctx.source === 'simulation' ? '模拟推演数据，非真实运行结果' : '真实 Orchestrator 运行结果',
    run_id: ctx.runId,
    spec_version: ctx.specVersion,
    contract_version: ctx.contractVersion,
    exported_at: ctx.exportedAt,
    task_count: tasks.length,
    tasks,
  };
  download(`task-snapshot-${ctx.source}-${stamp()}.json`, JSON.stringify(payload, null, 2), 'application/json');
}

/** 导出需求—任务—文件—测试追溯表 CSV（文档 9.3） */
export function exportTraceability(tasks: Task[], ctx: ExportContext) {
  const header = ['task_id', 'goal', 'status', 'assignee', 'depends_on', 'spec_version', 'contract_version',
    'input_snapshot', 'attempt_id', 'retry_count', 'outputs', 'evidence', 'objections', 'data_source'];
  const rows = tasks.map((t) => [
    t.task_id,
    t.goal,
    t.status,
    t.assignee,
    t.depends_on.join('|'),
    t.spec_version,
    t.contract_version,
    t.input_snapshot,
    String(t.attempt_id),
    String(t.retry_count),
    t.outputs.map((o) => `${o.path}@${o.version}`).join('|'),
    t.evidence.map((e) => `${e.case_id}:${e.passed ? 'PASS' : 'FAIL'}`).join('|'),
    t.objections.map((o) => `${o.id}:${o.status}`).join('|'),
    ctx.source,
  ]);
  const csv = [header, ...rows]
    .map((row) => row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(','))
    .join('\r\n');
  // BOM 让 Excel 正确识别中文
  download(`traceability-${ctx.source}-${stamp()}.csv`, `\uFEFF${csv}`, 'text/csv;charset=utf-8');
}

/** 导出缺陷 / 异议清单（交 B01/B06 复核） */
export function exportDefects(tasks: Task[], ctx: ExportContext) {
  const defects = tasks.flatMap((t) =>
    t.objections.map((o) => ({
      defect_id: o.id,
      task_id: t.task_id,
      raised_by: o.from,
      status: o.status,
      reason: o.reason,
      created_at: o.created_at,
      data_source: ctx.source,
    })),
  );
  const failed = tasks
    .filter((t) => t.status === 'FAILED' || t.status === 'BLOCKED')
    .map((t) => ({
      defect_id: 'STATUS',
      task_id: t.task_id,
      raised_by: t.assignee,
      status: t.status,
      reason: t.error || t.blocked_reason || '',
      created_at: ctx.exportedAt,
      data_source: ctx.source,
    }));
  download(
    `defects-${ctx.source}-${stamp()}.json`,
    JSON.stringify({ data_source: ctx.source, exported_at: ctx.exportedAt, items: [...defects, ...failed] }, null, 2),
    'application/json',
  );
}

/** 导出运行报告（事件日志 + 控制回执 + 统计） */
export function exportRunReport(tasks: Task[], logs: LogEntry[], acks: AckEntry[], ctx: ExportContext) {
  const counts = tasks.reduce<Record<string, number>>((acc, t) => {
    acc[t.status] = (acc[t.status] || 0) + 1;
    return acc;
  }, {});
  const payload = {
    export_type: 'run_report',
    data_source: ctx.source,
    source_note: ctx.source === 'simulation' ? '模拟推演，非真实运行结果' : '真实运行结果',
    run_id: ctx.runId,
    spec_version: ctx.specVersion,
    contract_version: ctx.contractVersion,
    exported_at: ctx.exportedAt,
    status_counts: counts,
    total_retries: tasks.reduce((sum, t) => sum + t.retry_count, 0),
    open_defects: tasks.flatMap((t) => t.objections).filter((o) => o.status === 'open').length,
    tasks,
    control_acks: acks,
    event_logs: logs,
  };
  download(`run-report-${ctx.source}-${stamp()}.json`, JSON.stringify(payload, null, 2), 'application/json');
}
