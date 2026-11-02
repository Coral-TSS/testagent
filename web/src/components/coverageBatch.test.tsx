import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { AiProposal, CaseRow, Coverage, TestCase } from "../api/types";
import { parentPath } from "../app/Layout";
import { mockFetch, renderPage } from "../test/utils";
import { ProposalDiff } from "./AiCompletion";
import { RefLinks } from "./AgentRunDrawer";
import { CaseList } from "./CaseList";
import { CaseCoverageTags, coverageSummary, CoverageDetail } from "./CoverageDetail";

const coverage: Coverage = {
  version_id: "v1",
  sut_id: "s1",
  cases: 2,
  requirements: { total: 1, covered: 1, uncovered: [], items: [{ id: "r1", code: "REQ-001", title: "Approve", cases: 1, case_list: [{ id: "c1", code: "TC-001", title: "Large amount" }] }] },
  actions: {
    total: 2,
    covered: 1,
    uncovered: [{ id: "a2", name: "Export purchase orders" }],
    items: [
      { id: "a1", name: "Approve purchase order", cases: 1, case_list: [{ id: "c1", code: "TC-001", title: "Large amount" }] },
      { id: "a2", name: "Export purchase orders", cases: 0, case_list: [] },
    ],
  },
  fields: { total: 1, covered: 1, uncovered: [], items: [{ id: "f1", name: "PurchaseOrder.amount", node_id: "n1", cases: 1, case_list: [{ id: "c2", code: "TC-002", title: "Amount" }] }] },
  relations: { total: 1, covered: 0, uncovered: [{ id: "l1", name: "PurchaseOrder belongs to Supplier" }], items: [{ id: "l1", name: "PurchaseOrder belongs to Supplier", cases: 0, case_list: [] }] },
  by_priority: {},
  by_type: {},
  by_scenario: {},
};

describe("coverage detail", () => {
  it("lists each action / field / relation with the covering cases", () => {
    renderPage(<CoverageDetail coverage={coverage} />);
    fireEvent.click(screen.getByText("Action coverage detail 1/2"));
    expect(screen.getByRole("link", { name: "Approve purchase order" }).getAttribute("href")).toBe("/suts/s1/model?node=a1");
    expect(screen.getByRole("link", { name: "TC-001" }).getAttribute("href")).toBe("/cases/c1");
    expect(screen.getByText("Not covered")).toBeTruthy();
    fireEvent.click(screen.getByText("Field coverage detail 1/1"));
    expect(screen.getByRole("link", { name: "PurchaseOrder.amount" }).getAttribute("href")).toBe("/suts/s1/model?node=n1");
    expect(screen.getByText("Link coverage detail 0/1")).toBeTruthy();
  });

  it("summarises and lists one case's coverage", () => {
    const c = { actions: [{ id: "a1", name: "Approve purchase order" }], entities: [], fields: [{ id: "f1", name: "PurchaseOrder.amount", node_id: "n1" }], relations: [{ id: "l1", name: "PurchaseOrder belongs to Supplier" }] };
    expect(coverageSummary(c)).toBe("Actions 1 · Fields 1 · Links 1");
    expect(coverageSummary(undefined)).toBe("-");
    renderPage(<CaseCoverageTags coverage={c} sutId="s1" />);
    expect(screen.getByText("Actions (1):")).toBeTruthy();
    expect(screen.getByRole("link", { name: "PurchaseOrder belongs to Supplier" }).getAttribute("href")).toBe("/suts/s1/model?view=links");
  });
});

describe("back button", () => {
  it("falls back to the parent crumb", () => {
    expect(parentPath("/cases/c1", [{ path: "/suts/s1" }, { path: "/versions/v1" }, { path: "/cases/c1" }])).toBe("/versions/v1");
    expect(parentPath("/suts/s1/model", [{ path: "/suts/s1" }])).toBe("/suts/s1");
    expect(parentPath("/agent/runs", [])).toBe("/agent");
    expect(parentPath("/defects", [])).toBe("/suts");
  });
});

