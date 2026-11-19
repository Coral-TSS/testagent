import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { Version } from "../api/types";
import { mockFetch, renderPage } from "../test/utils";
import { StrategyTab } from "./StrategyTab";

afterEach(() => vi.unstubAllGlobals());

const version = { id: "v1", sut_id: "s1", name: "V1", status: "requirements_frozen" } as Version;
const run = {
  id: "run1", task_id: "t1", trigger: "manual", status: "running", cancel_requested: false,
  created_at: "2026-11-07T09:00:00+08:00", started_at: "2026-11-07T09:00:01+08:00", ended_at: null,
  counts: { total: 3, done: 1, passed: 1, failed: 0, error: 0, blocked: 0, skipped: 0 },
};
const task = {
  id: "t1", name: "Smoke", kind: "regression", executor: "agent", status: "running",
  environment_id: "env1", schedule: null, next_run_at: null, case_count: 3,
  source: "human", selector: null, script_gap_count: 0, latest_run: run,
};

function setup(tasks: () => { body: unknown; status?: number }) {
  mockFetch({
    "GET /versions/v1/strategy": () => ({ status: 404, body: { code: "NOT_FOUND" } }),
    "GET /versions/v1/tasks": tasks,
    "GET /suts/s1/environments": () => ({ body: [] }),
    "GET /versions/v1/requirements": () => ({ body: [] }),
    "GET /versions/v1/gaps": () => ({ body: [] }),
  });
  return renderPage(<StrategyTab version={version} onOpenRun={() => {}} />);
}

describe("version task run entry (#14)", () => {
  it("shows a latest-run link and progress per task, including queued and never-run states", async () => {
    setup(() => ({ body: [
      task,
      { ...task, id: "t2", name: "API", latest_run: { ...run, id: "run2", task_id: "t2", status: "queued", started_at: null } },
      { ...task, id: "t3", name: "回归", status: "done", latest_run: { ...run, id: "run3", task_id: "t3", status: "failed", counts: { ...run.counts, done: 3, failed: 2 } } },
      { ...task, id: "t4", name: "New task", status: "draft", latest_run: null },
    ] }));
    const link = await screen.findByRole("link", { name: "查看 Smoke 的最近一次执行" });
    expect(link.getAttribute("href")).toBe("/runs/run1");
    const row = link.closest("tr")!;
    expect(within(row).getByText("1/3 已处理")).toBeTruthy();
    const banner = screen.getByText("1 个任务运行中 · 1 个任务排队中");
    expect(banner.compareDocumentPosition(screen.getByText("测试策略")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("link", { name: "查看 API 的现场执行" }).getAttribute("href")).toBe("/runs/run2");
    expect(screen.getByText("等待启动")).toBeTruthy();
    expect(screen.getByText("存在失败")).toBeTruthy();
    expect(screen.getByText("尚未执行")).toBeTruthy();
  });

  it("refreshes progress and removes the live banner when a run finishes", async () => {
    let finished = false;
    setup(() => ({ body: [finished ? { ...task, status: "done", latest_run: { ...run, status: "passed", counts: { ...run.counts, done: 3, passed: 3 } } } : task] }));
    await screen.findByText("1/3 已处理");
    finished = true;
    await waitFor(() => expect(screen.getByText("3/3 已处理")).toBeTruthy(), { timeout: 8000 });
    expect(screen.getByText("通过")).toBeTruthy();
    expect(screen.queryByText("1 个任务运行中 · 0 个任务排队中")).toBeNull();
    expect(screen.getByRole("link", { name: "查看 Smoke 的最近一次执行" }).getAttribute("href")).toBe("/runs/run1");
  });

  it("discovers scheduled runs even if no task was active when the page opened", async () => {
    let started = false;
    setup(() => ({ body: [started ? task : { ...task, status: "ready", latest_run: null }] }));
    await screen.findByText("尚未执行");
    started = true;
    await waitFor(() => expect(screen.getByRole("link", { name: "查看 Smoke 的现场执行" })).toBeTruthy(), { timeout: 8000 });
    expect(screen.queryByText("尚未执行")).toBeNull();
  });

  it("offers retry instead of showing a failed request as an empty task list", async () => {
    let failed = true;
    setup(() => failed ? { status: 503, body: { code: "UNAVAILABLE", message: "离线" } } : { body: [task] });
    expect(await screen.findByText("测试任务执行信息无法刷新")).toBeTruthy();
    expect(screen.queryByText("暂无测试任务")).toBeNull();
    failed = false;
    fireEvent.click(screen.getByRole("button", { name: "重试任务" }));
    expect(await screen.findByRole("link", { name: "查看 Smoke 的最近一次执行" })).toBeTruthy();
    expect(screen.queryByText("测试任务执行信息无法刷新")).toBeNull();
  });

  it("retains the last run with a stale-data warning when a refresh fails", async () => {
    let failed = false;
    setup(() => failed ? { status: 503, body: { code: "UNAVAILABLE", message: "离线" } } : { body: [task] });
    await screen.findByRole("link", { name: "查看 Smoke 的最近一次执行" });
    failed = true;
    await screen.findByText("测试任务执行信息无法刷新", {}, { timeout: 8000 });
    expect(screen.getByText(/正在显示上次加载的任务和执行信息/)).toBeTruthy();
    const warning = screen.getByText("测试任务执行信息无法刷新");
    const banner = screen.getByText("1 个任务运行中 · 0 个任务排队中");
    expect(warning.compareDocumentPosition(banner) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("link", { name: "查看 Smoke 的最近一次执行" }).getAttribute("href")).toBe("/runs/run1");
    failed = false;
    fireEvent.click(screen.getByRole("button", { name: "重试任务" }));
    await waitFor(() => expect(screen.queryByText("测试任务执行信息无法刷新")).toBeNull());
  });
});
