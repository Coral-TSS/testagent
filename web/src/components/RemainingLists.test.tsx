import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { Input } from "antd";
import { useState } from "react";

import type { IoParam } from "../api/types";
import { AgentRunDrawer } from "./AgentRunDrawer";
import { VersionPage } from "../pages/VersionPage";
import { AgentRunsPage } from "../pages/AgentRunsPage";
import { AgentToolsPage } from "../pages/AgentToolsPage";
import { DefectPage } from "../pages/DefectPage";
import { RunPage } from "../pages/RunPage";
import { RunTasksModal } from "./RunTasksModal";
import { DefectsPage } from "../pages/DefectsPage";
import { ExecutionsPage } from "../pages/ExecutionsPage";
import { ModelPage } from "../pages/ModelPage";
import { ReportsPage } from "../pages/ReportsPage";
import { SutsPage } from "../pages/SutsPage";
import { VersionsPage } from "../pages/VersionsPage";
import { mockFetch, renderPage } from "../test/utils";
import { IoParamsTable } from "./IoParams";
import { SimpleCrud } from "./SimpleCrud";

afterEach(() => vi.unstubAllGlobals());

const counts = { total: 1, done: 1, passed: 1, failed: 0, error: 0, blocked: 0, skipped: 0 };
const summary = { ...counts, not_executed: 0, executed: 1, pass_rate: 1 };
const run = { id: "r1", task_id: "t1", task_name: "目标任务", version_id: "v1", version_name: "V1", sut_code: "FIRST", status: "passed", trigger: "manual", cancel_requested: false, created_at: "2026-11-07T09:00:00Z", counts };

