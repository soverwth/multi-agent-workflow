/**
 * B05 项目总览：项目名称 / 目标 / 阶段 / 完成进度（需求文档第 2 条、验收第 1 条）
 *
 * 真实模式下只读取 B02 的 /api/runs 与 /api/task-runs；
 * 模拟模式下读取由真实编排器产出的本地 fixture，并明确标注。
 */

import { useCallback, useEffect, useState } from 'react';
import {
  listDiscussionRuns,
  listTaskRuns,
  type DiscussionRun,
  type TaskRunSummary,
} from '../api/workbenchApi';
import {
  narrativeForDiscussionStage,
  narrativeForDiscussionStatus,
  narrativeForStatus,
  progressPercent,
} from '../constants/naturalLanguage';
import type { DataSource } from '../types/task';

export interface CurrentProject {
  runId: string;
  projectId?: string;
  status?: string;
  completed?: number;
  total?: number;
  specVersion?: string;
}

interface Props {
  apiBase: string;
  source: DataSource;
  currentProject: CurrentProject | null;
  simulationProjects: CurrentProject[];
  selectedRunId: string;
  onOpenRun: (runId: string) => void;
  onOpenDiscussion: (runId: string) => void;
  onCreate: (payload: {
    idea: string;
    constraints: string;
    scenario: string;
    max_rounds: number;
  }) => Promise<void>;
}

const SCENARIOS = [
  { value: 'normal', label: '正常收敛（agent 共识）' },
  { value: 'value_conflict', label: '价值分歧（自动辩论后判定）' },
  { value: 'budget_exhaustion', label: '预算耗尽（诚实停止）' },
  { value: 'agent_failure', label: 'Agent 失败（阻断）' },
];

