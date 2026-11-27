/**
 * 观测与回溯页（阶段三 · 界面占位）
 *
 * 任务文档要求：定义观测数据 schema（主体 / 类型 / 时间 / 上下文 / 载荷），
 * 其中"模型调用"是一等主体；提供跨阶段时间轴与事后回溯（技术级 / 因果级 / 业务级）。
 * 本页只搭界面骨架：指标从已有任务快照计算，模型调用与回溯入口为占位。
 */

import { useMemo } from 'react';
import type { DataSource, Task } from '../types/task';
import { statusColors } from '../constants/status';

interface Props {
  source: DataSource;
  tasks: Task[];
  eventCount: number;
}

const PHASES = ['阶段一 讨论', '阶段二 编排', '阶段二 执行', '阶段三 观测'];

export function ObservationView({ source, tasks, eventCount }: Props) {
  const totalMs = useMemo(() => {
    const durations = tasks.map((task) => (task.duration_seconds ?? 0) * 1000).filter((value) => value > 0);
    const sum = durations.reduce((acc, value) => acc + value, 0);
    return { sum, max: Math.max(1, ...durations, 1) };
  }, [tasks]);

  const callsPlaceholder = useMemo(() => {
    const roles = Array.from(new Set(tasks.map((task) => task.role_id || task.assignee || '未分配')));
    return roles.slice(0, 6);
  }, [tasks]);

  return (
    <>
      <div className="page-head">
        <div className="page-head-text">
          <h2>观测与回溯</h2>
          <p>
            把讨论、编排、执行三段过程收进同一套观测体系：跨阶段时间轴、每次模型调用的输入 / 输出哈希与用量、
            以及"这个结论由哪次调用产生"的反向追溯。
          </p>
        </div>
        <div className="page-head-actions">
          <span className={`badge ${source === 'real' ? 'real' : 'sim'}`}><i />{source === 'real' ? '真实运行' : '模拟推演 · 真实编排器产物'}</span>
          <button type="button" className="btn" disabled>导出观测数据</button>
        </div>
      </div>

      <div className="metrics">
        <div className="metric"><span>观测事件</span><em>{eventCount}</em></div>
        <div className="metric"><span>任务总耗时</span><em>{(totalMs.sum / 1000).toFixed(1)} s</em></div>
        <div className="metric"><span>最长任务</span><em>{(totalMs.max / 1000).toFixed(1)} s</em></div>
        <div className="metric"><span>模型调用</span><em>—</em></div>
        <div className="metric"><span>可追溯产物</span><em>{tasks.reduce((acc, task) => acc + task.outputs.length, 0)}</em></div>
      </div>

      <section className="card">
        <div className="card-head">
          <div>
            <h3>跨阶段时间轴</h3>
            <p>讨论 → 编排 → 执行进入同一条时间轴，而不是各做各的。</p>
          </div>
          <span className="badge neutral">占位：时间轴对齐算法待实现</span>
        </div>
        <div className="observation-timeline">
          {PHASES.map((label, index) => (
            <div className="obs-row" key={label}>
              <b>{label}</b>
              <div className="obs-track">
                <div
                  className="obs-span"
                  style={{
                    left: `${index * 4}%`,
                    width: `${Math.max(18, 92 - index * 12)}%`,
                    background: index === 0 ? '#3b82f6' : index < 3 ? '#f59e0b' : '#8b5cf6',
                    opacity: tasks.length === 0 ? 0.35 : 1,
                  }}
                >
                  {tasks.length === 0 ? '暂无数据' : index === 0 ? '讨论事件 · 待接入' : index === 3 ? '观测事件 · 待接入' : `${tasks.filter((task) => task.status === 'SUCCEEDED').length}/${tasks.length} 任务`}
                </div>
              </div>
            </div>
          ))}
          <div className="obs-axis"><span>t₀ 提交想法</span><span>R1 发布</span><span>计划登记</span><span>运行完成</span><span>现在</span></div>
        </div>
      </section>

      <div className="grid-2">
        <section className="card">
          <div className="card-head">
            <div>
              <h3>模型调用工件</h3>
              <p>每次调用都是一条带哈希的工件：run / attempt / node、input_hash、output_hash、usage、latency。</p>
            </div>
            <span className="badge purple"><i />schema 占位</span>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>角色</th><th>节点</th><th>input_hash</th><th>usage</th><th>latency</th><th>status</th></tr>
              </thead>
              <tbody>
                {(callsPlaceholder.length ? callsPlaceholder : ['—']).map((role, index) => (
                  <tr key={`${role}-${index}`}>
                    <td>{role}</td>
                    <td className="mono">—</td>
                    <td className="mono">—</td>
                    <td className="mono">—</td>
                    <td className="mono">—</td>
                    <td><span className="badge neutral">待接入</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="card">
          <div className="card-head">
            <div>
              <h3>事后回溯</h3>
              <p>技术级重放比对、因果级"产物 → 调用 → 输入版本"、业务级热点排名。</p>
            </div>
          </div>
          <div className="grid-auto" style={{ gridTemplateColumns: '1fr' }}>
            <div className="placeholder">
              <span className="todo">技术级</span>
              <b>事件回放与断点恢复</b>
              已有：编排页「回放校验 / 断点恢复」。待做：在观测视图里以时间轴形式呈现重放差异。
            </div>
            <div className="placeholder">
              <span className="todo">因果级</span>
              <b>结论 → 模型调用 → 输入版本</b>
              任何产物都能通过 output_hash 反查产生它的调用，再通过 input_hash 反查它读的输入版本。
            </div>
            <div className="placeholder">
              <span className="todo">业务级</span>
              <b>耗时排名 / 重试热点 / 缺陷来源</b>
              跨运行横向对比：同一规格不同计划的差异、失败集中在哪些任务。
            </div>
          </div>
          <div className="btn-row" style={{ marginTop: 12 }}>
            <button type="button" className="btn" disabled>回放校验</button>
            <button type="button" className="btn" disabled>对比两次运行</button>
            <button type="button" className="btn" disabled>导出复盘报告</button>
          </div>
        </section>
      </div>

      <section className="card card-pad">
        <div className="card-head" style={{ marginBottom: 10 }}>
          <h3>任务状态分布</h3>
          <span className="badge neutral">按当前快照</span>
        </div>
        <div className="legend" style={{ border: 'none', padding: 0 }}>
          {Array.from(new Set(tasks.map((task) => task.status))).map((status) => (
            <span className="legend-item" key={status}>
              <i style={{ background: statusColors[status as keyof typeof statusColors] }} />
              {status} · {tasks.filter((task) => task.status === status).length}
            </span>
          ))}
        </div>
      </section>
    </>
  );
}
