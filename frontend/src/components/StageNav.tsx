/**
 * B05 工作台导航：覆盖需求文档要求的页面 +
 * 保留原有「编排与执行」作为默认落地页，避免破坏既有工作流监控与调试入口。
 *
 * 只是界面叙事层，不改变后端流程；各页面内容由 App 决定。
 */

export type StageKey =
  | 'overview'
  | 'discussion'
  | 'requirements'
  | 'spec'
  | 'orchestrate'
  | 'agents'
  | 'delivery'
  | 'history';

const STAGES: { key: StageKey; no: string; label: string; hint: string }[] = [
  { key: 'overview', no: '01', label: '项目总览', hint: '项目 / 目标 / 阶段进度' },
  { key: 'discussion', no: '02', label: '项目主理人', hint: '提交想法 / 讨论入口' },
  { key: 'requirements', no: '03', label: '需求与方案', hint: 'PRD / 候选方案 / 确认' },
  { key: 'spec', no: '04', label: '规格与计划', hint: '设计规格 / PM Agent / 版本链' },
  { key: 'orchestrate', no: '05', label: '编排与执行', hint: 'DAG / 时间线 / 事件流' },
  { key: 'agents', no: '06', label: 'Agent 执行', hint: '角色 / 日志 / 测试 / 异常' },
  { key: 'delivery', no: '07', label: '成果交付', hint: '代码 / 文件 / 测试报告' },
  { key: 'history', no: '08', label: '历史项目', hint: '需求 / 任务 / 执行记录' },
];

interface Props {
  value: StageKey;
  onChange: (stage: StageKey) => void;
}

export function StageNav({ value, onChange }: Props) {
  const activeIndex = STAGES.findIndex((stage) => stage.key === value);
  return (
    <nav className="stage-nav" aria-label="工作台页面导航">
      {STAGES.map((stage, index) => (
        <button
          type="button"
          key={stage.key}
          className={`stage-item${stage.key === value ? ' active' : ''}${index < activeIndex ? ' done' : ''}`}
          aria-current={stage.key === value ? 'page' : undefined}
          onClick={() => onChange(stage.key)}
        >
          <span className="stage-no">{stage.no}</span>
          <span className="stage-text">
            <b>{stage.label}</b>
            <small>{stage.hint}</small>
          </span>
        </button>
      ))}
    </nav>
  );
}
