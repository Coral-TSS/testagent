import { fireEvent, screen, waitFor } from "@testing-library/react";

import { mockFetch, renderPage } from "../test/utils";
import { CasePage } from "./CasePage";

afterEach(() => vi.unstubAllGlobals());

const base = {
  id: "c1",
  sut_id: "s1",
  code: "TC-001",
  title: "Cannot submit when the amount is 0",
  test_point: "Amount boundary",
  priority: "P1",
  type_tag: "functional",
  scenario: "boundary",
  mode: "manual",
  status: "draft",
  source: "agent",
  revision: 1,
  origin_version_id: "v1",
  steps: [{ action: "Enter amount 0 and submit", expected: "An error is shown" }],
  test_data: { amount: 0 },
  expected: "Submission refused",
  agent_run_id: "run1",
  requirements: [{ id: "r1", code: "REQ-001", title: "Create purchase order", version_id: "v1" }],
  nodes: [{ id: "n1", kind: "action", name: "Create purchase order", deleted: false }],
  tasks: [],
  updated_at: "2026-10-31T10:00:00+08:00",
};

describe("CasePage", () => {
  it("shows the case and lets a human mark it ready", async () => {
    let current = { ...base };
    const calls = mockFetch({
      "GET /cases/c1": () => ({ body: current }),
      "GET /cases/c1/revisions": () => ({ body: [{ revision: 1, content: { title: base.title }, author: "agent:run1", created_at: base.updated_at }] }),
      "GET /versions/v1/requirements": () => ({ body: [{ id: "r1", code: "REQ-001", title: "Create purchase order" }] }),
      "GET /suts/s1/graph": () => ({ body: { nodes: [], edges: [] } }),
      "POST /cases/c1/status": () => {
        current = { ...current, status: "ready" };
        return { body: current };
      },
    });
    renderPage(<CasePage />, { path: "/cases/:caseId", route: "/cases/c1" });
    expect(await screen.findByText("Create purchase order (REQ-001)")).toBeTruthy();
    expect(screen.getByText("AI generated")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Set ready" }));
    fireEvent.click(await screen.findByRole("button", { name: /OK/ }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/cases/c1/status")).toBe(true));
    expect(calls.find((c) => c.method === "POST")!.body).toEqual({ status: "ready" });
    expect(await screen.findByRole("button", { name: "Back to draft" })).toBeTruthy();
  });

  it("saves edits through PATCH with parsed test data", async () => {
    const calls = mockFetch({
      "GET /cases/c1": () => ({ body: base }),
      "GET /cases/c1/revisions": () => ({ body: [] }),
      "GET /versions/v1/requirements": () => ({ body: [] }),
      "GET /suts/s1/graph": () => ({ body: { nodes: [], edges: [] } }),
      "PATCH /cases/c1": () => ({ body: { ...base, revision: 2 } }),
    });
    renderPage(<CasePage />, { path: "/cases/:caseId", route: "/cases/c1" });
    const expected = await screen.findByLabelText("Expected result");
    await waitFor(() => expect((expected as HTMLTextAreaElement).value).toBe("Submission refused"));
    fireEvent.change(expected, { target: { value: "Shows “Amount must be greater than 0”" } });
    fireEvent.click(screen.getByRole("button", { name: /Save/ }));
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    const body = calls.find((c) => c.method === "PATCH")!.body as Record<string, unknown>;
    expect(body.expected).toBe("Shows “Amount must be greater than 0”");
    expect(body.test_data).toEqual({ amount: 0 });
    expect(body.requirement_ids).toEqual(["r1"]);
  });
});
