import { withContext } from "./navContext";

/** Which menu row is current. Keys are workflow stages, not pathnames. */
export function menuSelection(pathname: string, search: string, sutId?: string): string {
  const parts = pathname.split("/").filter(Boolean);
  const q = new URLSearchParams(search);
  if (parts[0] === "suts" && !parts[1]) return "sut-list";
  if (parts[0] === "suts" && parts[1]) {
    const sub = parts[2];
    if (sub === "model") return "model-graph";
    if (sub === "review") return "model-review";
    if (sub === "apis") return "model-apis";
    if (sub === "versions") return "sut-requirements";
    if (sub === "cases") return "sut-cases";
    return "sut-overview";
  }
  if (parts[0] === "versions" && parts[1]) {
    if (parts[2] === "model") return "model-graph";
    if (parts[2] === "review") return "model-review";
    if (parts[2] === "apis") return "model-apis";
    if (parts[2] === "strategy" || q.get("tab") === "strategy") return "sut-strategy";
    if (parts[2] === "tasks" || q.get("tab") === "tasks") return "sut-tasks";
    if (q.get("tab") === "cases") return "sut-cases";
    return "sut-requirements";
  }
  if (parts[0] === "tasks") return "sut-tasks";
  if (parts[0] === "cases") return "sut-cases";
  if (parts[0] === "executions" || parts[0] === "runs") {
    const scoped = Boolean(q.get("sut_id")) || (parts.length > 1 && Boolean(sutId));
    return scoped ? "sut-executions" : "global-executions";
  }
  if (parts[0] === "defects") {
    const scoped = Boolean(q.get("sut_id")) || (parts.length > 1 && Boolean(sutId));
    return scoped ? "sut-defects" : "global-defects";
  }
  if (parts[0] === "reports") return "global-reports";
  if (pathname === "/persons") return "persons";
  if (pathname === "/stats/people") return "people-stats";
  if (pathname === "/agent/config") return "agent-config";
  if (pathname === "/agent/runs") return "agent-runs";
  if (pathname === "/agent/tools") return "agent-tools";
  if (pathname === "/users") return "users";
  return "";
}

/** Links for the current system. Version-scoped entries are empty until a version exists. */
export function sutLinks(sutId: string, versionId?: string) {
  const versionQuery = versionId ? `?version_id=${versionId}` : "";
  return {
    overview: `/suts/${sutId}`,
    requirements: versionId ? `/versions/${versionId}` : "",
    strategy: versionId ? `/versions/${versionId}/strategy` : "",
    tasks: versionId ? `/versions/${versionId}/tasks` : "",
    cases: `/suts/${sutId}/cases${versionQuery}`,
    executions: withContext("/executions", sutId, versionId),
    defects: withContext("/defects", sutId, versionId),
    reports: withContext("/reports", sutId, versionId),
    model: versionId ? `/versions/${versionId}/model` : "",
    review: versionId ? `/versions/${versionId}/review` : "",
    apis: versionId ? `/versions/${versionId}/apis` : "",
    versions: `/suts/${sutId}/versions`,
  };
}

/** Stay on the same kind of page when the current system changes. Version ids do not carry over. */
export function switchSutTarget(pathname: string, search: string, nextSut: string): string {
  const parts = pathname.split("/").filter(Boolean);
  if (parts[0] === "versions") return `/suts/${nextSut}`;
  if (parts[0] === "suts" && parts[1]) {
    const sub = parts[2];
    if (sub === "model" || sub === "review" || sub === "apis" || sub === "versions") return `/suts/${nextSut}`;
    const rest = parts.slice(2).join("/");
    const q = new URLSearchParams(search);
    q.delete("version_id");
    const s = q.toString();
    return `/suts/${nextSut}${rest ? `/${rest}` : ""}${s ? `?${s}` : ""}`;
  }
  if ((parts[0] === "executions" || parts[0] === "defects" || parts[0] === "reports") && parts.length === 1) {
    const q = new URLSearchParams(search);
    q.set("sut_id", nextSut);
    q.delete("version_id");
    return `/${parts[0]}?${q.toString()}`;
  }
  return `/suts/${nextSut}`;
}

/** Stay on the same version section (requirements, strategy, tasks) or keep a list filter. */
export function switchVersionTarget(pathname: string, search: string, versionId: string, sutId?: string): string {
  const legacyModel = pathname.match(/^\/suts\/[^/]+\/(model|review|apis)$/);
  if (legacyModel) {
    const q = new URLSearchParams(search);
    q.delete("version_id");
    const s = q.toString();
    return `/versions/${versionId}/${legacyModel[1]}${s ? `?${s}` : ""}`;
  }
  const section = pathname.match(/^\/versions\/[^/]+(\/(strategy|tasks|model|review|apis))?$/);
  if (section) {
    const q = new URLSearchParams(search);
    q.delete("tab");
    const s = q.toString();
    return `/versions/${versionId}${section[1] || ""}${s ? `?${s}` : ""}`;
  }
  const list = pathname.startsWith("/suts/") || pathname === "/defects" || pathname === "/reports" || pathname === "/executions";
  if (list) {
    const q = new URLSearchParams(search);
    q.set("version_id", versionId);
    if ((pathname === "/defects" || pathname === "/reports" || pathname === "/executions") && sutId) q.set("sut_id", sutId);
    return `${pathname}?${q.toString()}`;
  }
  return `/versions/${versionId}`;
}