describe("remaining list consistency", () => {
  it("counts SUTs without losing the create action", async () => {
    mockFetch({ "GET /suts": () => ({ body: [{ id: "s1", code: "FIRST", name: "First" }, { id: "s2", code: "OTHER", name: "其他" }] }) });
    renderPage(<SutsPage />);
    await waitFor(() => expect(screen.getByRole("status", { name: "被测系统数量" }).textContent).toBe("被测系统 (2)"));
    expect(screen.getByText("共 2 条")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /新建被测系统/ }));
    expect(await screen.findByRole("dialog")).toBeTruthy();
  });

  it("counts versions inside the selected SUT", async () => {
    mockFetch({ "GET /suts/s1/versions": () => ({ body: [{ id: "v1", name: "V1", status: "planning" }, { id: "v2", name: "V2", status: "planning" }] }) });
    renderPage(<VersionsPage />, { path: "/suts/:sutId/versions", route: "/suts/s1/versions" });
    await waitFor(() => expect(screen.getByRole("status", { name: "版本数量" }).textContent).toBe("版本 (2)"));
    expect(screen.getByText("共 2 条")).toBeTruthy();
  });

  it("loads the selected execution scope before the recent-record limit", async () => {
    mockFetch({ "GET /runs": ({ url }) => ({ body: url.includes("version_id=v1") && url.includes("sut_id=s1") ? [run] : [{ ...run, id: "other", version_id: "other" }] }) });
    renderPage(<ExecutionsPage />, { path: "/executions", route: "/executions?sut_id=s1&version_id=v1" });
    expect(await screen.findByText("已加载最近 1 条（最多 50 条）")).toBeTruthy();
    expect(screen.getByRole("link", { name: "目标任务" }).getAttribute("href")).toBe("/tasks/t1");
    expect(screen.queryByText("共 1 条")).toBeNull();
  });

  it("keeps report SUT filtering and labels capped report data honestly", async () => {
    mockFetch({
      "GET /reports": ({ url }) => ({ body: [{ id: "rep1", scope_type: "version", version_name: url.includes("sut_id=s1") ? "Target" : "其他", summary, created_at: "2026-11-07T09:00:00Z" }] }),
      "GET /suts": () => ({ body: [] }), "GET /suts/s1/versions": () => ({ body: [] }),
    });
    renderPage(<ReportsPage />, { path: "/reports", route: "/reports?sut_id=s1" });
    expect(await screen.findByText("已加载最近 1 条（最多 200 条）")).toBeTruthy();
    expect(screen.getByRole("link", { name: "版本 Target 报告" })).toBeTruthy();
    expect(screen.queryByText("共 1 条")).toBeNull();
  });

  it("does not turn failed defect loads into zero counts and can retry", async () => {
    let failed = true;
    mockFetch({ "GET /suts": () => ({ body: [] }), "GET /persons": () => ({ body: [] }), "GET /defects": () => failed ? { status: 503, body: { code: "UNAVAILABLE" } } : { body: [] } });
    renderPage(<DefectsPage />);
    expect(await screen.findByText("无法获取数量")).toBeTruthy();
    expect(screen.queryByText("暂无缺陷")).toBeNull();
    failed = false;
    fireEvent.click(screen.getByRole("button", { name: "重试缺陷" }));
    expect(await screen.findByText("已加载最近 0 条（最多 500 条）")).toBeTruthy();
  });

  it("marks Agent traces as recently loaded records", async () => {
    mockFetch({ "GET /agent/runs": () => ({ body: [{ id: "a1", purpose: "generate_cases", status: "succeeded", step_count: 2, created_at: "2026-11-07T09:00:00Z" }] }) });
    renderPage(<AgentRunsPage />);
    expect(await screen.findByText("已加载最近 1 条（最多 100 条）")).toBeTruthy();
    expect(screen.getByRole("status", { name: "Agent 追踪数量" }).textContent).toBe("Agent 追踪 (1)");
  });

  it("updates the Agent tools tab count when its list loads", async () => {
    const row = { id: "m1", scope: "global", sut_id: null, content: "Rule A", tags: [], enabled: true, source_correction_ids: [], created_by: "system", agent_run_id: null, created_at: "2026-11-07T09:00:00Z" };
    mockFetch({ "GET /agent/memories": () => ({ body: [row, { ...row, id: "m2", content: "Rule B" }] }) });
    renderPage(<AgentToolsPage />, { path: "/agent/tools", route: "/agent/tools?tab=memories" });
    expect(await screen.findByRole("tab", { name: "记忆 (2)" })).toBeTruthy();
    expect(screen.getByText("已加载最近 2 条（最多 500 条）")).toBeTruthy();
  });

  it("paginates shared registries while preserving the complete count", async () => {
    const rows = Array.from({ length: 65 }, (_, i) => ({ id: `p${i}`, name: `Endpoint ${i + 1}` }));
    renderPage(<SimpleCrud title="APIs" rows={rows} fields={<Input />} columns={[{ title: "名称", dataIndex: "name" }]} onCreate={async () => {}} />);
    expect(screen.getByText("共 65 条")).toBeTruthy();
    fireEvent.click(screen.getByTitle("2"));
    expect(await screen.findByText("Endpoint 65")).toBeTruthy();
    expect(screen.getByText("共 65 条")).toBeTruthy();
  });

  it("deletes the correct original parameter when editing the second page", async () => {
    function Page() {
      const [value, setValue] = useState<IoParam[]>(Array.from({ length: 51 }, (_, i) => ({ name: `param_${i + 1}`, data_type: "string", required: false })));
      return <IoParamsTable value={value} onChange={setValue} />;
    }
    renderPage(<Page />);
    expect(screen.getByText("共 51 条")).toBeTruthy();
    fireEvent.click(screen.getByTitle("2"));
    fireEvent.click(await screen.findByLabelText("删除 param_51"));
    expect(await screen.findByText("共 50 条")).toBeTruthy();
    expect(screen.getByDisplayValue("param_1")).toBeTruthy();
    expect(screen.queryByDisplayValue("param_51")).toBeNull();
  });

  it("updates model node counts under client-side search", async () => {
    mockFetch({
      "GET /suts/s1/graph": () => ({ body: { nodes: [{ id: "n1", name: "账户", kind: "entity", module_id: null, attributes: {}, deleted: false }, { id: "n2", name: "Payment", kind: "entity", module_id: null, attributes: {}, deleted: false }], edges: [] } }),
      "GET /suts/s1/modules": () => ({ body: [] }), "GET /suts/s1/fields": () => ({ body: [] }),
      "GET /suts/s1/links": () => ({ body: [] }), "GET /suts/s1/suggestions": () => ({ body: [] }),
    });
    renderPage(<ModelPage />, { path: "/suts/:sutId/model", route: "/suts/s1/model?view=list" });
    await screen.findByText("共 2 条");
    fireEvent.change(screen.getByPlaceholderText("按名称搜索"), { target: { value: "账户" } });
    expect(await screen.findByText("1 / 2 条")).toBeTruthy();
    expect(screen.queryByText("Payment")).toBeNull();
  });

});


