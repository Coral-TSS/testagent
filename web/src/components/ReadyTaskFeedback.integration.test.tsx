import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useLocation } from "react-router-dom";

import { CasePage } from "../pages/CasePage";
import { mockFetch, renderPage } from "../test/utils";
import { CaseList } from "./CaseList";

afterEach(() => vi.unstubAllGlobals());

const base = {
  id: "c1", sut_id: "s1", code: "TC-001", title: "Review case", priority: "P1", type_tag: "functional",
  scenario: "normal", mode: "manual", status: "draft", source: "human", revision: 1,
  origin_version_id: "v1", steps: [{ action: "Submit", expected: "Accepted" }], expected: "Accepted",
  test_data: {}, requirements: [], nodes: [], tasks: [], updated_at: "2026-11-07T09:00:00Z",
};
const target = { id: "t1", name: "Smoke", version_id: "v1", version_name: "V1", status: "draft", source: "rule", reason: "Case became ready, added automatically (P1)" };
const feedback = { case_id: "c1", code: "TC-001", sut_id: "s1", version_id: "v1", linked: [target], not_added: [], sync_warning: false };

function caseRoutes(current: () => unknown) {
  return {
    "GET /cases/c1": () => ({ body: current() }),
    "GET /cases/c1/revisions": () => ({ body: [] }),
    "GET /suts/s1/environments": () => ({ body: [] }),
    "GET /versions/v1/requirements": () => ({ body: [] }),
    "GET /suts/s1/graph": () => ({ body: { nodes: [], edges: [] } }),
  };
}

describe("Ready task feedback (#11)", () => {
  it("shows actual task links after a person confirms Ready", async () => {
    let current: unknown = base;
    mockFetch({
      ...caseRoutes(() => current),
      "POST /cases/c1/status": () => {
        current = { ...base, status: "ready", tasks: [{ ...target, seq: 1 }], task_binding: feedback };
        return { body: current };
      },
    });
    renderPage(<CasePage />, { path: "/cases/:caseId", route: "/cases/c1" });
    fireEvent.click(await screen.findByRole("button", { name: "Set ready" }));
    fireEvent.click(await screen.findByRole("button", { name: /OK/ }));
    const panel = await screen.findByRole("region", { name: "Task associations for TC-001" });
    expect(within(panel).getByRole("link", { name: "Open task Smoke" }).getAttribute("href")).toBe("/tasks/t1");
    expect(within(panel).getByText("Automatic rule")).toBeTruthy();
    expect(within(panel).getByText(/added automatically/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Back to draft" })).toBeTruthy();
  });

  it("explains an empty task setup and links to strategy without implying the case ran", async () => {
    mockFetch(caseRoutes(() => ({ ...base, status: "ready", task_binding: { ...feedback, linked: [] } })));
    renderPage(<CasePage />, { path: "/cases/:caseId", route: "/cases/c1" });
    const panel = await screen.findByRole("region", { name: "Task associations for TC-001" });
    expect(within(panel).getByText(/No tasks exist for this system yet/)).toBeTruthy();
    expect(within(panel).getByRole("link", { name: "Manage test tasks" }).getAttribute("href")).toBe("/versions/v1?tab=strategy");
    expect(within(panel).getByText(/Ready does not start a run/)).toBeTruthy();
  });

  it("warns when Ready was saved but a matching task was not confirmed", async () => {
    const value = { ...feedback, linked: [], sync_warning: true, not_added: [{ ...target, reason: "sync_unconfirmed" }] };
    mockFetch(caseRoutes(() => ({ ...base, status: "ready", task_binding: value })));
    renderPage(<CasePage />, { path: "/cases/:caseId", route: "/cases/c1" });
    const panel = await screen.findByRole("region", { name: "Task associations for TC-001" });
    expect(within(panel).getByText("Ready saved; task association needs attention")).toBeTruthy();
    fireEvent.click(within(panel).getByText("Why 1 task(s) were not added"));
    expect(within(panel).getByText(/Save rule and sync/)).toBeTruthy();
    expect(within(panel).getByRole("link", { name: "Open task Smoke" }).getAttribute("href")).toBe("/tasks/t1");
  });

  it("explains manual exclusions and shows version names when reviewing other tasks", async () => {
    const value = { ...feedback, linked: [], not_added: [{ ...target, reason: "manually_excluded" }, { ...target, id: "t2", name: "Busy", version_name: "V2", reason: "task_running" }] };
    mockFetch(caseRoutes(() => ({ ...base, status: "ready", task_binding: value })));
    renderPage(<CasePage />, { path: "/cases/:caseId", route: "/cases/c1" });
    const panel = await screen.findByRole("region", { name: "Task associations for TC-001" });
    fireEvent.click(within(panel).getByText("Why 2 task(s) were not added"));
    expect(within(panel).getByText(/Removed manually; automatic rules will not add it back/)).toBeTruthy();
    expect(within(panel).getByText(/Task is running; its case list is not changed/)).toBeTruthy();
    expect(within(panel).getByText("Version V2")).toBeTruthy();
  });

  it("shows per-case feedback in a successful batch and opens the task from the dialog", async () => {
    mockFetch({
      "GET /suts/s1/cases": () => ({ body: [{ ...base, requirement_codes: [], node_count: 0 }] }),
      "GET /suts/s1/environments": () => ({ body: [] }),
      "POST /cases/batch": () => ({ body: { action: "ready", ok: [{ id: "c1", code: "TC-001", task_binding: feedback }], skipped: [], failed: [], queued: 0 } }),
    });
    function Page() {
      const location = useLocation();
      return <><CaseList sutId="s1" /><output aria-label="Current page">{location.pathname}</output></>;
    }
    renderPage(<Page />, { path: "*", motion: false });
    await screen.findByText("TC-001");
    fireEvent.click(screen.getAllByRole("checkbox")[0]);
    fireEvent.click(screen.getByRole("button", { name: "Set ready" }));
    fireEvent.click(await screen.findByRole("button", { name: /OK/ }));
    const dialog = await screen.findByRole("dialog");
    const panel = within(dialog).getByRole("region", { name: "Task associations for TC-001" });
    fireEvent.click(within(panel).getByRole("link", { name: "Open task Smoke" }));
    expect(screen.getByLabelText("Current page").textContent).toBe("/tasks/t1");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});
