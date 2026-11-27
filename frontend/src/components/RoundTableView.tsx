/**
 * 需求讨论页（阶段一 A—H 看板 + 圆桌插话）
 *
 * 界面先行、功能占位：八阶段进度条读取讨论运行的真实 stage；
 * 圆桌区域的发言、点名、辩论为阶段三交互的占位，不发送任何请求。
 */

import type { DiscussionRun } from '../api/workbenchApi';
import { narrativeForDiscussionStage, narrativeForDiscussionStatus } from '../constants/naturalLanguage';
import { DISCUSSION_PHASES, SEATS, phaseIndexForStage } from '../constants/discussion';

interface Props {
  discussion: DiscussionRun | null;
  /** 用户在圆桌输入的文字；由 App 持有，便于阶段三接入时直接读取。 */
  chatDraft: string;
  onChatDraftChange: (value: string) => void;
  onOpenRequirements: () => void;
}

export function RoundTableView({ discussion, chatDraft, onChatDraftChange, onOpenRequirements }: Props) {
  const phase = phaseIndexForStage(discussion?.stage);
  const signoffs = discussion?.blackboard?.signoffs ?? [];
  const claims = discussion?.blackboard?.claims ?? [];
  const objections = discussion?.blackboard?.objections ?? [];

  return (
    <>
      <div className="page-head">
        <div className="page-head-text">
          <h2>需求讨论 · 八阶段看板</h2>
          <p>
            多角色按 A—H 推进：独立发散、结构化批判、共识评价、agent 互相确认。全程不设审批门；
            你随时可以在右侧圆桌插话、点名或要求举证，流程不会因等待你而暂停。
          </p>
        </div>
        <div className="page-head-actions">
          <span className={`badge ${discussion ? 'info' : 'neutral'}`}>
            <i />
            {discussion ? `${discussion.run_id} · ${narrativeForDiscussionStatus(discussion.status)}` : '尚未创建讨论运行'}
          </span>
          <button type="button" className="btn" onClick={onOpenRequirements}>查看需求与方案 →</button>
        </div>
      </div>

      <div className="phase-rail" aria-label="讨论八阶段进度">
        {DISCUSSION_PHASES.map((item, index) => {
          const state = index < phase.done ? 'done' : index === phase.current && phase.current < DISCUSSION_PHASES.length ? 'active' : '';
          return (
            <div className="phase-rail-wrap" key={item.code} style={{ display: 'contents' }}>
              <div className={`phase-rail-step ${state}`}>
                <i>{item.code}</i>
                <b>{item.name}</b>
              </div>
              {index < DISCUSSION_PHASES.length - 1 && <span className="phase-rail-line" aria-hidden="true" />}
            </div>
          );
        })}
      </div>

      <div className="metrics">
        <div className="metric"><span>当前阶段</span><strong>{discussion ? narrativeForDiscussionStage(discussion.stage) : '—'}</strong></div>
        <div className="metric"><span>批判轮次</span><em>{discussion ? `${discussion.round ?? 0} / ${discussion.max_rounds ?? '—'}` : '—'}</em></div>
        <div className="metric"><span>独立观点</span><em>{claims.length}</em></div>
        <div className="metric"><span>异议 / 已回应</span><em>{objections.length} / {objections.filter((item) => item.response).length}</em></div>
        <div className="metric"><span>角色表态</span><em>{signoffs.length} / {SEATS.length}</em></div>
      </div>

      <div className="roundtable">
        <section className="card">
          <div className="card-head">
            <div>
              <h3>圆桌 · 多 agent 与用户同场</h3>
              <p>用户驱动、不阻塞：点名发言、追问观点、质疑要举证、让两个 agent 辩论。</p>
            </div>
            <span className="badge purple"><i />阶段三交互 · 占位</span>
          </div>

          <div className="roundtable-seats" aria-label="圆桌席位">
            {SEATS.map((seat, index) => {
              const stance = signoffs.find((item) => item.role === seat.name);
              const stanceClass = !stance ? 'pending' : stance.stance === 'Agree' ? 'agree' : stance.stance === 'Disagree' ? 'disagree' : 'conditional';
              return (
                <div className={`seat${index === 0 && discussion ? ' speaking' : ''}`} key={seat.id}>
                  <span className="seat-avatar" style={{ background: seat.color }}>{seat.name.slice(0, 1)}</span>
                  <b>{seat.name}</b>
                  <small>{seat.hint}</small>
                  {stance && <span className={`badge ${stanceClass === 'agree' ? 'ready' : stanceClass === 'disagree' ? 'real offline' : 'local'}`}>{stance.stance}</span>}
                </div>
              );
            })}
          </div>

          <div className="chat-log" aria-label="讨论记录">
            {claims.length === 0 && (
              <div className="chat-msg system">
                <span className="chat-msg-avatar" style={{ background: '#9aa7b8' }}>系</span>
                <div className="chat-msg-body">讨论尚未开始。到「项目主理人」提交想法后，这里会按阶段显示各角色的观点、异议与表态。</div>
              </div>
            )}
            {claims.slice(-6).map((claim) => {
              const seat = SEATS.find((item) => item.name === claim.role);
              return (
                <div className="chat-msg" key={claim.claim_id}>
                  <span className="chat-msg-avatar" style={{ background: seat?.color ?? '#6b7a90' }}>{claim.role.slice(0, 1)}</span>
                  <div className="chat-msg-body">
                    <b>{claim.role}</b>
                    {claim.claim}
                    {claim.reason ? <div className="muted">理由：{claim.reason}</div> : null}
                    {claim.round ? <time>第 {claim.round} 轮</time> : null}
                  </div>
                </div>
              );
            })}
            {objections.slice(-3).map((item) => (
              <div className="chat-msg" key={item.objection_id}>
                <span className="chat-msg-avatar" style={{ background: '#b42318' }}>质</span>
                <div className="chat-msg-body">
                  <b>异议 · {item.raised_by}</b>
                  {item.content}
                  {item.response ? <div className="muted">回应：{item.response}</div> : null}
                </div>
              </div>
            ))}
          </div>

          <div className="chat-input">
            <textarea
              aria-label="圆桌插话"
              placeholder="随时插话：追问观点、质疑并要求举证、补充需求……（功能占位，暂不发送）"
              value={chatDraft}
              onChange={(event) => onChatDraftChange(event.target.value)}
              rows={2}
            />
            <button type="button" className="btn primary" disabled>发送</button>
          </div>
          <div className="chat-tools">
            <button type="button" className="btn sm" disabled>点名发言…</button>
            <button type="button" className="btn sm" disabled>追问这个观点</button>
            <button type="button" className="btn sm" disabled>要求举证</button>
            <button type="button" className="btn sm" disabled>让两位 agent 辩论</button>
            <span className="composer-hint">用户不响应时，agent 按推荐方案继续推进。</span>
          </div>
        </section>

        <aside style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <section className="card card-pad">
            <div className="card-head" style={{ marginBottom: 8 }}>
              <h3>本轮议题</h3>
              <span className="badge neutral">黑板</span>
            </div>
            {(discussion?.blackboard?.open_questions?.length ?? 0) === 0
              ? <p className="muted" style={{ margin: 0 }}>暂无未决问题</p>
              : (
                <ul className="plain-list" style={{ fontSize: 12.5, lineHeight: 1.8 }}>
                  {discussion?.blackboard?.open_questions?.map((item, index) => <li key={index}>{item}</li>)}
                </ul>
              )}
          </section>

          <section className="card card-pad">
            <div className="card-head" style={{ marginBottom: 8 }}>
              <h3>设计规格细化进度</h3>
              <span className="badge neutral">阶段一终点</span>
            </div>
            <dl className="kv">
              <dt>需求条目</dt><dd>{discussion?.blackboard?.requirements_draft?.requirements?.length ?? discussion?.blackboard?.r1?.requirements.length ?? 0} 条</dd>
              <dt>接口 / 错误码</dt><dd>待设计规格阶段补全</dd>
              <dt>字段边界 / 数据模型</dt><dd>待设计规格阶段补全</dd>
              <dt>非功能约束</dt><dd>待设计规格阶段补全</dd>
            </dl>
          </section>
        </aside>
      </div>
    </>
  );
}
