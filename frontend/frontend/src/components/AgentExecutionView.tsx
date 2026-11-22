/**
 * B05 Agent 执行中心（需求文档第 6 条、验收第 4 条）
 *
 * 展示 Agent 角色、当前任务、执行日志、测试结果和异常信息。
 * 数据完全来自任务快照与事件流：角色按 role_id/assignee 聚合，
 * 日志是真实事件，测试结果来自证据字段，异常来自 error/blocked_reason/缺陷。
 * 不生成任何模拟执行结果。
 */

import { useMemo } from 'react';
import {
  formatDuration,
  narrativeForEvent,
  narrativeForStatus,
} from '../constants/naturalLanguage';
import { statusColors, statusLabels } from '../constants/status';
import type { DataSource, Task } from '../types/task';

interface ActivityEvent {
  sequence: number;
  type: string;
  task_id?: string | null;
  attempt_id?: number | null;
  occurred_at?: string;
}

interface Props {
  tasks: Task[];
  events: ActivityEvent[];
  source: DataSource;
  onSelectTask: (taskId: string) => void;
}

interface AgentGroup {
  name: string;
  capability?: string;
  block?: string;
  tasks: Task[];
  active: Task[];
  logs: ActivityEvent[];
}

function agentName(task: Task): string {
  return task.role_id || task.assignee || task.block_id || '未分配角色';
}

function groupByAgent(tasks: Task[], events: ActivityEvent[]): AgentGroup[] {
  const byName = new Map<string, AgentGroup>();
  for (const task of tasks) {
    const name = agentName(task);
    let group = byName.get(name);
    if (!group) {
      group = { name, capability: task.capability, block: task.block_id, tasks: [], active: [], logs: [] };
      byName.set(name, group);
    }
    group.tasks.push(task);
    if (['RUNNING', 'REVIEWING', 'RETRYING', 'READY'].includes(task.status)) {
      group.active.push(task);
    }
  }
  const taskIds = new Set(tasks.map((task) => task.task_id));
  const ordered = [...events].sort((left, right) => right.sequence - left.sequence);
  for (const event of ordered) {
    if (!event.task_id || !taskIds.has(event.task_id)) continue;
    const task = tasks.find((item) => item.task_id === event.task_id);
    if (!task) continue;
    const group = byName.get(agentName(task));
    if (group && group.logs.length < 40) group.logs.push(event);
  }
  return [...byName.values()].sort((left, right) => right.tasks.length - left.tasks.length);
}

