import type { NavKind } from "../api/types";

/** Which object a page shows, and the extra crumb for SUT sub-pages / version tabs. */
export interface RouteObject {
  kind?: NavKind;
  id?: string;
  page?: string;
  /** current SUT / version carried in the query string of list pages */
  sutId?: string;
  versionId?: string;
}

const SUT_PAGES: Record<string, string> = {
  model: "模型图谱",
  review: "模型评审",
  apis: "API 注册表",
  versions: "版本与需求",
  cases: "用例",
};
const DETAIL: Record<string, NavKind> = {
  versions: "version",
  tasks: "task",
  runs: "run",
  cases: "case",
  executions: "execution",
  defects: "defect",
  reports: "report",
};
const LIST_PAGES: Record<string, string> = {
  executions: "执行",
  reports: "测试报告",
  defects: "缺陷",
};
const VERSION_TABS: Record<string, string> = {
  suggestions: "模型建议",
  cases: "用例",
  strategy: "策略",
  tasks: "任务",
  history: "变更日志",
};
const VERSION_SECTIONS: Record<string, string> = {
  strategy: "策略",
  tasks: "任务",
};

export function routeObject(pathname: string, search: string): RouteObject {
  const q = new URLSearchParams(search);
  const parts = pathname.split("/").filter(Boolean);
  const sutQ = q.get("sut_id") || q.get("sut") || undefined;
  const versionQ = q.get("version_id") || undefined;
  if (parts[0] === "suts" && parts[1]) {
    return { kind: "sut", id: parts[1], page: SUT_PAGES[parts[2] || ""], sutId: parts[1], versionId: versionQ };
  }
  if (parts[0] === "versions" && parts[1]) {
    const section = VERSION_SECTIONS[parts[2] || ""];
    if (section && !q.get("req")) return { kind: "version", id: parts[1], page: section };
    const req = q.get("req");
    if (req) return { kind: "requirement", id: req };
    return { kind: "version", id: parts[1], page: VERSION_TABS[q.get("tab") || ""] };
  }
  if (parts.length === 2 && DETAIL[parts[0]]) {
    return { kind: DETAIL[parts[0]], id: parts[1] };
  }
  if (parts.length === 1 && LIST_PAGES[parts[0]]) {
    if (versionQ) return { kind: "version", id: versionQ, page: LIST_PAGES[parts[0]], sutId: sutQ, versionId: versionQ };
    if (sutQ) return { kind: "sut", id: sutQ, page: LIST_PAGES[parts[0]], sutId: sutQ };
    return { page: LIST_PAGES[parts[0]] };
  }
  return {};
}

/** Global pages keep the current SUT / version in their query string. */
export function withContext(path: string, sutId?: string, versionId?: string): string {
  const q = new URLSearchParams();
  if (sutId) q.set("sut_id", sutId);
  if (versionId) q.set("version_id", versionId);
  const s = q.toString();
  return s ? `${path}?${s}` : path;
}
