/**
 * 需求与方案页（任务文档阶段一终点）
 *
 * 展示讨论产生的内容：需求分析、PRD（需求草案/R1）、
 * 候选方案（观点/异议/Proposal）与 agent 角色的共识表态。
 * 所有内容读取 /api/runs 与 /api/runs/{id}/design-spec；
 * 尚未产生的内容明确标注"未产生"，不伪造。全程无人工审批门。
 */

import { useEffect, useMemo, useState } from 'react';
import {
  getDesignSpec,
  getDiscussionRun,
  listDiscussionRuns,
  type DiscussionRun,
  type RequirementItem,
} from '../api/workbenchApi';
import {
  narrativeForDiscussionStage,
  narrativeForDiscussionStatus,
} from '../constants/naturalLanguage';
import type { DataSource } from '../types/task';

interface Props {
  apiBase: string;
  source: DataSource;
  selectedRunId: string;
  onSelectRun: (runId: string) => void;
  onCreateTaskRun: (runId: string) => void;
}

function asText(value: string | string[] | undefined): string {
  if (Array.isArray(value)) return value.join('；');
  return value ?? '';
}

function requirementList(items: RequirementItem[] | undefined, emptyHint: string) {
  if (!items || items.length === 0) return <p className="empty-state">{emptyHint}</p>;
  return (
    <div className="requirement-list">
      {items.map((item) => (
        <div className="requirement-item" key={item.req_id}>
          <strong>{item.req_id} · {item.description}</strong>
          <p>验收：{asText(item.acceptance)}</p>
          {(item.priority || item.status) && (
            <p className="muted">优先级：{item.priority ?? '—'} · 状态：{item.status ?? '—'}</p>
          )}
        </div>
      ))}
    </div>
  );
}

