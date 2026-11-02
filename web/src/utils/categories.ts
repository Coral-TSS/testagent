import type { CaseCategory, TaskSelector } from "../api/types";

/** Case categories; task kinds use the same values. Input validation is requirement. */
export const CATEGORY_LABEL: Record<CaseCategory, string> = { requirement: "Requirement validation", quality: "General quality", regression: "Regression smoke" };
export const KIND_LABEL: Record<CaseCategory, string> = { requirement: "Requirement validation", quality: "General quality", regression: "Regression/smoke" };
export const CATEGORY_COLOR: Record<CaseCategory, string> = { requirement: "blue", quality: "purple", regression: "gold" };
export const CATEGORY_HINT: Record<CaseCategory, string> = {
  requirement: "Business rules in the requirement: normal, boundary, exception and input validation/error codes",
  quality: "Properties every system should have: idempotency, concurrency/duplicate submission, repeatability and data reset",
  regression: "Main-path smoke and regression guard",
};
export const QUALITY_TAGS: Record<string, string> = {
  idempotency: "Idempotency",
  concurrency: "Concurrency",
  repeatability: "Repeatability",
  data_reset: "Data reset",
  isolation: "Data isolation",
  contract: "API contract",
};
export const SCENARIO_LABEL: Record<string, string> = { normal: "Normal", boundary: "Boundary", exception: "Exception" };

export const categoryOptions = (Object.keys(CATEGORY_LABEL) as CaseCategory[]).map((value) => ({ value, label: CATEGORY_LABEL[value], title: CATEGORY_HINT[value] }));
export const qualityTagOptions = Object.entries(QUALITY_TAGS).map(([value, label]) => ({ value, label: `${label} (${value})` }));

/** A one-line description of a task rule. */
export function describeSelector(sel: TaskSelector | null | undefined, reqCode: (id: string) => string = (id) => id): string {
  if (!sel) return "No rule: only manually added cases";
  const parts: string[] = [];
  if (sel.requirement_ids?.length) parts.push(`Requirement ${sel.requirement_ids.map(reqCode).join(", ")}`);
  if (sel.categories?.length) parts.push(`Category ${sel.categories.map((c) => CATEGORY_LABEL[c]).join(", ")}`);
  if (sel.priorities?.length) parts.push(`Priority ${sel.priorities.join(", ")}`);
  if (sel.scenarios?.length) parts.push(`Scenario ${sel.scenarios.map((s) => SCENARIO_LABEL[s] || s).join(", ")}`);
  if (sel.type_tags?.length) parts.push(`Type ${sel.type_tags.join(", ")}`);
  if (sel.quality_tags?.length) parts.push(`Quality ${sel.quality_tags.map((t) => QUALITY_TAGS[t] || t).join(", ")}`);
  return parts.length ? `Among ready cases: ${parts.join("; ")}` : "All ready cases";
}

/** Drops empty lists so the API stores a minimal rule. */
export function cleanSelector(v: TaskSelector): TaskSelector {
  return Object.fromEntries(Object.entries(v).filter(([, list]) => Array.isArray(list) && list.length > 0)) as TaskSelector;
}
