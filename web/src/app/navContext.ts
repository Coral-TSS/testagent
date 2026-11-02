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
  model: "Model",
  review: "Model review",
  apis: "API registry",
  versions: "Version",
  cases: "Case library",
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
  cases: "Test cases",
  executions: "Execution",
  reports: "Report",
  defects: "Defect",
};
const VERSION_TABS: Record<string, string> = {
  suggestions: "Model suggestions",
  cases: "Test cases & coverage",
  strategy: "Test strategy & tasks",
  history: "Change log",
};

export function routeObject(pathname: string, search: string): RouteObject {
  const q = new URLSearchParams(search);
  const parts = pathname.split("/").filter(Boolean);
  const sutQ = q.get("sut_id") || q.get("sut") || undefined;
  const versionQ = q.get("version_id") || undefined;
  if (parts[0] === "suts" && parts[1]) {
    return { kind: "sut", id: parts[1], page: SUT_PAGES[parts[2] || ""], sutId: parts[1], versionId: versionQ };
  }
  if (parts.length === 2 && DETAIL[parts[0]]) {
    if (parts[0] === "versions") {
      const req = q.get("req");
      if (req) return { kind: "requirement", id: req };
      return { kind: "version", id: parts[1], page: VERSION_TABS[q.get("tab") || ""] };
    }
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
  if (path === "/cases") {
    if (sutId) q.set("sut", sutId);
  } else {
    if (sutId) q.set("sut_id", sutId);
    if (versionId) q.set("version_id", versionId);
  }
  const s = q.toString();
  return s ? `${path}?${s}` : path;
}
