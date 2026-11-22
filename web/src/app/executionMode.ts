/** Task execution mode. `agent` is the existing Playwright runner. */

export const EXECUTION_MODE_OPTIONS = [
  { value: "agent", label: "AI 执行（Playwright）" },
  { value: "browser_use", label: "AI 执行（Browser Use）" },
  { value: "automation", label: "自动化用例" },
  { value: "human", label: "人工执行" },
] as const;

export const EXECUTION_MODE_LABEL: Record<string, string> = Object.fromEntries(
  EXECUTION_MODE_OPTIONS.map((item) => [item.value, item.label]),
);

export const BROWSER_USE_HINT = "Browser Use 尚未接入，选择后不会执行。";
