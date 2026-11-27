/**
 * 工作台页面定义：按三个阶段分组。
 *
 * 从 StageNav 组件文件拆出，便于其他页面复用且不破坏 Fast Refresh。
 * 新增的「需求讨论」「观测与回溯」两页是任务文档要求、功能尚未实现的占位页面。
 */

export type StageKey =
  | 'overview'
  | 'discussion'
  | 'roundtable'
  | 'requirements'
  | 'spec'
  | 'orchestrate'
  | 'agents'
  | 'delivery'
  | 'observation'
  | 'history';

export interface StageItem {
  key: StageKey;
  no: string;
  label: string;
  hint: string;
}

interface StageGroup {
  phase: 'project' | '1' | '2' | '3';
  title: string;
  items: StageItem[];
}

export const STAGE_GROUPS: StageGroup[] = [
  {
    phase: 'project',
    title: '项目',
    items: [
      { key: 'overview', no: '01', label: '项目总览', hint: '项目 / 阶段 / 进度' },
    ],
  },
  {
    phase: '1',
    title: '阶段一 · 想法 → 设计规格',
    items: [
      { key: 'discussion', no: '02', label: '项目主理人', hint: '提交想法 / 推进讨论' },
      { key: 'roundtable', no: '03', label: '需求讨论', hint: '八阶段看板 / 圆桌插话' },
      { key: 'requirements', no: '04', label: '需求与方案', hint: 'PRD / 候选方案 / 共识' },
      { key: 'spec', no: '05', label: '规格与计划', hint: '设计规格 / 基线 / 版本链' },
    ],
  },
  {
    phase: '2',
    title: '阶段二 · 编排 → 执行',
    items: [
      { key: 'orchestrate', no: '06', label: '编排与执行', hint: 'DAG / 甘特 / 事件流' },
      { key: 'agents', no: '07', label: 'Agent 执行', hint: '角色 / 日志 / 测试' },
      { key: 'delivery', no: '08', label: '成果交付', hint: '代码 / 文件 / 测试报告' },
    ],
  },
  {
    phase: '3',
    title: '阶段三 · 可观测',
    items: [
      { key: 'observation', no: '09', label: '观测与回溯', hint: '跨阶段时间轴 / 模型调用' },
      { key: 'history', no: '10', label: '历史项目', hint: '需求 / 任务 / 运行记录' },
    ],
  },
];

export const STAGES: StageItem[] = STAGE_GROUPS.flatMap((group) => group.items);

export const STAGE_TITLES: Record<StageKey, string> = Object.fromEntries(
  STAGES.map((stage) => [stage.key, stage.label]),
) as Record<StageKey, string>;
