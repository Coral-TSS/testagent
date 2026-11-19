import type { CaseCategory, TaskSelector } from "../api/types";

/** Case categories; task kinds use the same values. Input validation is requirement. */
export const CATEGORY_LABEL: Record<CaseCategory, string> = { requirement: "需求验证", quality: "通用质量", regression: "回归冒烟" };
export const KIND_LABEL: Record<CaseCategory, string> = { requirement: "需求验证", quality: "通用质量", regression: "回归/冒烟" };
export const CATEGORY_COLOR: Record<CaseCategory, string> = { requirement: "blue", quality: "purple", regression: "gold" };
export const CATEGORY_HINT: Record<CaseCategory, string> = {
  requirement: "需求中的业务规则：正常、边界、异常以及输入校验/错误码",
  quality: "每个系统都应具备的性质：幂等、并发/重复提交、可重复性与数据重置",
  regression: "主路径冒烟与回归守护",
};
export const QUALITY_TAGS: Record<string, string> = {
  idempotency: "幂等",
  concurrency: "并发",
  repeatability: "可重复性",
  data_reset: "数据重置",
  isolation: "数据隔离",
  contract: "API 契约",
};
export const SCENARIO_LABEL: Record<string, string> = { normal: "正常", boundary: "边界", exception: "异常" };

export const categoryOptions = (Object.keys(CATEGORY_LABEL) as CaseCategory[]).map((value) => ({ value, label: CATEGORY_LABEL[value], title: CATEGORY_HINT[value] }));
export const qualityTagOptions = Object.entries(QUALITY_TAGS).map(([value, label]) => ({ value, label: `${label} (${value})` }));

/** A one-line description of a task rule. */
export function describeSelector(sel: TaskSelector | null | undefined, reqCode: (id: string) => string = (id) => id): string {
  if (!sel) return "无规则：仅手工添加的用例";
  const parts: string[] = [];
  if (sel.requirement_ids?.length) parts.push(`需求 ${sel.requirement_ids.map(reqCode).join(", ")}`);
  if (sel.categories?.length) parts.push(`类别 ${sel.categories.map((c) => CATEGORY_LABEL[c]).join(", ")}`);
  if (sel.priorities?.length) parts.push(`优先级 ${sel.priorities.join(", ")}`);
  if (sel.scenarios?.length) parts.push(`场景 ${sel.scenarios.map((s) => SCENARIO_LABEL[s] || s).join(", ")}`);
  if (sel.type_tags?.length) parts.push(`类型 ${sel.type_tags.join(", ")}`);
  if (sel.quality_tags?.length) parts.push(`质量 ${sel.quality_tags.map((t) => QUALITY_TAGS[t] || t).join(", ")}`);
  return parts.length ? `在就绪用例中：${parts.join("；")}` : "全部就绪用例";
}

/** Drops empty lists so the API stores a minimal rule. */
export function cleanSelector(v: TaskSelector): TaskSelector {
  return Object.fromEntries(Object.entries(v).filter(([, list]) => Array.isArray(list) && list.length > 0)) as TaskSelector;
}
