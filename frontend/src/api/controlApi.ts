import type { ControlAction, ControlCommand } from '../types/events';

/**
 * B05 → B02 控制接口客户端。
 *
 * 设计约束（文档 10.5 验收条件）：界面不直接改状态。
 * 所有暂停 / 恢复 / 取消 / 重派 / 变更确认均以指令形式发给 Orchestrator，
 * 前端只根据 control_ack 和后续事件流更新视图。
 */

let seq = 0;
const nextRequestId = () => `CTRL-${Date.now().toString(36)}-${(++seq).toString(36)}`;

export interface ControlApi {
  send: (action: ControlAction, options?: { taskId?: string; reason?: string }) => ControlCommand;
  pause: (reason?: string) => ControlCommand;
  resume: (reason?: string) => ControlCommand;
  cancel: (taskId: string, reason: string) => ControlCommand;
  retry: (taskId: string, reason?: string) => ControlCommand;
  confirmChange: (reason?: string) => ControlCommand;
}

/**
 * 创建一个控制 API 客户端。
 * @param transport 实际发送函数（WebSocket.send 的封装）
 * @param operator  操作人，用于人工确认入口留痕
 */
export function createControlApi(
  transport: (payload: ControlCommand) => void,
  operator = 'human-operator',
): ControlApi {
  const send = (action: ControlAction, options?: { taskId?: string; reason?: string }): ControlCommand => {
    const command: ControlCommand = {
      request_id: nextRequestId(),
      action,
      task_id: options?.taskId,
      reason: options?.reason,
      operator,
      timestamp: new Date().toISOString(),
    };
    transport(command);
    return command;
  };

  return {
    send,
    pause: (reason) => send('pause', { reason }),
    resume: (reason) => send('resume', { reason }),
    cancel: (taskId, reason) => send('cancel', { taskId, reason }),
    retry: (taskId, reason) => send('retry', { taskId, reason }),
    confirmChange: (reason) => send('confirm_change', { reason }),
  };
}