export function ProjectOverview({
  apiBase,
  source,
  currentProject,
  simulationProjects,
  selectedRunId,
  onOpenRun,
  onOpenDiscussion,
  onCreate,
}: Props) {
  const isReal = source === 'real';
  const [discussions, setDiscussions] = useState<DiscussionRun[]>([]);
  const [taskRuns, setTaskRuns] = useState<TaskRunSummary[]>([]);
  const [error, setError] = useState('');
  const [idea, setIdea] = useState('');
  const [constraints, setConstraints] = useState('');
  const [scenario, setScenario] = useState('normal');
  const [submitting, setSubmitting] = useState(false);

  const loadProjects = useCallback(async (signal?: AbortSignal) => {
    const [discussionData, taskData] = await Promise.all([
      listDiscussionRuns(apiBase, signal),
      listTaskRuns(apiBase, signal),
    ]);
    return { discussions: discussionData.runs ?? [], taskRuns: taskData.runs ?? [] };
  }, [apiBase]);

  const applyProjects = useCallback((data: {
    discussions: DiscussionRun[];
    taskRuns: TaskRunSummary[];
  }) => {
    setDiscussions(data.discussions);
    setTaskRuns(data.taskRuns);
    setError('');
  }, []);

  useEffect(() => {
    if (!isReal) return undefined;
    const controller = new AbortController();
    let active = true;
    void loadProjects(controller.signal)
      .then((data) => { if (active) applyProjects(data); })
      .catch((caught: unknown) => {
        if (active && !controller.signal.aborted) {
          setError(caught instanceof Error ? caught.message : String(caught));
        }
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [applyProjects, isReal, loadProjects]);

  const handleCreate = useCallback(async () => {
    if (submitting || idea.trim().length < 3) return;
    setSubmitting(true);
    try {
      await onCreate({
        idea: idea.trim(),
        constraints: constraints.trim(),
        scenario,
        max_rounds: 2,
      });
      setIdea('');
      setConstraints('');
      applyProjects(await loadProjects());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setSubmitting(false);
    }
  }, [applyProjects, constraints, idea, loadProjects, onCreate, scenario, submitting]);

  const percent = currentProject ? progressPercent(currentProject.completed, currentProject.total) : 0;

  return (
    <div className="stage-panel">
      <div className="page-head">
        <div className="page-head-text">
          <h2>项目总览</h2>
          <p>
            汇总平台里的项目：需求讨论、任务运行、当前阶段和完成进度。
            所有数据来自后端接口或本地真实编排器产物，页面不会自行生成项目。
          </p>
        </div>
      </div>

      <div className={`source-note ${isReal ? 'real' : 'sim'}`}>
        {isReal
          ? '真实数据：正在读取 B02 的 /api/runs 与 /api/task-runs。'
          : '演示数据：来自真实编排器生成的本地快照，不写入后端，也不标记为真实执行结果。'}
      </div>

      {error && <div className="alert error" role="alert">读取项目列表失败：{error}</div>}

      <div className="project-create-card">
        <div>
          <h3>创建新项目</h3>
          <p>提交项目想法后，由 B02 讨论服务创建真实讨论运行；后续需求分析与确认在「项目主理人」阶段查看。</p>
        </div>
        <label className="field-label" htmlFor="project-idea">项目想法</label>
        <textarea
          id="project-idea"
          value={idea}
          onChange={(event) => setIdea(event.target.value)}
          placeholder="例如：为社团设计一个活动报名与签到工具"
          rows={2}
          maxLength={500}
          disabled={!isReal || submitting}
        />
        <label className="field-label" htmlFor="project-constraints">约束与目标（可选）</label>
        <input
          id="project-constraints"
          value={constraints}
          onChange={(event) => setConstraints(event.target.value)}
          placeholder="例如：首期只做报名与签到，不接入支付"
          disabled={!isReal || submitting}
        />
        <div className="project-create-row">
          <select
            aria-label="演示场景"
            value={scenario}
            onChange={(event) => setScenario(event.target.value)}
            disabled={!isReal || submitting}
          >
            {SCENARIOS.map((item) => (
              <option key={item.value} value={item.value}>{item.label}</option>
            ))}
          </select>
          <button
            type="button"
            className="primary-button"
            onClick={() => void handleCreate()}
            disabled={!isReal || submitting || idea.trim().length < 3}
          >
            {submitting ? '正在创建…' : '提交想法，创建项目'}
          </button>
          {!isReal && <span className="hint">创建项目会写入后端，请先切换到「真实接口」。</span>}
        </div>
      </div>

      <div className="project-current-card">
        <div className="project-current-head">
          <div>
            <h3>当前运行的项目</h3>
            <p className="muted">
              {currentProject
                ? `${currentProject.runId}${currentProject.projectId ? ` · ${currentProject.projectId}` : ''}`
                : '尚未加载运行：请到「编排与执行」输入运行编号，或从下方项目列表进入。'}
            </p>
          </div>
          {currentProject && <span className="project-percent">{percent}%</span>}
        </div>
        {currentProject && (
          <>
            <div className="progress-track"><div className="progress-fill" style={{ width: `${percent}%` }} /></div>
            <div className="project-facts">
              <span>完成任务：{currentProject.completed ?? 0} / {currentProject.total ?? 0}</span>
              <span>当前状态：{narrativeForStatus(currentProject.status ?? 'PENDING')}</span>
              {currentProject.specVersion && <span>规格版本：{currentProject.specVersion}</span>}
            </div>
          </>
        )}
      </div>

      {!isReal && simulationProjects.length > 0 && (
        <section className="project-section">
          <h3>演示项目（本地快照）</h3>
          <div className="project-grid">
            {simulationProjects.map((project) => {
              const value = progressPercent(project.completed, project.total);
              return (
                <button
                  type="button"
                  key={project.runId}
                  className={`project-card${selectedRunId === project.runId ? ' active' : ''}`}
                  onClick={() => onOpenRun(project.runId)}
                >
                  <span className="project-card-kind">演示运行</span>
                  <strong>{project.runId}</strong>
                  <small>{project.projectId ?? '本地快照项目'}</small>
                  <div className="progress-track"><div className="progress-fill" style={{ width: `${value}%` }} /></div>
                  <span className="project-card-meta">{narrativeForStatus(project.status ?? 'PENDING')} · {value}%</span>
                </button>
              );
            })}
          </div>
        </section>
      )}

      {isReal && (
        <>
          <section className="project-section">
            <h3>需求讨论项目（{discussions.length}）</h3>
            {discussions.length === 0 ? (
              <p className="empty-state">后端还没有讨论运行。用上方表单提交一个项目想法即可创建。</p>
            ) : (
              <div className="project-grid">
                {discussions.map((run) => (
                  <button
                    type="button"
                    key={run.run_id}
                    className="project-card"
                    onClick={() => onOpenDiscussion(run.run_id)}
                  >
                    <span className="project-card-kind">需求讨论</span>
                    <strong>{run.idea}</strong>
                    <small>{run.run_id}</small>
                    <span className="project-card-desc">{run.constraints || '未填写约束与目标'}</span>
                    <span className="project-card-meta">
                      {narrativeForDiscussionStage(run.stage)} · {narrativeForDiscussionStatus(run.status)}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </section>

          <section className="project-section">
            <h3>开发任务运行（{taskRuns.length}）</h3>
            {taskRuns.length === 0 ? (
              <p className="empty-state">后端还没有任务运行。可从讨论结论或设计规格创建。</p>
            ) : (
              <div className="project-grid">
                {taskRuns.map((run) => (
                  <button
                    type="button"
                    key={run.run_id}
                    className={`project-card${selectedRunId === run.run_id ? ' active' : ''}`}
                    onClick={() => onOpenRun(run.run_id)}
                  >
                    <span className="project-card-kind">任务运行</span>
                    <strong>{run.run_id}</strong>
                    <small>{run.project_id ?? run.plan_id ?? '未关联项目'}</small>
                    <span className="project-card-meta">
                      {narrativeForStatus(run.status ?? 'PENDING')} · {run.plan_version ?? '版本未知'}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
