/**
 * 设计规格基线相关纯函数（从 BaselineCard 拆出）。
 *
 * 基线 = baseline_id / project_id / revision / parent_baseline_id / r1_version / design_spec / sha256 / confirmed_by / generation_source。
 * 当前后端 design spec 只带 phase1_source（run_id / r1_version / generation_source / confirmed_by），
 * 因此 revision / parent / sha256 先显示为"待后端补齐"的占位，不伪造值。
 */

export interface BaselineFacts {
  baselineId?: string;
  projectId?: string;
  revision?: number;
  parentId?: string;
  r1Version?: string;
  sha256?: string;
  confirmedBy: string[];
  generationSource: string;
}

/** 现阶段从 design spec 的 phase1_source 推导可展示的事实；其余字段留空。 */
export function factsFromDesignSpec(spec: Record<string, unknown> | null): BaselineFacts | null {
  if (!spec) return null;
  const source = (spec.phase1_source ?? {}) as Record<string, unknown>;
  return {
    baselineId: typeof source.run_id === 'string' ? source.run_id : undefined,
    r1Version: typeof source.r1_version === 'string' ? source.r1_version : undefined,
    confirmedBy: Array.isArray(source.confirmed_by) ? (source.confirmed_by as string[]) : [],
    generationSource: typeof source.generation_source === 'string' ? source.generation_source : 'unknown',
  };
}
