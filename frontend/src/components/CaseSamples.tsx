import { useState } from 'react';
import type { DataSource } from '../types/task';

/**
 * T06—T08 案例前端适配样例（B05 交付要求）
 * 展示 InterfaceAgent 如何把 C1 契约字段映射为真实页面，
 * 并明确标注为模拟数据，与真实接口结果区分。
 */

interface LostItem {
  id: string;
  name: string;
  description: string;
  location: string;
  lost_at: string;
  status: 'waiting';
  created_at: string;
}

/** 与 C1 LostView 对齐的模拟数据（不含 publisher_id / 联系方式） */
const sampleItems: LostItem[] = [
  {
    id: '3f2a9c11-0001-4a2b-9c10-1a2b3c4d5e6f',
    name: '校园卡',
    description: '蓝色卡套，姓名可见，遗失于教学楼附近',
    location: '第三教学楼 302',
    lost_at: '2026-11-16T10:30:00+08:00',
    status: 'waiting',
    created_at: '2026-11-16T10:45:00+08:00',
  },
  {
    id: '3f2a9c11-0002-4a2b-9c10-1a2b3c4d5e6f',
    name: '耳机',
    description: '白色入耳式耳机，带充电盒',
    location: '图书馆 2 楼阅览区',
    lost_at: '2026-11-15T16:05:00+08:00',
    status: 'waiting',
    created_at: '2026-11-15T16:20:00+08:00',
  },
  {
    id: '3f2a9c11-0003-4a2b-9c10-1a2b3c4d5e6f',
    name: '高等数学教材',
    description: '封面有笔记，第 7 版',
    location: '食堂一楼',
    lost_at: '2026-11-14T12:15:00+08:00',
    status: 'waiting',
    created_at: '2026-11-14T12:40:00+08:00',
  },
];

const field = (label: string, required: boolean) => (
  <div style={{ marginBottom: 12 }}>
    <div style={{ fontSize: 12, color: '#475569', marginBottom: 4 }}>
      {label} {required && <span style={{ color: '#dc2626' }}>*</span>}
    </div>
    <input
      style={{ width: '100%', boxSizing: 'border-box', padding: '8px 10px', border: '1px solid #cbd5e1', borderRadius: 6, fontSize: 13 }}
      placeholder={`请输入${label}`}
      disabled
    />
  </div>
);