export function RequirementsView({
  apiBase,
  source,
  selectedRunId,
  onSelectRun,
  onCreateTaskRun,
}: Props) {
  const isReal = source === 'real';
  const [runs, setRuns] = useState<DiscussionRun[]>([]);
  const [detail, setDetail] = useState<DiscussionRun | null>(null);
  const [designSpec, setDesignSpec] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState('');
  const loading = isReal && Boolean(selectedRunId) && detail?.run_id !== selectedRunId && !error;

  useEffect(() => {
    if (!isReal) return undefined;
    const controller = new AbortController();
    void listDiscussionRuns(apiBase, controller.signal)
      .then((data) => {
        setRuns(data.runs ?? []);
        if (!selectedRunId && data.runs?.length) onSelectRun(data.runs[0].run_id);
      })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) {
          setError(caught instanceof Error ? caught.message : String(caught));
        }
      });
    return () => controller.abort();
  }, [apiBase, isReal, onSelectRun, selectedRunId]);

  useEffect(() => {
    if (!isReal || !selectedRunId) return undefined;
    const controller = new AbortController();
    void Promise.all([
      getDiscussionRun(apiBase, selectedRunId, controller.signal),
      getDesignSpec(apiBase, selectedRunId, controller.signal).catch(() => null),
    ])
      .then(([detailData, specData]) => {
        if (controller.signal.aborted) return;
        setDetail(detailData.run);
        setDesignSpec(specData?.design_spec ?? null);
        setError('');
      })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) {
          setError(caught instanceof Error ? caught.message : String(caught));
          setDetail(null);
        }
      });
    return () => controller.abort();
  }, [apiBase, isReal, selectedRunId]);

  const board = detail?.blackboard;
  const r1 = board?.r1 ?? null;
  const draftRequirements = useMemo(
    () => board?.requirements_draft?.requirements ?? [],
    [board],
  );

  if (!isReal) {
    return (
      <div className="stage-panel">
        <div className="stage-panel-head">
          <h2>需求与方案</h2>
          <p>展示需求分析、PRD、候选方案和 agent 共识。这些内容只在真实讨论运行中存在。</p>
        </div>
        <div className="source-note sim">
          演示数据快照只含任务编排结果，不含讨论过程。请切换到「真实接口」查看真实需求与方案。
        </div>
        <div className="stage-card">
          <h3>如何产生需求与方案</h3>
          <p>到「项目主理人」提交想法并推进讨论，各角色会产出需求草案与候选方案，agent 互相确认后发布 R1。</p>
        </div>
      </div>
    );
  }

  return (
    <div className="stage-panel">
      <div className="stage-panel-head">
        <h2>需求与方案</h2>
        <p>读取讨论运行：需求分析与 PRD、候选方案与异议、agent 共识表态与设计规格。</p>
      </div>

      <div className="source-note real">真实数据：内容来自 /api/runs 与 /api/runs/{'{id}'}/design-spec。</div>

      <div className="requirement-select-bar">
        <label htmlFor="discussion-select">讨论运行</label>
        <select
          id="discussion-select"
          value={selectedRunId}
          onChange={(event) => onSelectRun(event.target.value)}
        >
          <option value="">请选择讨论运行</option>
          {runs.map((run) => (
            <option key={run.run_id} value={run.run_id}>
              {run.idea} · {run.run_id}
            </option>
          ))}
        </select>
        {selectedRunId && detail && (
          <button
            type="button"
            onClick={() => onCreateTaskRun(selectedRunId)}
            disabled={!r1}
            title={r1 ? '由已确认 R1 创建任务运行' : '只有发布 R1 后才能创建任务运行'}
          >
            由 R1 创建任务运行
          </button>
        )}
      </div>

      {error && <div className="alert error" role="alert">读取失败：{error}</div>}
      {loading && <div className="stage-card">正在读取讨论运行…</div>}

      {detail && !loading && (
        <>
          <div className="requirement-summary">
            <div className="metric"><strong>{narrativeForDiscussionStage(detail.stage)}</strong><span>当前阶段</span></div>
            <div className="metric"><strong>{narrativeForDiscussionStatus(detail.status)}</strong><span>控制状态</span></div>
            <div className="metric"><strong>{detail.round ?? 0} / {detail.max_rounds ?? '—'}</strong><span>批判轮次</span></div>
            <div className="metric"><strong>{board?.claims?.length ?? 0}</strong><span>独立观点</span></div>
          </div>

          <section className="requirement-section">
            <h3>项目想法与需求分析</h3>
            <div className="requirement-grid">
              <div><b>项目想法</b><p>{detail.idea}</p></div>
              <div><b>约束与目标</b><p>{detail.constraints || '未填写'}</p></div>
              <div><b>问题定义</b><p>{board?.problem || '尚未产生（讨论还在进行中）'}</p></div>
              <div>
                <b>关键假设</b>
                {board?.assumptions?.length
                  ? <ul>{board.assumptions.map((item, index) => <li key={index}>{item}</li>)}</ul>
                  : <p>尚未产生</p>}
              </div>
            </div>
          </section>

          <section className="requirement-section">
            <h3>PRD · 需求草案 {r1 ? '（R1 已发布）' : '（R1 未发布）'}</h3>
            {requirementList(r1?.requirements ?? draftRequirements, '讨论尚未产出需求条目；agent 共识确认后才会发布 R1。')}
          </section>

          <section className="requirement-section">
            <h3>候选方案与异议</h3>
            <div className="requirement-grid">
              <div>
                <b>Proposal 草案</b>
                <p className="proposal">{board?.proposal_draft || '尚未形成候选方案'}</p>
              </div>
              <div>
                <b>独立观点（候选来源）</b>
                {board?.claims?.length ? (
                  <ul>
                    {board.claims.map((claim) => (
                      <li key={claim.claim_id}>
                        <strong>{claim.claim_id} · {claim.role}</strong>：{claim.claim}
                        {claim.reason ? `（理由：${claim.reason}）` : ''}
                      </li>
                    ))}
                  </ul>
                ) : <p>尚未进行独立发散</p>}
              </div>
              <div>
                <b>未决问题</b>
                {board?.open_questions?.length
                  ? <ul>{board.open_questions.map((item, index) => <li key={index}>{item}</li>)}</ul>
                  : <p>暂无未决问题</p>}
              </div>
              <div>
                <b>异议处理</b>
                {board?.objections?.length ? (
                  <ul>
                    {board.objections.map((item) => (
                      <li key={item.objection_id}>
                        {item.objection_id} · {item.content}
                        {item.status ? `（${item.status}）` : ''}
                        {item.response ? ` → 回应：${item.response}` : ''}
                      </li>
                    ))}
                  </ul>
                ) : <p>暂无异议记录</p>}
              </div>
            </div>
          </section>

          <section className="requirement-section">
            <h3>agent 共识 · 角色表态 {r1 ? `· R1 已由 ${r1.confirmed_by?.length ?? 0} 个角色确认` : '· 尚未达成'}</h3>
            {board?.signoffs?.length ? (
              <div className="stances">
                {board.signoffs.map((item, index) => {
                  const cls = item.stance === 'Agree' ? 'agree' : item.stance === 'Disagree' ? 'disagree' : item.stance === 'Conditional' ? 'conditional' : 'pending';
                  return (
                    <div className={`stance ${cls}`} key={index}>
                      <div className="stance-head">
                        <b>{item.role}</b>
                        <span className={`badge ${cls === 'agree' ? 'ready' : cls === 'disagree' ? 'real offline' : cls === 'conditional' ? 'local' : 'neutral'}`}>
                          {item.stance === 'Agree' ? '赞同' : item.stance === 'Disagree' ? '反对' : item.stance === 'Conditional' ? '有条件赞同' : item.stance}
                        </span>
                      </div>
                      <small>{item.reason || '未给出理由'}</small>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="empty-state">尚无角色表态。需求确认由 agent 角色互相确认完成，不设人工勾选。</p>
            )}
            {board?.decisions?.length ? (
              <div style={{ marginTop: 12 }}>
                <b style={{ fontSize: 12, color: 'var(--muted)' }}>讨论中形成的决定</b>
                <ul className="plain-list" style={{ fontSize: 12.5, lineHeight: 1.8 }}>
                  {board.decisions.map((item, index) => (
                    <li key={item.decision_id ?? index}>{item.decided_by ? `${item.decided_by}：` : ''}{item.content}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            <div style={{ marginTop: 12 }}>
              <b style={{ fontSize: 12, color: 'var(--muted)' }}>最近一次共识评价</b>
              <p style={{ margin: '4px 0 0', fontSize: 12.5, lineHeight: 1.7 }}>
                {detail.latest_consensus ? (detail.latest_consensus.reason || '已产生评价') : '尚未执行共识评价'}
                {detail.latest_consensus?.open_count ? ` · 未关闭异议 ${detail.latest_consensus.open_count}` : ''}
              </p>
            </div>
            {detail.failure && (
              <div className="alert error">讨论失败：{detail.failure.message || '未知原因'}（{detail.failure.stage || detail.stage}）</div>
            )}
          </section>

          <section className="requirement-section">
            <h3>设计规格</h3>
            {designSpec ? (
              <details>
                <summary>查看由 R1 生成的设计规格（{Object.keys(designSpec).length} 个顶层字段）</summary>
                <pre className="spec-pre">{JSON.stringify(designSpec, null, 2)}</pre>
              </details>
            ) : (
              <p className="empty-state">该讨论尚无 R1，设计规格未生成。</p>
            )}
          </section>
        </>
      )}
    </div>
  );
}
