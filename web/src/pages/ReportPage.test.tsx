import { fireEvent, screen, waitFor } from "@testing-library/react";

import { mockFetch, renderPage } from "../test/utils";
import { ReportPage } from "./ReportPage";
import { ReportsPage } from "./ReportsPage";

afterEach(() => vi.unstubAllGlobals());

const summary = { total: 4, passed: 2, failed: 1, error: 0, blocked: 1, skipped: 0, not_executed: 0, pass_rate: 2 / 3 };
const report = {
  id: "rp1",
  scope_type: "task_run",
  scope_id: "run1",
  ai_summary: null,
  agent_run_id: null,
  created_by: "system",
  created_at: "2026-10-31T21:00:00+08:00",
  content: {
    scope: { type: "task_run", task_run_id: "run1", task_name: "Smoke", version_id: "v1", version_name: "1.0", status: "failed" },
    summary,
    failures: [
      {
        case: { id: "c1", code: "TC-001", title: "Amount is 0" },
        requirement_codes: ["REQ-001"],
        status: "failed",
        failed_assertion: "status == 400",
        error: null,
        execution_id: "e1",
        defect_ids: ["d1"],
      },
    ],
    by_requirement: [
      {
        requirement_id: "r1",
        version_id: "v1",
        code: "REQ-001",
        title: "Place order",
        owner: ["Pat Product"],
        developers: ["Lee Dev"],
        testers: [],
        defect_count: 2,
        weighted_score: 6,
        executed_cases: 4,
        density: 0.5,
        by_severity: { critical: 1, minor: 1 },
      },
    ],
    by_person: [
      {
        person_id: "p1",
        name: "Lee Dev",
        attributed_count: 2,
        attributed_score: 6,
        attributed_by_role: { developer: { count: 2, score: 6 } },
        related_count: 2,
        top_requirements: ["REQ-001"],
      },
    ],
    defects: [
      {
        id: "d1",
        code: "DEF-001",
        title: "Amount 0 can be submitted",
        severity: "critical",
        cause_category: "development",
        status: "open",
        requirements: ["REQ-001"],
        responsible: [{ name: "Lee Dev", role: "developer" }],
      },
    ],
    code_links: [{ requirement_code: "REQ-001", nodes: [{ name: "Order", code_ref: "order.py" }], apis: [{ method: "POST", path: "/orders", code_ref: "api.py:10" }] }],
    weights_used: { critical: 10, major: 3, minor: 1, trivial: 0.1 },
    snapshot_id: "snap1",
    generated_at: "2026-10-31T13:00:00Z",
  },
};

describe("ReportPage", () => {
  it("renders requirement density, people ranking and code links; regenerate creates a new report", async () => {
    const calls = mockFetch({
      "GET /reports/rp1": () => ({ body: report }),
      "POST /runs/run1/report": () => ({ status: 201, body: { ...report, id: "rp2" } }),
    });
    renderPage(<ReportPage />, { path: "/reports/:reportId", route: "/reports/rp1" });
    expect(await screen.findByText("REQ-001 Place order")).toBeTruthy();
    expect(screen.getByText("0.50")).toBeTruthy(); // density 2 / 4
    expect(screen.getByText("Critical 1")).toBeTruthy();
    expect(screen.getByText("Developer 2 (6)")).toBeTruthy();
    expect(screen.getByText("Lee Dev (Developer)")).toBeTruthy();
    expect(screen.getByText("POST /orders · api.py:10")).toBeTruthy();
    expect(screen.getByText("Critical 10 · Major 3 · Minor 1 · Trivial 0.1")).toBeTruthy();
    expect(screen.getByText(/No AI summary/)).toBeTruthy();
    expect(screen.getByText("66.7%")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Regenerate" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/runs/run1/report")).toBe(true));
    // no PUT/PATCH/DELETE on a report: it is immutable
    expect(calls.some((c) => c.path.startsWith("/reports/") && c.method !== "GET")).toBe(false);
  });
});

describe("ReportsPage", () => {
  it("lists task and version reports", async () => {
    mockFetch({
      "GET /suts": () => ({ body: [] }),
      "GET /reports": () => ({
        body: [
          { id: "rp1", scope_type: "task_run", scope_id: "run1", created_at: report.created_at, created_by: "system", summary, has_ai_summary: false, version_id: "v1", version_name: "1.0", task_name: "Smoke" },
          { id: "rp2", scope_type: "version", scope_id: "v1", created_at: report.created_at, created_by: "local-user", summary, has_ai_summary: true, version_id: "v1", version_name: "1.0", task_name: null },
        ],
      }),
    });
    renderPage(<ReportsPage />, { path: "/reports", route: "/reports" });
    expect(await screen.findByText("Smoke report")).toBeTruthy();
    expect(screen.getByText("Version 1.0 report")).toBeTruthy();
    expect(screen.getAllByText("66.7%")).toHaveLength(2);
  });
});