export function AgentExecutionView({ tasks, events, source, onSelectTask }: Props) {
  const groups = useMemo(() => groupByAgent(tasks, events), [tasks, events]);
  const totalLogs = events.length;

  return (
    <div className="stage-panel agents-stage">
      <div className="stage-panel-head">
        <h2>05 · Agent 执行中心</h2>
        <p>
          按执行角色汇总任务：当前任务、真实事件日志、测试结果与异常信息都来自后端快照。
          点击任务可回到「编排与执行」查看完整详情。
        </p>
      </div>

      <div className={`source-note ${source === 'real' ? 'real' : 'sim'}`}>
        {source === 'real'
          ? '真实数据：角色由 role_id 得出，日志由 /events 事件流得出。'
          : '演示数据：来自真实编排器生成的本地快照，不是实时执行。'}
        <span>共 {totalLogs} 条事件、{groups.length} 个执行角色。</span>
      </div>

      {tasks.length === 0 ? (
        <div className="stage-card">
          <p>尚未加载任务运行。请到「编排与执行」输入运行编号，或先创建一个项目。</p>
        </div>
      ) : (
        <div className="agent-groups">
          {groups.map((group) => {
            const current = group.active[0] ?? group.tasks[0];
            const succeeded = group.tasks.filter((task) => task.status === 'SUCCEEDED').length;
            const failures = group.tasks.filter((task) =>
              ['FAILED', 'BLOCKED'].includes(task.status),
            ).length;
            const evidences = group.tasks.flatMap((task) =>
              task.evidence.map((evidence) => ({ ...evidence, task_id: task.task_id })),
            );
            const requiredTests = group.tasks.flatMap((task) => task.required_test_ids ?? []);
            const problems = group.tasks.filter((task) =>
              task.error || task.blocked_reason || task.objections.length > 0,
            );
            const reviews = group.tasks.filter((task) => task.review?.decision);

            return (
              <section className="agent-group" key={group.name}>
                <header className="agent-group-head">
                  <div>
                    <h3>{group.name}</h3>
                    <p>
                      {[group.capability && `能力 ${group.capability}`, group.block && `归属 ${group.block}`]
                        .filter(Boolean)
                        .join(' · ') || '未登记能力信息'}
                    </p>
                  </div>
                  <div className="agent-group-stats">
                    <span>{group.tasks.length} 个任务</span>
                    <span className="ok">{succeeded} 通过</span>
                    {failures > 0 && <span className="bad">{failures} 异常</span>}
                  </div>
                </header>

                <div className="agent-current">
                  <b>当前任务</b>
                  {current ? (
                    <button type="button" className="agent-task-link" onClick={() => onSelectTask(current.task_id)}>
                      <span style={{ color: statusColors[current.status] }}>● {statusLabels[current.status]}</span>
                      <strong>{current.task_id}</strong>
                      <span>{current.goal}</span>
                      <small>{narrativeForStatus(current.status)}</small>
                    </button>
                  ) : <span>暂无任务</span>}
                </div>

                <div className="agent-columns">
                  <div className="agent-column">
                    <h4>执行日志（最近事件）</h4>
                    {group.logs.length === 0 ? (
                      <p className="empty-state">该角色暂无事件日志</p>
                    ) : (
                      <ul className="agent-log">
                        {group.logs.slice(0, 8).map((event) => (
                          <li key={`${event.sequence}-${event.type}`}>
                            <span className="mono">#{event.sequence}</span>
                            <span>{narrativeForEvent(event.type)}</span>
                            <small>{event.task_id}</small>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>

                  <div className="agent-column">
                    <h4>测试结果</h4>
                    {evidences.length === 0 && requiredTests.length === 0 ? (
                      <p className="empty-state">该角色暂无测试证据</p>
                    ) : (
                      <>
                        <ul className="agent-evidence">
                          {evidences.slice(0, 8).map((evidence) => (
                            <li key={`${evidence.task_id}-${evidence.case_id}`}>
                              <span className={evidence.passed ? 'ok' : 'bad'}>
                                {evidence.passed ? '通过' : '未通过'}
                              </span>
                              <span>{evidence.case_id}</span>
                              <small>{evidence.task_id}</small>
                            </li>
                          ))}
                        </ul>
                        {requiredTests.length > 0 && (
                          <p className="hint">规定测试编号：{requiredTests.slice(0, 12).join('、')}</p>
                        )}
                      </>
                    )}
                    {reviews.length > 0 && (
                      <p className="hint">质量门结论：{reviews.map((task) => task.review?.decision).join('、')}</p>
                    )}
                  </div>

                  <div className="agent-column">
                    <h4>异常与缺陷</h4>
                    {problems.length === 0 ? (
                      <p className="empty-state">该角色暂无异常记录</p>
                    ) : (
                      <ul className="agent-problems">
                        {problems.slice(0, 6).map((task) => (
                          <li key={task.task_id}>
                            <button type="button" className="text-link" onClick={() => onSelectTask(task.task_id)}>
                              {task.task_id}
                            </button>
                            <span>{task.error || task.blocked_reason || task.objections[0]?.reason || '存在未关闭缺陷'}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                    {group.tasks.some((task) => task.duration_seconds) && (
                      <p className="hint">
                        最近耗时：{formatDuration(group.tasks.find((task) => task.duration_seconds)?.duration_seconds)}
                      </p>
                    )}
                  </div>
                </div>
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}
