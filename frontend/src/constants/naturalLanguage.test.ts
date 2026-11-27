import { describe, expect, it } from 'vitest';
import {
  formatDuration,
  narrativeForDiscussionStage,
  narrativeForDiscussionStatus,
  narrativeForEvent,
  narrativeForStatus,
  progressPercent,
} from './naturalLanguage';

describe('面向普通用户的自然语言展示', () => {
  it('把九态翻译成人话，未知状态保留原始值', () => {
    expect(narrativeForStatus('RETRYING')).toContain('重试');
    expect(narrativeForStatus('WAITING_DEPENDENCY')).toContain('等前面的任务');
    expect(narrativeForStatus('SUCCEEDED')).toContain('通过验收');
    expect(narrativeForStatus('NEW_STATE')).toContain('NEW_STATE');
  });

  it('把讨论阶段与状态翻译成人话', () => {
    expect(narrativeForDiscussionStage('HUMAN_CONFIRMATION')).toContain('agent');
    expect(narrativeForDiscussionStage('HUMAN_CONFIRMATION')).not.toContain('六');
    expect(narrativeForDiscussionStage('STOPPED')).toContain('不代表达成共识');
    expect(narrativeForDiscussionStatus('WAITING_HUMAN')).toContain('无人工审批');
    expect(narrativeForDiscussionStatus('UNKNOWN')).toContain('UNKNOWN');
  });

  it('把事件类型翻译成人话，未知事件保留原始值', () => {
    expect(narrativeForEvent('TASK_ACCEPTED')).toContain('质量验收');
    expect(narrativeForEvent('TASK_BLOCKED')).toContain('阻断');
    expect(narrativeForEvent('CUSTOM_EVENT')).toBe('CUSTOM_EVENT');
  });

  it('格式化耗时与完成进度', () => {
    expect(formatDuration(45)).toBe('45 秒');
    expect(formatDuration(90)).toBe('1 分 30 秒');
    expect(formatDuration(null)).toBe('—');
    expect(progressPercent(3, 4)).toBe(75);
    expect(progressPercent(0, 0)).toBe(0);
    expect(progressPercent(10, 4)).toBe(100);
  });
});