export function CaseSamples({ source }: { source: DataSource }) {
  const [tab, setTab] = useState<'T06' | 'T07' | 'T08'>('T06');
  const [selected, setSelected] = useState<LostItem>(sampleItems[0]);

  const isReal = source === 'real';

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: '#f8fafc', overflow: 'hidden' }}>
      {/* 顶部标注：模拟/真实明确区分 */}
      <div style={{
        padding: '10px 16px',
        background: isReal ? '#ecfdf5' : '#fffbeb',
        borderBottom: `1px solid ${isReal ? '#a7f3d0' : '#fde68a'}`,
        fontSize: 12,
        color: isReal ? '#065f46' : '#92400e',
      }}>
        {isReal
          ? '● 真实接口样例：数据来自 C1 契约约定的 /api/v1 实际响应结构'
          : '● 模拟数据样例：用于演示界面字段映射，非真实接口结果'}
      </div>

      <div style={{ display: 'flex', gap: 4, padding: '12px 16px 0' }}>
        {([['T06', '发布表单'], ['T07', '搜索列表'], ['T08', '详情与认领']] as const).map(([id, label]) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            style={{
              padding: '8px 16px', border: '1px solid #e2e8f0', borderBottom: 'none',
              borderRadius: '8px 8px 0 0', cursor: 'pointer', fontSize: 13,
              background: tab === id ? '#fff' : '#f1f5f9',
              color: tab === id ? '#0f172a' : '#64748b',
              fontWeight: tab === id ? 600 : 400,
            }}
          >
            {id} {label}
          </button>
        ))}
      </div>

      <div style={{ flex: 1, margin: '0 16px 16px', background: '#fff', border: '1px solid #e2e8f0', borderRadius: '0 8px 8px 8px', overflow: 'auto', padding: 20 }}>
        {tab === 'T06' && (
          <div style={{ maxWidth: 520 }}>
            <h3 style={{ margin: '0 0 6px', color: '#0f172a' }}>发布失物</h3>
            <p style={{ margin: '0 0 18px', fontSize: 12, color: '#64748b' }}>
              字段与 C1 对齐：name 1—80、description 1—1000、location 1—120、lost_at 必填且带时区（ISO 8601）。
            </p>
            {field('物品名称', true)}
            {field('描述', true)}
            {field('丢失地点', true)}
            {field('丢失时间（ISO 8601，必填）', true)}
            <div style={{ padding: 10, background: '#f1f5f9', borderRadius: 6, fontSize: 12, color: '#475569' }}>
              提示映射：REQUIRED_FIELD → “请填写丢失时间”，INVALID_FIELD → 字段级红色提示（对齐文档 6.4 FE-01 行为）。
            </div>
            <button style={{ marginTop: 16, padding: '9px 18px', background: '#2563eb', color: '#fff', border: 'none', borderRadius: 6, fontSize: 13, cursor: 'not-allowed', opacity: 0.7 }} disabled>
              提交（样例禁用）
            </button>
          </div>
        )}

        {tab === 'T07' && (
          <div>
            <h3 style={{ margin: '0 0 6px', color: '#0f172a' }}>失物搜索列表</h3>
            <p style={{ margin: '0 0 16px', fontSize: 12, color: '#64748b' }}>
              keyword / location 可省略，空串等同未提供；展示 LostView，不返回 publisher_id。
            </p>
            <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
              <input placeholder="关键词（name/description 包含匹配）" style={{ flex: 1, padding: 8, border: '1px solid #cbd5e1', borderRadius: 6, fontSize: 13 }} disabled />
              <input placeholder="地点" style={{ width: 180, padding: 8, border: '1px solid #cbd5e1', borderRadius: 6, fontSize: 13 }} disabled />
            </div>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ background: '#f1f5f9', textAlign: 'left' }}>
                  {['名称', '地点', '丢失时间', '状态'].map((h) => (
                    <th key={h} style={{ padding: '8px 10px', borderBottom: '1px solid #e2e8f0', color: '#475569' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sampleItems.map((item) => (
                  <tr
                    key={item.id}
                    onClick={() => { setSelected(item); setTab('T08'); }}
                    style={{ cursor: 'pointer', borderBottom: '1px solid #f1f5f9' }}
                  >
                    <td style={{ padding: '8px 10px', color: '#0f172a' }}>{item.name}</td>
                    <td style={{ padding: '8px 10px', color: '#475569' }}>{item.location}</td>
                    <td style={{ padding: '8px 10px', color: '#64748b' }}>{item.lost_at}</td>
                    <td style={{ padding: '8px 10px', color: '#15803d' }}>{item.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {tab === 'T08' && (
          <div style={{ maxWidth: 560 }}>
            <h3 style={{ margin: '0 0 16px', color: '#0f172a' }}>失物详情与认领入口</h3>
            <div style={{ display: 'grid', gridTemplateColumns: '120px 1fr', gap: '10px 12px', fontSize: 13, marginBottom: 20 }}>
              <span style={{ color: '#64748b' }}>ID</span>
              <span style={{ fontFamily: 'monospace', color: '#334155', wordBreak: 'break-all' }}>{selected.id}</span>
              <span style={{ color: '#64748b' }}>名称</span><span style={{ color: '#0f172a' }}>{selected.name}</span>
              <span style={{ color: '#64748b' }}>描述</span><span style={{ color: '#334155' }}>{selected.description}</span>
              <span style={{ color: '#64748b' }}>地点</span><span style={{ color: '#334155' }}>{selected.location}</span>
              <span style={{ color: '#64748b' }}>丢失时间</span><span style={{ color: '#334155' }}>{selected.lost_at}</span>
            </div>
            <div style={{ padding: 12, border: '1px dashed #cbd5e1', borderRadius: 8 }}>
              <div style={{ fontSize: 12, color: '#475569', marginBottom: 6 }}>认领说明（create_claim.body 仅含 statement，1—500 字符）</div>
              <textarea placeholder="请填写认领说明" style={{ width: '100%', boxSizing: 'border-box', minHeight: 70, padding: 8, border: '1px solid #cbd5e1', borderRadius: 6, fontSize: 13 }} disabled />
              <button style={{ marginTop: 8, padding: '8px 16px', background: '#16a34a', color: '#fff', border: 'none', borderRadius: 6, fontSize: 13, cursor: 'not-allowed', opacity: 0.7 }} disabled>提交认领（样例禁用）</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
