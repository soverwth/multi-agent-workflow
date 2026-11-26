/**
 * B05-D25 任务详情面板
 *
 * 点击任务后展示：人工介入入口、输入、输出、依赖、验收条件、测试编号、日志、提交、缺陷。
 * 只渲染传入的数据；控制动作通过回调交给 App → API，不在前端直接改任务状态。
 */

import type { ReactNode } from 'react';
import { statusColors, statusLabels } from '../constants/status';
import type { DataSource, Task } from '../types/task';

interface Props {
  task: Task | null;
  dataSource?: DataSource;
  onClose?: () => void;
  /** 点击任务编号 / 依赖任务时联动定位（与 DAG、时间线共用）。 */
  onSelectTask?: (taskId: string) => void;
  /** 真实运行下可用的控制指令。 */
  onStep?: () => void;
  onRun?: () => void;
  canControl?: boolean;
  busy?: boolean;
}

const BLOCK_LABELS: Record<string, string> = {
  B01: 'B01 规格与计划',
  B02: 'B02 任务编排',
  B03: 'B03 状态持久化',
  B04: 'B04 Agent 执行',
  B05: 'B05 交互展示',
  B06: 'B06 质量验收',
};

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="detail-section">
      <h4 className="detail-section-title">{title}</h4>
      <div className="detail-section-body">{children}</div>
    </section>
  );
}

function Chips({
  items,
  empty,
  onItemClick,
}: {
  items: string[];
  empty: string;
  onItemClick?: (item: string) => void;
}) {
  if (!items.length) return <span className="muted">{empty}</span>;
  return (
    <div className="chip-row">
      {items.map((item) =>
        onItemClick ? (
          <button type="button" key={item} className="chip chip-button" onClick={() => onItemClick(item)}>
            {item}
          </button>
        ) : (
          <code key={item} className="chip">
            {item}
          </code>
        ),
      )}
    </div>
  );
}

