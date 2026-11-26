/**
 * B05 版本链面包屑：把快照里已有的版本字段串成一条可追溯链路。
 * 纯展示，不需要后端新增接口；缺失字段显示 — 而不是编造版本号。
 */

export interface VersionMeta {
  run_id: string;
  spec_version?: string | null;
  contract_version?: string | null;
  plan_version?: string | null;
  input_snapshot?: string | null;
  project_id?: string | null;
}

interface Props {
  meta: VersionMeta | null;
  sourceLabel: string;
}

export function VersionChain({ meta, sourceLabel }: Props) {
  if (!meta) {
    return <div className="version-chain muted">尚未加载运行，版本链不可用</div>;
  }

  const nodes = [
    { label: '项目', value: meta.project_id },
    { label: '规格', value: meta.spec_version },
    { label: '契约', value: meta.contract_version },
    { label: '计划', value: meta.plan_version },
    { label: '运行', value: meta.run_id },
    { label: '输入快照', value: meta.input_snapshot ? meta.input_snapshot.slice(0, 12) : null },
  ];

  return (
    <div className="version-chain" aria-label="版本追溯链">
      <span className="version-source">{sourceLabel}</span>
      {nodes.map((node, index) => (
        <span className="version-segment" key={node.label}>
          {index > 0 ? <i aria-hidden="true">→</i> : null}
          <span className="version-node">
            <small>{node.label}</small>
            <b className={node.value ? 'mono' : 'muted'}>{node.value || '—'}</b>
          </span>
        </span>
      ))}
    </div>
  );
}
