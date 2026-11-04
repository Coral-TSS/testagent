import { fireEvent, screen, waitFor } from "@testing-library/react";

import { mockFetch, renderPage } from "../test/utils";
import { TaskPage } from "../pages/TaskPage";

afterEach(() => vi.unstubAllGlobals());

const task = {
  id: "t1",
  name: "Regression",
  kind: "regression",
  executor: "automation",
  status: "ready",
  version_id: "v1",
  version_name: "1.0",
  sut_id: "s1",
  environment_id: "env1",
  selector: null,
  schedule: null,
  case_count: 2,
  cases: [
    { id: "c1", code: "TC-001", title: "Sign in", status: "ready", mode: "automated" },
    { id: "c2", code: "TC-002", title: "Refund", status: "ready", mode: "manual" },
  ],
  script_gaps: [{ id: "c2", code: "TC-002", title: "Refund", automation_status: null }],
};

function routes(extra: Record<string, () => { status?: number; body?: unknown }> = {}) {
  return mockFetch({
    "GET /tasks/t1": () => ({ body: task }),
    "GET /tasks/t1/runs": () => ({ body: [] }),
    "GET /suts/s1/environments": () => ({ body: [] }),
    "GET /suts/s1/cases": () => ({ body: [] }),
    "GET /settings/general": () => ({ body: { timezone: "UTC" } }),
    "GET /versions/v1/tasks": () => ({ body: [{ id: "t9", name: "Agent smoke", executor: "agent", status: "ready" }] }),
    ...extra,
  });
}

describe("MissingScriptsModal (#18)", () => {
  it("turns a MISSING_SCRIPTS refusal into three choices; run anyway retries with the flag", async () => {
    let n = 0;
    const calls = routes({
      "POST /tasks/t1/run": () =>
        n++ === 0 ? { status: 409, body: { code: "MISSING_SCRIPTS", message: "no script", related: ["TC-002"] } } : { status: 201, body: { id: "r1" } },
    });
    renderPage(<TaskPage />, { path: "/tasks/:taskId", route: "/tasks/t1" });
    expect((await screen.findByTestId("gap-tag")).textContent).toContain("1 without script");
    fireEvent.click(screen.getByRole("button", { name: "Run now" }));
    expect(await screen.findByText("Some cases in this automated task have no automation script")).toBeTruthy();
    expect(screen.getByTestId("gap-list").textContent).toContain("TC-002 Refund");
    expect(screen.getByRole("button", { name: "Generate scripts (AI automation)" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Move to an agent task" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Skip these cases and run" }));
    await waitFor(() => expect(calls.filter((c) => c.path === "/tasks/t1/run")).toHaveLength(2));
    expect(calls.filter((c) => c.path === "/tasks/t1/run")[1].body).toEqual({ allow_missing_scripts: true });
  });

  it("generates scripts for the gaps, or moves them to an agent task", async () => {
    const calls = routes({
      "POST /versions/v1/automate": () => ({ body: { queued: 1, job_ids: [1] } }),
      "GET /tasks/t9": () => ({ body: { ...task, id: "t9", executor: "agent", cases: [{ id: "c5", code: "TC-005" }] } }),
      "PUT /tasks/t9/cases": () => ({ body: {} }),
      "PUT /tasks/t1/cases": () => ({ body: {} }),
    });
    renderPage(<TaskPage />, { path: "/tasks/:taskId", route: "/tasks/t1?missing=run" });
    fireEvent.click(await screen.findByRole("button", { name: "Generate scripts (AI automation)" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/versions/v1/automate")).toBe(true));
    expect(calls.find((c) => c.path === "/versions/v1/automate")!.body).toEqual({ case_ids: ["c2"], environment_id: "env1" });

    fireEvent.click(screen.getByTestId("gap-tag"));
    await screen.findByRole("button", { name: "Move to an agent task" });
    fireEvent.mouseDown(screen.getByLabelText("Target task"));
    fireEvent.click(await screen.findByText("Agent smoke"));
    fireEvent.click(screen.getByRole("button", { name: "Move to an agent task" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT" && c.path === "/tasks/t1/cases")).toBe(true));
    expect(calls.find((c) => c.path === "/tasks/t9/cases")!.body).toEqual({ case_ids: ["c5", "c2"] });
    expect(calls.find((c) => c.method === "PUT" && c.path === "/tasks/t1/cases")!.body).toEqual({ case_ids: ["c1"] });
  });
});
