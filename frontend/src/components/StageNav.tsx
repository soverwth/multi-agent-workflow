/**
 * 工作台侧边栏导航：按三个阶段分组。
 *
 * 只是界面叙事层，不改变后端流程；各页面内容由 App 决定。
 */

import { STAGE_GROUPS, type StageKey } from '../constants/stages';

interface Props {
  value: StageKey;
  onChange: (stage: StageKey) => void;
  /** 已完成的页面（由 App 根据运行状态推断），用于显示绿色完成态。 */
  doneKeys?: Set<StageKey>;
}

export function StageNav({ value, onChange, doneKeys }: Props) {
  return (
    <nav className="sidebar" aria-label="工作台页面导航">
      {STAGE_GROUPS.map((group) => (
        <div className="sidebar-section" data-phase={group.phase} key={group.phase}>
          <div className="sidebar-section-title">
            <i aria-hidden="true" />
            {group.title}
          </div>
          {group.items.map((stage) => {
            const active = stage.key === value;
            const done = !active && Boolean(doneKeys?.has(stage.key));
            return (
              <button
                type="button"
                key={stage.key}
                className={`stage-item${active ? ' active' : ''}${done ? ' done' : ''}`}
                aria-current={active ? 'page' : undefined}
                onClick={() => onChange(stage.key)}
              >
                <span className="stage-no">{stage.no}</span>
                <span className="stage-text">
                  <b>{stage.label}</b>
                  <small>{stage.hint}</small>
                </span>
              </button>
            );
          })}
        </div>
      ))}
      <div className="sidebar-foot">
        单端口单网页 · 全程无审批门
        <br />
        用户随时插话，流程不因等待而暂停
      </div>
    </nav>
  );
}
