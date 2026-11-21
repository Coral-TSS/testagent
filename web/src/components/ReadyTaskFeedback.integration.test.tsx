import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useLocation } from "react-router-dom";

import { CasePage } from "../pages/CasePage";
import { mockFetch, renderPage } from "../test/utils";
import { CaseList } from "./CaseList";

afterEach(() => vi.unstubAllGlobals());

const base = {
  id: "c1", sut_id: "s1", code: "TC-001", title: "评审用例", priority: "P1", type_tag: "functional",
  scenario: "normal", mode: "manual", status: "draft", source: "human", revision: 1,
  origin_version_id: "v1", steps: [{ action: "提交", expected: "已接受" }], expected: "已接受",
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
    fireEvent.click(await screen.findByRole("button", { name: "设为就绪" }));
    fireEvent.click(await screen.findByRole("button", { name: /确定/ }));
    const panel = await screen.findByRole("region", { name: "任务 TC-001 的关联" });
    expect(within(panel).getByRole("link", { name: "打开任务 Smoke" }).getAttribute("href")).toBe("/tasks/t1");
    expect(within(panel).getByText("自动规则")).toBeTruthy();
    expect(within(panel).getByText(/added automatically/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "退回草稿" })).toBeTruthy();
  });

  it("explains an empty task setup and links to strategy without implying the case ran", async () => {
    mockFetch(caseRoutes(() => ({ ...base, status: "ready", task_binding: { ...feedback, linked: [] } })));
    renderPage(<CasePage />, { path: "/cases/:caseId", route: "/cases/c1" });
    const panel = await screen.findByRole("region", { name: "任务 TC-001 的关联" });
    expect(within(panel).getByText(/该系统还没有测试任务/)).toBeTruthy();
    expect(within(panel).getByRole("link", { name: "管理测试任务" }).getAttribute("href")).toBe("/versions/v1/tasks");
    expect(within(panel).getByText(/设为就绪不会开始执行/)).toBeTruthy();
  });

  it("warns when Ready was saved but a matching task was not confirmed", async () => {
    const value = { ...feedback, linked: [], sync_warning: true, not_added: [{ ...target, reason: "sync_unconfirmed" }] };
    mockFetch(caseRoutes(() => ({ ...base, status: "ready", task_binding: value })));
    renderPage(<CasePage />, { path: "/cases/:caseId", route: "/cases/c1" });
    const panel = await screen.findByRole("region", { name: "任务 TC-001 的关联" });
    expect(within(panel).getByText("就绪已保存；任务关联需要关注")).toBeTruthy();
    fireEvent.click(within(panel).getByText("为何未加入 1 个任务"));
    expect(within(panel).getByText(/保存规则并同步/)).toBeTruthy();
    expect(within(panel).getByRole("link", { name: "打开任务 Smoke" }).getAttribute("href")).toBe("/tasks/t1");
  });

  it("explains manual exclusions and shows version names when reviewing other tasks", async () => {
    const value = { ...feedback, linked: [], not_added: [{ ...target, reason: "manually_excluded" }, { ...target, id: "t2", name: "忙碌", version_name: "V2", reason: "task_running" }] };
    mockFetch(caseRoutes(() => ({ ...base, status: "ready", task_binding: value })));
    renderPage(<CasePage />, { path: "/cases/:caseId", route: "/cases/c1" });
    const panel = await screen.findByRole("region", { name: "任务 TC-001 的关联" });
    fireEvent.click(within(panel).getByText("为何未加入 2 个任务"));
    expect(within(panel).getByText(/已手工移除；自动规则不会再把它加回来/)).toBeTruthy();
    expect(within(panel).getByText(/任务正在运行；其用例列表不会被更改/)).toBeTruthy();
    expect(within(panel).getByText("版本 V2")).toBeTruthy();
  });

  it("shows per-case feedback in a successful batch and opens the task from the dialog", async () => {
    mockFetch({
      "GET /suts/s1/cases": () => ({ body: [{ ...base, requirement_codes: [], node_count: 0 }] }),
      "GET /suts/s1/environments": () => ({ body: [] }),
      "POST /cases/batch": () => ({ body: { action: "ready", ok: [{ id: "c1", code: "TC-001", task_binding: feedback }], skipped: [], failed: [], queued: 0 } }),
    });
    function Page() {
      const location = useLocation();
      return <><CaseList sutId="s1" /><output aria-label="当前页">{location.pathname}</output></>;
    }
    renderPage(<Page />, { path: "*", motion: false });
    await screen.findByText("TC-001");
    fireEvent.click(screen.getAllByRole("checkbox")[0]);
    fireEvent.click(screen.getByRole("button", { name: "设为就绪" }));
    fireEvent.click(await screen.findByRole("button", { name: /确定/ }));
    const dialog = await screen.findByRole("dialog");
    const panel = within(dialog).getByRole("region", { name: "任务 TC-001 的关联" });
    fireEvent.click(within(panel).getByRole("link", { name: "打开任务 Smoke" }));
    expect(screen.getByLabelText("当前页").textContent).toBe("/tasks/t1");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});