it("removes the second-page responsibility without changing the first person", async () => {
  const responsible = Array.from({ length: 51 }, (_, i) => ({ person_id: `p${i + 1}`, person_name: `Person ${i + 1}`, role: "developer", inferred: false }));
  const defect = { id: "d1", code: "DEF-001", title: "示例", status: "open", severity: "minor", cause_category: "unknown", requirements: [], responsible, links: [] };
  const calls = mockFetch({
    "GET /defects/d1": () => ({ body: defect }),
    "GET /persons": () => ({ body: responsible.map((r) => ({ id: r.person_id, name: r.person_name, active: true })) }),
    "PUT /defects/d1/responsible": () => ({ body: { ...defect, responsible: responsible.slice(0, 50) } }),
  });
  renderPage(<DefectPage />, { path: "/defects/:defectId", route: "/defects/d1", motion: false });
  fireEvent.click(await screen.findByRole("button", { name: "变更" }));
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(within(dialog).getByTitle("2"));
  fireEvent.click(within(dialog).getByText("移除", { exact: true }));
  fireEvent.click(within(await screen.findByRole("tooltip")).getByRole("button", { name: "确定" }));
  await waitFor(() => expect(within(dialog).getByText("共 50 条")).toBeTruthy());
  fireEvent.click(within(dialog).getByRole("button", { name: "确定" }));
  await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
  expect(calls.find((c) => c.method === "PUT")!.body).toEqual(responsible.slice(0, 50).map(({ person_id, role }) => ({ person_id, role })));
});

it("keeps run execution numbering continuous on the second page", async () => {
  const executions = Array.from({ length: 51 }, (_, i) => ({ id: `e${i + 1}`, case_id: `c${i + 1}`, case_code: `TC-${i + 1}`, case_title: `Case ${i + 1}`, executor: "manual", status: "passed", created_at: "2026-11-07T09:00:00Z" }));
  mockFetch({ "GET /runs/r1": () => ({ body: { ...run, executor: "manual", not_ready: [], executions } }) });
  renderPage(<RunPage />, { path: "/runs/:runId", route: "/runs/r1" });
  await screen.findByText("共 51 条");
  fireEvent.click(screen.getByTitle("2"));
  const row = (await screen.findByRole("link", { name: "Case 51 (TC-51)" })).closest("tr")!;
  expect(within(row).getAllByRole("cell")[0].textContent).toBe("51");
});

it("does not label a failed task picker as zero tasks", async () => {
  mockFetch({ "GET /versions/v1/runnable-tasks": () => ({ status: 503, body: { code: "UNAVAILABLE" } }) });
  renderPage(<RunTasksModal open versionId="v1" onClose={() => {}} />);
  expect(await screen.findByText("无法获取数量")).toBeTruthy();
  expect(screen.queryByText("共 0 条")).toBeNull();
});


it("retains all Agent trace steps and retries an unavailable trace", async () => {
  let failed = true;
  const steps = Array.from({ length: 65 }, (_, i) => ({ type: "model", seq: i + 1, content: `Thought ${i + 1}`, ms: 1 }));
  mockFetch({ "GET /agent/runs/a1": () => failed ? { status: 503, body: { code: "UNAVAILABLE" } } : { body: { id: "a1", purpose: "generate_cases", status: "succeeded", steps } } });
  renderPage(<AgentRunDrawer runId="a1" onClose={() => {}} />);
  expect(await screen.findByText("无法获取数量")).toBeTruthy();
  failed = false;
  fireEvent.click(screen.getByRole("button", { name: "重试Agent 追踪步骤" }));
  expect(await screen.findByText("Thought 65")).toBeTruthy();
  expect(screen.getByText("共 65 条")).toBeTruthy();
});

it("counts the version change log and retains its last event", async () => {
  const history = Array.from({ length: 65 }, (_, i) => ({ action: `Change ${i + 1}`, actor: "reviewer", created_at: "2026-11-07T09:00:00Z", diff: null }));
  mockFetch({
    "GET /versions/v1": () => ({ body: { id: "v1", sut_id: "s1", name: "V1", status: "requirements_frozen" } }),
    "GET /versions/v1/requirements": () => ({ body: [] }),
    "GET /versions/v1/history": () => ({ body: history }),
    "GET /suts/s1/suggestions": () => ({ body: [] }),
  });
  renderPage(<VersionPage />, { path: "/versions/:versionId", route: "/versions/v1?tab=history" });
  expect(await screen.findByRole("tab", { name: "变更日志 (65)" })).toBeTruthy();
  expect(screen.getByText("Change 65")).toBeTruthy();
  expect(screen.getByRole("region", { name: "版本变更列表" })).toBeTruthy();
});
