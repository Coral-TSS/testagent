import { fireEvent, screen, waitFor } from "@testing-library/react";

import { CasePage } from "../pages/CasePage";
import { ReportPage } from "../pages/ReportPage";
import { TaskPage } from "../pages/TaskPage";
import { mockFetch, renderPage } from "../test/utils";
import { cleanSelector, describeSelector } from "../utils/categories";
import { StrategyTab } from "./StrategyTab";

afterEach(() => vi.unstubAllGlobals());

const version = { id: "v1", sut_id: "s1", name: "V1.0", status: "frozen" } as never;
const reqs = [
  { id: "r1", code: "REQ-001", title: "Create purchase order" },
  { id: "r2", code: "REQ-002", title: "Payments" },
];

describe("task–case binding", () => {
  it("describes rules in words and drops empty lists", () => {
    expect(describeSelector({ requirement_ids: ["r1"], categories: ["requirement"] }, (id) => (id === "r1" ? "REQ-001" : id))).toBe(
      "Among ready cases: Requirement REQ-001; Category Requirement validation",
    );
    expect(describeSelector(null)).toBe("No rule: only manually added cases");
    expect(cleanSelector({ categories: ["quality"], priorities: [], requirement_ids: undefined })).toEqual({ categories: ["quality"] });
  });

  it("task page shows rule/manual sources with reasons, and restores a removed case", async () => {
    const task = {
      id: "t1",
      name: "Requirement validation: REQ-001 Create purchase order",
      kind: "requirement",
      executor: "agent",
      status: "ready",
      version_id: "v1",
      sut_id: "s1",
      selector: { requirement_ids: ["r1"], categories: ["requirement"] },
      cases: [
        { seq: 1, id: "c1", code: "TC-001", title: "Large-amount approval", status: "ready", mode: "automated", type_tag: "functional", category: "requirement", source: "manual", reason: "Added manually" },
        { seq: 2, id: "c2", code: "TC-002", title: "Threshold", status: "ready", mode: "manual", type_tag: "functional", category: "requirement", source: "rule", reason: "Case became ready, added automatically (rule match: requirement REQ-001 · Requirement validation)" },
      ],
      exclusions: [{ case_id: "c3", code: "TC-003", title: "Idempotency", removed_by: "local-user", created_at: "2026-11-02T15:00:00+08:00" }],
      rule_stats: { rule: 1, manual: 1, excluded: 1 },
    };
    const calls = mockFetch({
      "GET /tasks/t1": () => ({ body: task }),
      "GET /tasks/t1/runs": () => ({ body: [] }),
      "GET /suts/s1/environments": () => ({ body: [] }),
      "GET /suts/s1/cases": () => ({ body: [] }),
      "GET /settings/general": () => ({ body: { timezone: "Asia/Shanghai" } }),
      "GET /versions/v1/requirements": () => ({ body: reqs }),
      "DELETE /tasks/t1/exclusions/c3": () => ({ body: { ...task, exclusions: [] } }),
      "POST /tasks/t1/selector/preview": () => ({
        body: { cases: [{ id: "c2", code: "TC-002", title: "Threshold", category: "requirement", reason: "Rule match: requirement REQ-001 · Requirement validation", excluded: false }] },
      }),
    });
    renderPage(<TaskPage />, { path: "/tasks/:taskId", route: "/tasks/t1" });
    expect((await screen.findAllByText("Requirement validation", { selector: ".ant-tag" })).length).toBeGreaterThan(0);
    await waitFor(() => expect(screen.getByTestId("rule-text").textContent).toBe("Among ready cases: Requirement REQ-001; Category Requirement validation"));
    expect(screen.getByTestId("rule-stats").textContent).toContain("By rule 1 · added manually 1 · removed manually 1");
    expect(screen.getByText("Rule", { selector: ".ant-tag" })).toBeTruthy();
    expect(screen.getByText("Manual", { selector: ".ant-tag" })).toBeTruthy();
    expect(screen.getByText(/Case became ready, added automatically/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Preview matches" }));
    expect(await screen.findByText("The rule matches 1 ready case(s)")).toBeTruthy();
    const preview = calls.find((c) => c.path === "/tasks/t1/selector/preview")!;
    expect(preview.body).toEqual({ selector: { requirement_ids: ["r1"], categories: ["requirement"] } });
    fireEvent.click(screen.getByText("Restore"));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.path === "/tasks/t1/exclusions/c3")).toBe(true));
  });

  it("strategy tab lists requirement gaps, drafts cases for one, and fills missing task kinds", async () => {
    const onOpenRun = vi.fn();
    const calls = mockFetch({
      "GET /versions/v1/strategy": () => ({ status: 404, body: { code: "NOT_FOUND", message: "x" } }),
      "GET /versions/v1/tasks": () => ({
        body: [{ id: "t1", name: "General quality: idempotency, concurrency, repeatability", kind: "quality", executor: "agent", status: "draft", case_count: 1, selector: { categories: ["quality"] } }],
      }),
      "GET /suts/s1/environments": () => ({ body: [] }),
      "GET /versions/v1/requirements": () => ({ body: reqs }),
      "GET /versions/v1/gaps": () => ({ body: [{ requirement_id: "r2", code: "REQ-002", title: "Payments", ready_count: 0, draft_count: 2 }] }),
      "POST /versions/v1/cases/generate": () => ({ body: { agent_run_id: "ar1", status: "succeeded", error_code: null } }),
      "POST /versions/v1/tasks/ensure": () => ({ body: { created: [] } }),
    });
    renderPage(<StrategyTab version={version} onOpenRun={onOpenRun} />);
    expect(await screen.findByText("Payments (REQ-002)")).toBeTruthy();
    expect(screen.getByText("2 to review")).toBeTruthy();
    expect(screen.getByText("Category General quality")).toBeTruthy();
    expect(screen.getAllByText("General quality").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: /Generate draft cases/ }));
    await waitFor(() => expect(onOpenRun).toHaveBeenCalledWith("ar1"));
    expect(calls.find((c) => c.path === "/versions/v1/cases/generate")!.body).toEqual({ requirement_ids: ["r2"], automate: false });
    fireEvent.click(screen.getByRole("button", { name: "Complete tasks per category" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/versions/v1/tasks/ensure")).toBe(true));
  });

  it("case page asks a person to confirm an uncertain category", async () => {
    let current = {
      id: "c1",
      sut_id: "s1",
      code: "TC-008",
      title: "409 when approving a non-pending order again",
      priority: "P1",
      type_tag: "functional",
      category: "requirement",
      quality_tags: [],
      category_suggestion: { category: "quality", quality_tags: ["idempotency"], reason: "A repeated approval is more of an idempotency guard" },
      mode: "manual",
      status: "ready",
      source: "agent",
      revision: 1,
      origin_version_id: "v1",
      steps: [{ action: "Approve again" }],
      requirements: [],
      nodes: [],
      tasks: [],
      updated_at: "2026-11-02T10:00:00+08:00",
    };
    const calls = mockFetch({
      "GET /cases/c1": () => ({ body: current }),
      "GET /cases/c1/revisions": () => ({ body: [] }),
      "GET /versions/v1/requirements": () => ({ body: [] }),
      "GET /suts/s1/graph": () => ({ body: { nodes: [], edges: [] } }),
      "POST /cases/c1/category-suggestion": () => {
        current = { ...current, category: "quality", category_suggestion: null as never };
        return { body: current };
      },
    });
    renderPage(<CasePage />, { path: "/cases/:caseId", route: "/cases/c1" });
    const alert = await screen.findByTestId("category-suggestion");
    expect(alert.textContent).toContain("suggested change from “Requirement validation” to “General quality” (Idempotency)");
    fireEvent.click(screen.getByRole("button", { name: /Accept/ }));
    await waitFor(() => expect(calls.find((c) => c.path === "/cases/c1/category-suggestion")?.body).toEqual({ accept: true }));
    await waitFor(() => expect(screen.queryByTestId("category-suggestion")).toBeNull());
  });

  it("run report shows pass rate by case category", async () => {
    const summary = { total: 2, passed: 1, failed: 1, error: 0, blocked: 0, skipped: 0, not_executed: 0, executed: 2, pass_rate: 0.5 };
    mockFetch({
      "GET /reports/rp1": () => ({
        body: {
          id: "rp1",
          scope_type: "task_run",
          scope_id: "run1",
          ai_summary: null,
          created_by: "system",
          created_at: "2026-11-02T21:00:00+08:00",
          content: {
            scope: { type: "task_run", task_run_id: "run1", task_name: "x", version_id: "v1", version_name: "V1.0", status: "failed" },
            summary,
            by_category: [
              { category: "requirement", label: "Requirement validation", ...summary, total: 1, failed: 0, executed: 1, pass_rate: 1 },
              { category: "quality", label: "General quality", ...summary, total: 1, passed: 0, executed: 1, pass_rate: 0 },
            ],
            failures: [],
            by_requirement: [],
            by_person: [],
            defects: [],
            code_links: [],
            executed_statuses: [],
            weights_used: {},
            snapshot_id: null,
            generated_at: "2026-11-02T21:00:00+08:00",
          },
        },
      }),
    });
    renderPage(<ReportPage />, { path: "/reports/:reportId", route: "/reports/rp1" });
    const card = await screen.findByTestId("by-category");
    expect(card.textContent).toContain("Requirement validation");
    expect(card.textContent).toContain("General quality");
    expect(card.textContent).toContain("100%");
    expect(card.textContent).toContain("0%");
  });
});
