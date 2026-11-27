/**
 * 讨论阶段一（A—H）的展示常量：从 RoundTableView 拆出，便于复用且不破坏 Fast Refresh。
 */

export const DISCUSSION_PHASES = [
  { code: 'A', name: '框定' },
  { code: 'B', name: '独立发散' },
  { code: 'C', name: '聚类整合' },
  { code: 'D', name: '结构化批判' },
  { code: 'E', name: '共识评价' },
  { code: 'F', name: '方案审阅' },
  { code: 'G', name: '需求确认' },
  { code: 'H', name: '设计规格' },
];

/** 后端 stage 名 → 八阶段代号（STOPPED/COMPLETED 等控制态另行处理） */
const STAGE_TO_PHASE: Record<string, string> = {
  INTAKE: 'A',
  DIVERGE: 'B',
  CLUSTER: 'C',
  CRITIQUE: 'D',
  EVALUATE: 'E',
  PROPOSAL_REVIEW: 'F',
  HUMAN_CONFIRMATION: 'G',
  DESIGN_SPEC: 'H',
};

export function phaseIndexForStage(stage: string | undefined): { current: number; done: number } {
  if (stage === 'COMPLETED') {
    return { current: DISCUSSION_PHASES.length, done: DISCUSSION_PHASES.length };
  }
  const code = STAGE_TO_PHASE[stage ?? ''] ?? 'A';
  const index = DISCUSSION_PHASES.findIndex((item) => item.code === code);
  return { current: index, done: index };
}

export const SEATS = [
  { id: 'pm', name: '产品经理', color: '#2756d2', hint: '用户价值 · 范围 · 优先级' },
  { id: 'ux', name: '用户研究员', color: '#0b6b8f', hint: '场景 · 可用性' },
  { id: 'arch', name: '技术架构师', color: '#5b21b6', hint: '边界 · 非功能约束' },
  { id: 'critic', name: '质疑者', color: '#b42318', hint: '风险 · 反例 · 举证' },
];