describe("log refs", () => {
  it("renders resolved subjects as links", () => {
    renderPage(<RefLinks refs={[{ id: "c1", kind: "Case", label: "Large-amount approval (TC-001)", path: "/cases/c1" }, { id: "s1", kind: "SUT", label: "Procurement approval (PROC)", path: "/suts/s1" }]} max={1} />);
    expect(screen.getByRole("link", { name: "Large-amount approval (TC-001)" }).getAttribute("href")).toBe("/cases/c1");
    expect(screen.getByText("+1")).toBeTruthy();
  });
});

const tc = {
  id: "c1",
  code: "TC-016",
  title: "Manual case",
  revision: 1,
  status: "draft",
  steps: [{ action: "Approve" }],
  test_data: null,
  expected: null,
  test_point: null,
  preconditions: null,
  requirements: [],
  nodes: [],
  fields: [],
  tasks: [],
} as unknown as TestCase;
const proposal: AiProposal = {
  agent_run_id: "run1",
  created_at: "2026-11-02T10:00:00Z",
  base_revision: 1,
  rationale: "Completed based on REQ-001",
  fields: {
    test_point: "Amount boundary",
    steps: [{ action: "Approve" }],
    test_data: { amount: 20000 },
    expected: "Escalate to second-level approval",
    requirement_ids: ["r1"],
    node_ids: [],
  },
  labels: { r1: "REQ-001 Approve purchase order" },
};

describe("AI completion diff", () => {
  it("pre-selects changed fields and accepts the picked ones", async () => {
    const onAccept = vi.fn();
    renderPage(<ProposalDiff tc={tc} proposal={proposal} onAccept={onAccept} onReject={() => {}} />);
    expect(screen.getByText("Completed based on REQ-001")).toBeTruthy();
    expect(screen.getByText("+ REQ-001 Approve purchase order")).toBeTruthy();
    // steps and node_ids unchanged → not selectable
    expect((screen.getByLabelText("Accept Steps") as HTMLInputElement).disabled).toBe(true);
    fireEvent.click(screen.getByLabelText("Accept Test point"));
    fireEvent.click(screen.getByRole("button", { name: /Accept selected \(3\)/ }));
    fireEvent.click(await screen.findByRole("button", { name: /OK/ }));
    expect(onAccept).toHaveBeenCalledWith(["test_data", "expected", "requirement_ids"]);
  });
});

describe("batch on the case list", () => {
  it("sets selected cases back to draft through one batch call", async () => {
    const rows: CaseRow[] = [
      { id: "c1", code: "TC-001", title: "A", priority: "P1", type_tag: "functional", mode: "manual", status: "ready", source: "human", revision: 1, requirement_codes: [], node_count: 0, coverage: { actions: [{ id: "a1", name: "Approve purchase order" }], entities: [], fields: [], relations: [] } },
      { id: "c2", code: "TC-002", title: "B", priority: "P1", type_tag: "functional", mode: "manual", status: "ready", source: "human", revision: 1, requirement_codes: [], node_count: 0 },
    ];
    const calls = mockFetch({
      "GET /suts/s1/cases": () => ({ body: rows }),
      "GET /suts/s1/environments": () => ({ body: [] }),
      "POST /cases/batch": () => ({ body: { action: "draft", ok: [{ id: "c1", code: "TC-001" }, { id: "c2", code: "TC-002" }], skipped: [], failed: [], queued: 0 } }),
    });
    renderPage(<CaseList sutId="s1" />);
    await screen.findByText("TC-001");
    expect(screen.getByTestId("coverage-TC-001").textContent).toBe("Actions 1");
    const checks = screen.getAllByRole("checkbox");
    fireEvent.click(checks[0]); // select all
    const bar = await screen.findByTestId("batch-bar");
    expect(within(bar).getByText("Selected 2 case(s):")).toBeTruthy();
    fireEvent.click(within(bar).getByRole("button", { name: "Set draft" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/cases/batch")).toBe(true));
    const call = calls.find((c) => c.path === "/cases/batch")!;
    expect(call.body).toMatchObject({ case_ids: ["c1", "c2"], action: "draft" });
    expect(await screen.findByText("Set draft: succeeded 2")).toBeTruthy();
  });
});
