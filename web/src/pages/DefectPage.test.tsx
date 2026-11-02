import { fireEvent, screen, waitFor } from "@testing-library/react";

import { mockFetch, renderPage } from "../test/utils";
import { DefectPage } from "./DefectPage";
import { DefectsPage } from "./DefectsPage";

afterEach(() => vi.unstubAllGlobals());

const defect = {
  id: "d1",
  code: "DEF-001",
  sut_id: "s1",
  version_id: "v1",
  title: "Amount 0 can be submitted",
  description: "Repro",
  severity: "major",
  status: "open",
  cause_category: "unknown",
  suggested_cause: "development",
  created_by: "agent",
  agent_run_id: "run1",
  analysis: "Backend does not validate",
  responsible_manual: false,
  created_at: "2026-10-31T20:00:00+08:00",
  requirements: [{ id: "r1", code: "REQ-001", title: "Place order", version_id: "v1", inferred: true }],
  responsible: [],
  links: [{ target_type: "api", target_id: "a1", name: "POST /orders", code_ref: "orders.py:10" }],
  case: { id: "c1", code: "TC-001", title: "Amount is 0" },
  execution: { id: "e1", status: "failed", executor: "manual" },
};

describe("DefectPage", () => {
  it("shows the AI suggestion and adopts it with one click", async () => {
    const calls = mockFetch({
      "GET /defects/d1": () => ({ body: defect }),
      "GET /versions/v1/requirements": () => ({ body: [{ id: "r1", code: "REQ-001", title: "Place order" }] }),
      "GET /persons": () => ({ body: [] }),
      "POST /defects/d1/accept-suggestion": () => ({
        body: { ...defect, cause_category: "development", responsible: [{ person_id: "p1", person_name: "Lee Dev", role: "developer", inferred: true }] },
      }),
    });
    renderPage(<DefectPage />, { path: "/defects/:defectId", route: "/defects/d1" });
    expect(await screen.findByText("AI suggestion: Development issue")).toBeTruthy();
    expect(screen.getByText("Created by AI")).toBeTruthy();
    expect(screen.getByText("POST /orders · orders.py:10")).toBeTruthy();
    expect(screen.getByText("Environment issues and undetermined defects are not attributed to people")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Accept/ }));
    await waitFor(() => expect(calls.some((c) => c.path === "/defects/d1/accept-suggestion")).toBe(true));
    expect(await screen.findByText("Lee Dev (Developer) · inferred")).toBeTruthy();
    expect(screen.getByText("Attributed to the requirement’s developer")).toBeTruthy();
    // allowed transitions from open
    expect(screen.getByRole("button", { name: "Start work" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^Close$/ })).toBeNull();
  });
});

describe("DefectsPage", () => {
  it("lists defects with requirement, responsible and AI suggestion columns", async () => {
    const calls = mockFetch({
      "GET /suts": () => ({ body: [] }),
      "GET /persons": () => ({ body: [] }),
      "GET /defects": () => ({
        body: [{ ...defect, requirement_codes: ["REQ-001"], responsible_names: ["Lee Dev", "Zhao Dev"] }],
      }),
    });
    renderPage(<DefectsPage />, { path: "/defects", route: "/defects?status=open" });
    expect(await screen.findByText("Amount 0 can be submitted (DEF-001)")).toBeTruthy();
    expect(screen.getByText("Lee Dev, Zhao Dev")).toBeTruthy();
    expect(screen.getByText("AI suggestion: Development issue")).toBeTruthy();
    const list = calls.find((c) => c.path === "/defects")!;
    expect(list).toBeTruthy();
  });
});