export function TaskDetailPanel({
  task,
  dataSource = 'simulation',
  onClose,
  onSelectTask,
  onStep,
  onRun,
  canControl = false,
  busy = false,
}: Props) {
  if (!task) {
    return (
      <aside className="detail-panel detail-panel-empty">
        <p className="muted">点击任务节点查看详情</p>
      </aside>
    );
  }

  const color = statusColors[task.status] || '#94a3b8';
  const findings = (task.review?.findings ?? []).filter((item) => item.severity === 'blocking');
  const isReal = dataSource === 'real';
  const needsAttention = task.status === 'FAILED' || task.status === 'BLOCKED';

  return (
    <aside className="detail-panel" aria-label={`任务 ${task.task_id} 详情`}>
      <header className="detail-header">
        <strong>{task.task_id}</strong>
        <span className="status-pill" style={{ background: color }}>
          {statusLabels[task.status]}
        </span>
        <span className={`source-tag ${isReal ? 'real' : 'sim'}`} title="数据来源：真实后端或本地模拟">
          {isReal ? '真实接口' : '模拟数据'}
        </span>
        {onClose && (
          <button type="button" onClick={onClose} aria-label="关闭详情" className="icon-button">
            ×
          </button>
        )}
      </header>

      <p className="detail-goal">{task.goal}</p>

      <Section title="人工介入">
        {needsAttention ? (
          <div className={`alert ${task.status === 'BLOCKED' ? 'blocked' : 'error'}`}>
            <strong>{task.status === 'BLOCKED' ? '任务被阻断' : '任务失败'}</strong>
            <div>{task.error || task.blocked_reason || '后端未提供具体原因，请结合事件流排查。'}</div>
            <div className="hint">
              重试预算由后端状态机控制（retry {task.retry_count}）；前端只发起控制指令，不直接改写状态。
            </div>
          </div>
        ) : task.status === 'REVIEWING' ? (
          <div className="alert info">
            <strong>等待质量门验收</strong>
            <div>质量门结论：{task.review?.decision || '待返回'}</div>
            {findings.map((item) => (
              <div key={`${item.code}-${item.message}`} className="hint">
                {item.code}: {item.message}
              </div>
            ))}
          </div>
        ) : (
          <div className="hint">当前状态无需人工介入；可单步推进观察状态迁移。</div>
        )}
        {canControl ? (
          <div className="control-grid detail-controls">
            <button type="button" onClick={onStep} disabled={busy}>
              推进一步
            </button>
            <button type="button" onClick={onRun} disabled={busy}>
              运行至完成
            </button>
          </div>
        ) : (
          <div className="hint">模拟数据不发送控制指令；切到「真实接口」后可操作。</div>
        )}
      </Section>

      <Section title="负责与追踪">
        <div>{BLOCK_LABELS[task.block_id ?? ''] || task.block_id || '—'}</div>
        <div>
          角色 {task.role_id || task.assignee || '—'} · 能力 {task.capability || '—'} · 优先级 {task.priority || '—'}
        </div>
        <div>
          尝试 #{task.attempt_id} · 重试 {task.retry_count}
          {typeof task.duration_seconds === 'number' ? ` · 耗时 ${task.duration_seconds.toFixed(2)}s` : ''}
        </div>
        <div className="mono">输入快照 {task.input_snapshot || '—'}</div>
      </Section>

      <Section title="依赖（上游任务）">
        <Chips items={task.depends_on} empty="无依赖（根任务）" onItemClick={onSelectTask} />
      </Section>

      <Section title="输入">
        <Chips items={task.inputs ?? []} empty="未声明输入" />
      </Section>

      <Section title="输出产物">
        {task.outputs.length ? (
          <ul className="plain-list">
            {task.outputs.map((artifact) => (
              <li key={`${artifact.path}-${artifact.version}`}>
                <code>{artifact.path}</code>
                {artifact.version ? <span className="muted"> · {artifact.version}</span> : null}
              </li>
            ))}
          </ul>
        ) : (
          <span className="muted">尚无产物</span>
        )}
      </Section>

      <Section title="验收条件">
        <Chips items={task.acceptance ?? []} empty="未声明验收条件" />
      </Section>

      <Section title="规定测试编号">
        <Chips items={task.required_test_ids ?? []} empty="未声明测试编号" />
      </Section>

      <Section title="证据与测试">
        {task.evidence.length ? (
          <ul className="plain-list">
            {task.evidence.map((item) => (
              <li key={item.case_id}>
                <strong>{item.case_id}</strong> {item.passed ? '通过' : '未通过'}
                {item.detail ? ` · ${item.detail}` : ''}
              </li>
            ))}
          </ul>
        ) : (
          <span className="muted">尚无证据</span>
        )}
      </Section>

      <Section title="日志">
        {task.logs && task.logs.length ? (
          <ul className="plain-list">
            {task.logs.map((log) => (
              <li key={log.name}>
                <code>{log.name}</code>
                <span className="muted"> {log.sha256.slice(0, 12)}</span>
              </li>
            ))}
          </ul>
        ) : (
          <span className="muted">尚无日志</span>
        )}
      </Section>

      <Section title="提交">
        {task.candidate_commit ? <code>{task.candidate_commit}</code> : <span className="muted">尚无候选提交</span>}
      </Section>

      <Section title="缺陷 / 异议">
        {task.objections.length ? (
          <ul className="plain-list">
            {task.objections.map((item) => (
              <li key={item.id} className={item.status === 'open' ? 'danger-text' : ''}>
                <strong>{item.from}</strong> {item.reason}（{item.status === 'open' ? '未关闭' : '已关闭'}）
              </li>
            ))}
          </ul>
        ) : (
          <span className="muted">无缺陷</span>
        )}
        {findings.length > 0 && (
          <ul className="plain-list danger-text">
            {findings.map((item) => (
              <li key={`${item.code}-${item.message}`}>
                {item.code}: {item.message}
              </li>
            ))}
          </ul>
        )}
      </Section>

      {task.blocked_reason && (
        <Section title="阻塞原因">
          <span className="danger-text">{task.blocked_reason}</span>
        </Section>
      )}

      <Section title="尝试历史">
        {task.attempts.length ? (
          <ul className="plain-list">
            {task.attempts.map((attempt) => (
              <li key={`${attempt.attempt_id}-${attempt.started_at}`}>
                #{attempt.attempt_id} · {attempt.result} · retry {attempt.retry_count}
                {attempt.note ? ` · ${attempt.note}` : ''}
              </li>
            ))}
          </ul>
        ) : (
          <span className="muted">尚无尝试记录</span>
        )}
      </Section>
    </aside>
  );
}
