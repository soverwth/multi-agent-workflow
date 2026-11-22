import type { DataSource, Task } from './task';

/**
 * B05 与 B02/B03 之间的协议类型。
 * 界面通过事件流被动接收状态，控制动作一律走 control API，
 * 不在前端直接改写任务状态。
 */

/** 服务端推送事件（来自 Orchestrator 事件流） */
export type ServerEvent =
  | {
      type: 'snapshot';
      /** 完整任务快照，来自 get_snapshot */
      tasks: Task[];
      source: DataSource;
      spec_version: string;
      contract_version: string;
      run_id: string;
      timestamp: string;
    }
  | {
      type: 'update';
      /** 增量任务更新：只包含变化字段 */
      task_id: string;
      patch: Partial<Task>;
      source: DataSource;
      timestamp: string;
    }
  | {
      type: 'log';
      level: 'info' | 'warn' | 'error' | 'success';
      message: string;
      task_id?: string;
      source: DataSource;
      timestamp: string;
    }
  | {
      type: 'control_ack';
      /** 控制指令的确认回执 —— 界面据此展示结果，不自行改状态 */
      request_id: string;
      command: ControlCommand['action'];
      accepted: boolean;
      message: string;
      source: DataSource;
      timestamp: string;
    };

/** 控制动作（对齐文档 9.2：暂停、恢复、取消、变更确认） */
export type ControlAction =
  | 'pause'      // 暂停派发
  | 'resume'     // 恢复派发
  | 'cancel'     // 取消任务
  | 'retry'      // 重派失败任务
  | 'confirm_change'; // 确认变更（R2/S2/C2）

export interface ControlCommand {
  request_id: string;
  action: ControlAction;
  task_id?: string;
  reason?: string;
  /** 操作人（人工确认入口） */
  operator: string;
  timestamp: string;
}

/** 界面操作模式：模拟推演 / 真实接口 */
export type ViewMode = DataSource;
