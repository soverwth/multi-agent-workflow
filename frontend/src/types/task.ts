/**
 * B05 交互展示 Agent —— 任务快照数据模型
 *
 * 设计对齐文档第 5、8、9.2 节：界面只读取任务快照与事件流，
 * 可追踪当前尝试（attempt_id / retry_count）与输入版本（input_snapshot）。
 */

/** 任务状态（文档表 7：状态含义与状态迁移条件） */
export type TaskStatus =
  | 'PENDING'   // 已生成，等待依赖
  | 'READY'     // 依赖已验收，等待派发
  | 'RUNNING'   // Agent 执行中
  | 'REVIEWING' // 候选产物提交，独立验收中
  | 'SUCCEEDED' // 验收通过
  | 'FAILED'    // 验收/执行失败，待返修
  | 'BLOCKED';  // 上游失效或变更影响，暂停放行

/** 数据来源：模拟（Mock 推演）与真实（连接真实 Orchestrator）必须明确区分 */
export type DataSource = 'simulation' | 'real';

/** 交付产物引用（对应文档表 8 交付文件清单） */
export interface Artifact {
  path: string;      // 相对路径，例如 backend/lost/publish_handler.pseudo
  version: string;   // 产物版本，例如 r1 / r2
  desc?: string;
}

/** 验收证据（对应文档 5.5.2 正常门槛 TC-P01/02/03） */
export interface TestEvidence {
  case_id: string;        // 例如 TC-P01
  passed: boolean;
  detail: string;
}

/** 异议 / 缺陷（对应文档 D-01 缺陷记录与 5.4 异议处理） */
export interface Objection {
  id: string;             // 例如 D-01
  from: string;           // 提出角色，例如 QA-01
  reason: string;
  status: 'open' | 'resolved';
  created_at: string;
}

/** 一条执行尝试记录（文档 8.2：attempt_id 单调递增，retry_count 统计失败重派） */
export interface AttemptRecord {
  attempt_id: number;
  retry_count: number;
  revalidation_id?: string | null; // 上游失效重验时使用，例如 RV-01
  started_at: string;
  finished_at?: string | null;
  result: 'success' | 'failure' | 'running';
  note?: string;
}

/** 标准任务记录（界面视图，来自 get_snapshot / 事件流） */
export interface Task {
  task_id: string;
  goal: string;
  depends_on: string[];
  status: TaskStatus;
  assignee: string;             // 运行执行角色，例如 BE-01
  spec_version: string;         // S1 设计基线
  contract_version: string;     // C1 契约版本
  input_snapshot: string;       // 当前输入快照版本标识，例如 snap-T04-r1
  attempt_id: number;           // 本次派发编号（单调递增）
  retry_count: number;          // 失败重派次数
  revalidation_id?: string | null;
  write_scope: string[];        // 允许写入范围
  outputs: Artifact[];          // 已交付产物
  evidence: TestEvidence[];     // 验收证据清单
  objections: Objection[];      // 关联的异议/缺陷
  attempts: AttemptRecord[];    // 尝试历史
  blocked_reason?: string | null;
  error?: string | null;
  source?: DataSource;          // 单条任务的数据来源（缺省时取全局）
}

/** 任务依赖边 */
export interface TaskEdgeDef {
  from: string;
  to: string;
  /** 上游失效导致下游重验的边（文档 7.4 / 8.2） */
  revalidation?: boolean;
}
