import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import { mockFetch, renderPage } from "../test/utils";
import type { RunnableTask } from "../api/types";
import { FlowSteps } from "./FlowSteps";
import { RunTasksModal, selectable } from "./RunTasksModal";
import { progress } from "../test/navigationFixtures";

afterEach(() => vi.unstubAllGlobals());

const base: RunnableTask = {
  id: "t1",
  name: "Smoke",
  kind: "regression",
  executor: "agent",
  status: "ready",
  environment_id: "env1",
  environment_name: "Testing",
  ready_cases: 2,
  case_count: 2,
  active_run_id: null,
  script_gaps: [],
  script_gap_ids: [],
  runnable: true,
  reason: null,
};
const rows: RunnableTask[] = [
  base,
  { ...base, id: "t2", name: "Automated", executor: "automation", script_gaps: ["TC-002"], script_gap_ids: ["c2"] },
  { ...base, id: "t3", name: "Draft task", status: "draft", runnable: false, reason: "not_ready" },
  { ...base, id: "t4", name: "No env", environment_id: null, environment_name: null, runnable: false, reason: "no_environment" },
];

describe("RunTasksModal (#13)", () => {
  it("ticks runnable tasks, greys the rest with a reason and starts the chosen ones", async () => {
    const calls = mockFetch({
      "GET /versions/v1/runnable-tasks": () => ({ body: rows }),
      "POST /versions/v1/run-tasks": () => ({
        body: { started: [{ task_id: "t1", name: "Smoke", run_id: "r1" }], skipped: [{ task_id: "t2", name: "Automated", code: "MISSING_SCRIPTS", message: "x", related: ["TC-002"] }], version_testing: true },
      }),
    });
    const onDone = vi.fn();
    renderPage(<RunTasksModal open versionId="v1" startTesting onClose={() => {}} onDone={onDone} />);
    expect(await screen.findByText("Draft task")).toBeTruthy();
    expect(screen.getByText("Not set ready")).toBeTruthy();
    expect(screen.getByText("No environment")).toBeTruthy();
    expect(screen.getByTestId("run-tasks-gaps").textContent).toContain("1 case(s)");
    const button = await screen.findByRole("button", { name: "Run 2 task(s)" });
    fireEvent.click(button);
    await waitFor(() => expect(calls.some((c) => c.path === "/versions/v1/run-tasks")).toBe(true));
    expect(calls.find((c) => c.path === "/versions/v1/run-tasks")!.body).toEqual({ task_ids: ["t1", "t2"], set_ready: false, allow_missing_scripts: false, start_testing: true });
    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(await screen.findByText(/Started 1 task\(s\), 1 not started/)).toBeTruthy();
    expect(screen.getByText(/cases without script \(TC-002\)/)).toBeTruthy();
  });

  it("can only change the status, and run missing scripts anyway", async () => {
    const calls = mockFetch({
      "GET /versions/v1/runnable-tasks": () => ({ body: rows }),
      "POST /versions/v1/status": () => ({ body: {} }),
    });
    renderPage(<RunTasksModal open versionId="v1" startTesting onClose={() => {}} />);
    await screen.findByText("Draft task");
    fireEvent.click(screen.getByRole("button", { name: "Only change status" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/versions/v1/status")).toBe(true));
    expect(calls.find((c) => c.path === "/versions/v1/status")!.body).toEqual({ status: "testing" });
    expect(calls.some((c) => c.path === "/versions/v1/run-tasks")).toBe(false);
  });

  it("lets drafts be picked only with set-ready on", () => {
    expect(selectable(rows[2], false)).toBe(false);
    expect(selectable(rows[2], true)).toBe(true);
    expect(selectable(rows[3], true)).toBe(false);
    expect(selectable({ ...rows[2], case_count: 0, reason: "no_cases" }, true)).toBe(false);
  });

  it("opens from the flow bar's Run tasks step", async () => {
    mockFetch({ "GET /versions/v1/runnable-tasks": () => ({ body: rows }) });
    renderPage(<FlowSteps progress={{ ...progress, next: { key: "runs", title: "Runs", label: "Run tasks", path: "/versions/v1?tab=strategy", kind: "run_tasks", version_id: "v1" } }} />);
    fireEvent.click(screen.getByRole("button", { name: /Run tasks/ }));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("Draft task")).toBeTruthy();
  });
});
