import { fireEvent, screen, waitFor } from "@testing-library/react";

import { mockFetch, renderPage } from "../test/utils";
import type { TestCase } from "../api/types";
import { CaseExecutionPanel, manualBody } from "./CaseExecutionPanel";

afterEach(() => vi.unstubAllGlobals());

const tc = { id: "c1", sut_id: "s1", status: "ready", code_path: null } as unknown as TestCase;

describe("CaseExecutionPanel", () => {
  it("debugs the case in the first environment and lists history", async () => {
    const calls = mockFetch({
      "GET /suts/s1/environments": () => ({ body: [{ id: "env1", sut_id: "s1", name: "测试中", base_url: "http://x" }] }),
      "GET /cases/c1/executions": () => ({
        body: [{ id: "e0", executor: "manual", status: "passed", created_at: "2026-10-31T18:00:00+08:00", environment_name: "测试中" }],
      }),
      "POST /cases/c1/debug": () => ({ body: { id: "e1", status: "passed" } }),
    });
    renderPage(<CaseExecutionPanel tc={tc} onAgentRun={() => {}} />);
    expect(await screen.findByText("2026-10-31 18:00:00")).toBeTruthy();
    expect(screen.getByText("手工")).toBeTruthy();
    const button = screen.getByRole("button", { name: "调试执行" });
    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(button);
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(calls.find((c) => c.method === "POST")!.body).toEqual({ environment_id: "env1", executor: "auto" });
  });

  it("shows needs-fix reason, draft path and the read-only code viewer", async () => {
    const broken = {
      ...tc,
      automation_status: "needs_fix",
      automation_note: "assert 422 == 201",
      automation_draft_path: "tests/REQ-001/test_TC-001.py",
      draft_abs_path: "D:/repo/runtime/repos/PROC/tests/REQ-001/test_TC-001.py",
    } as unknown as TestCase;
    mockFetch({
      "GET /suts/s1/environments": () => ({ body: [] }),
      "GET /cases/c1/executions": () => ({ body: [] }),
      "GET /cases/c1/code": () => ({
        body: { path: "tests/REQ-001/test_TC-001.py", abs_path: "D:/x/test_TC-001.py", repo_path: "D:/x", commit: "abcdef123", content: "def test_x():\n    pass\n" },
      }),
    });
    renderPage(<CaseExecutionPanel tc={broken} onAgentRun={() => {}} />);
    expect(screen.getByText(/自动化待修复/)).toBeTruthy();
    expect(screen.getByText("原因：assert 422 == 201")).toBeTruthy();
    expect(screen.getByText("D:/repo/runtime/repos/PROC/tests/REQ-001/test_TC-001.py")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "查看草稿" }));
    expect(await screen.findByLabelText("编号")).toBeTruthy();
    expect(screen.getByLabelText("编号").textContent).toContain("def test_x()");
  });

  it("shows the absolute script path of an automated case", async () => {
    const auto = { ...tc, code_path: "tests/REQ-001/test_TC-002.py", code_abs_path: "D:/abs/test_TC-002.py", code_commit: "fd04c30aa" } as unknown as TestCase;
    mockFetch({ "GET /suts/s1/environments": () => ({ body: [] }), "GET /cases/c1/executions": () => ({ body: [] }) });
    renderPage(<CaseExecutionPanel tc={auto} onAgentRun={() => {}} />);
    expect(screen.getByText("D:/abs/test_TC-002.py")).toBeTruthy();
    expect(screen.getByText(/将运行已绑定的 Git 版本/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "查看代码" })).toBeTruthy();
  });

  it("builds manual result bodies and rejects bad JSON", async () => {
    expect(await manualBody({ status: "failed", failed_assertion: " Should show ", actual_data: '{"amount":0}', duration_min: 1.5 }, [])).toEqual({
      body: { status: "failed", failed_assertion: "Should show", actual_data: { amount: 0 }, duration_ms: 90000, attachments: [] },
    });
    expect((await manualBody({ status: "passed", actual_data: "{bad" }, [])).error).toMatch("JSON");
    expect((await manualBody({ status: "passed", actual_data: "[1]" }, [])).error).toMatch(/对象|JSON 对象/);
  });

  it("offers the suspected-system-issue choices instead of a fix (#9)", async () => {
    const mismatch = {
      ...tc,
      origin_version_id: "v1",
      automation_status: "sut_mismatch",
      automation_note: "Expected 201, got 422",
      automation_draft_path: "tests/REQ-001/test_TC-001.py",
      draft_abs_path: "D:/repo/tests/REQ-001/test_TC-001.py",
      automation_failure: { kind: "assertion", cause: "sut", headline: "Expected 201, got 422", expected: "201", actual: "422", requirement_refs: [], next_actions: [], raw: "assert 422 == 201" },
    } as unknown as TestCase;
    const calls = mockFetch({
      "GET /suts/s1/environments": () => ({ body: [] }),
      "GET /cases/c1/executions": () => ({
        body: [{ id: "e9", executor: "pytest", status: "failed", suspected_cause: "sut", summary: { headline: "Expected 201, got 422" }, created_at: "2026-11-04T10:00:00+08:00" }],
      }),
      "POST /cases/c1/automation/confirm-sut-issue": () => ({ body: { execution: { id: "e10" }, defect: { id: "d1" } } }),
      "POST /cases/c1/automation/mark-script-issue": () => ({ body: {} }),
    });
    renderPage(<CaseExecutionPanel tc={mismatch} onAgentRun={() => {}} />);
    const box = screen.getByTestId("sut-mismatch");
    expect(box.textContent).toContain("疑似系统问题");
    expect(box.textContent).toContain("Expected 201, got 422");
    expect(screen.queryByText(/自动化待修复/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "绑定、记录并创建缺陷" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/cases/c1/automation/confirm-sut-issue")).toBe(true));
    expect(calls.find((c) => c.path === "/cases/c1/automation/confirm-sut-issue")!.body).toEqual({ action: "bind_and_record", create_defect: true });
    fireEvent.click(screen.getByRole("button", { name: "这是脚本问题" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/cases/c1/automation/mark-script-issue")).toBe(true));
    expect(await screen.findAllByText("疑似系统问题")).toBeTruthy();
  });
});
