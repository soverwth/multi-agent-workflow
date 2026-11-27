/**
 * 设计规格基线卡（任务文档 2.3：阶段一→二衔接对象）
 *
 * 基线 = baseline_id / project_id / revision / parent_baseline_id / r1_version / design_spec / sha256 / confirmed_by / generation_source。
 * 当前后端 design spec 只带 phase1_source（run_id / r1_version / generation_source / confirmed_by），
 * 因此 revision / parent / sha256 先显示为"待后端补齐"的占位，不伪造值。
 */

import { useMemo } from 'react';
import { factsFromDesignSpec } from '../utils/baseline';

interface Props {
  spec: Record<string, unknown> | null;
  /** 当前任务运行绑定的计划版本 / 规格版本，用于链尾。 */
  planVersion?: string;
  specVersion?: string;
}

export function BaselineCard({ spec, planVersion, specVersion }: Props) {
  const facts = useMemo(() => factsFromDesignSpec(spec), [spec]);
  const reqCount = Array.isArray(spec?.requirements) ? spec!.requirements.length : 0;
  const operations = Array.isArray((spec?.contract as Record<string, unknown> | undefined)?.operations)
    ? ((spec!.contract as Record<string, unknown[]>).operations ?? []).length
    : 0;

  return (
    <section className="card">
      <div className="card-head">
        <div>
          <h3>设计规格基线</h3>
          <p>阶段一只交付一个对象：带编号、哈希与父链的基线。阶段二按 baseline_id 签收，不按文件路径。</p>
        </div>
        <span className={`badge ${facts?.generationSource === 'handwritten' ? 'sim' : facts ? 'ready' : 'neutral'}`}>
          <i />
          {!facts ? '尚未加载基线' : facts.generationSource === 'handwritten' ? '手写 fixture · 仅作阶段二输入测试' : facts.generationSource === 'llm' ? '讨论产出 · 真实模型' : facts.generationSource === 'rules' ? '讨论产出 · 规则兜底' : facts.generationSource}
        </span>
      </div>

      <div className="baseline">
        <div>
          <dl className="kv">
            <dt>baseline_id</dt><dd className="mono">{facts?.baselineId ?? <Placeholder text="待后端补齐" />}</dd>
            <dt>revision</dt><dd className="mono">{facts?.revision ?? <Placeholder text="待后端补齐" />}</dd>
            <dt>parent_baseline_id</dt><dd className="mono">{facts?.parentId ?? <Placeholder text="首版 / 待补齐" />}</dd>
            <dt>r1_version</dt><dd className="mono">{facts?.r1Version ?? <Placeholder text="—" />}</dd>
            <dt>sha256</dt><dd><span className="hash-chip"><small>规范化内容哈希</small>{facts?.sha256 ?? <Placeholder text="待后端补齐" />}</span></dd>
            <dt>confirmed_by</dt><dd>{facts?.confirmedBy.length ? facts.confirmedBy.join('、') : <Placeholder text="agent 共识确认后写入" />}</dd>
          </dl>
        </div>
        <div>
          <div className="spec-outline">
            <div className="spec-outline-item"><span className="count">{reqCount}</span><b>需求条目</b><small>编号 · 描述 · 验收条件 · 优先级</small></div>
            <div className="spec-outline-item"><span className="count">{operations}</span><b>接口操作</b><small>方法 · 路径 · 请求 / 响应字段 · 状态码</small></div>
            <div className="spec-outline-item"><span className="count">—</span><b>错误码 / 字段边界</b><small>错误码 → 状态码；长度 · 格式 · 取值范围</small></div>
            <div className="spec-outline-item"><span className="count">—</span><b>数据模型 / 非功能</b><small>实体 · 关系 · 索引；性能 · 安全 · 并发</small></div>
          </div>
          <div style={{ marginTop: 12 }}>
            <div className="baseline-chain" aria-label="版本链">
              <span className="baseline-node current"><small>R1</small><b>{facts?.r1Version ?? '—'}</b></span>
              <i>→</i>
              <span className="baseline-node"><small>设计规格基线</small><b>{facts?.baselineId ?? '—'}</b></span>
              <i>→</i>
              <span className="baseline-node"><small>规格版本</small><b>{specVersion ?? '—'}</b></span>
              <i>→</i>
              <span className="baseline-node"><small>计划版本</small><b>{planVersion ?? '—'}</b></span>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function Placeholder({ text }: { text: string }) {
  return <span className="badge neutral" style={{ fontFamily: 'inherit' }}>{text}</span>;
}
