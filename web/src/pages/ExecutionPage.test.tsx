import { screen, waitFor } from "@testing-library/react";

import { mockFetch, renderPage } from "../test/utils";
import { summarizeRawOutput } from "../components/RunReport";
import { describeTarget, ExecutionPage } from "./ExecutionPage";

beforeEach(() => {
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:shot"), revokeObjectURL: vi.fn() }));
});
afterEach(() => vi.unstubAllGlobals());

const execution = {
  id: "e1",
  case_id: "c1",
  case_code: "TC-001",
  case_title: "Amount 0 shows an error",
  sut_id: "s1",
  task_run_id: null,
  executor: "agent_browser",
  status: "failed",
  environment_name: "Test env",
  base_url: "http://127.0.0.1:8766/bug/",
  agent_run_id: "run1",
  executed_by: "agent:run1",
  failed_assertion: "Expected text to contain “Amount must be greater than 0”, got “Submitted successfully”",
  error: null,
  result: "Looks all right",
  test_data: { amount: 0 },
  duration_ms: 3200,
  created_at: "2026-10-31T19:00:00+08:00",
  ended_at: "2026-10-31T19:00:03+08:00",
  steps_recorded: [
    { seq: 1, action: "fill", target: { label: "Amount" }, value: "0", status: "ok", screenshot_sha: "aa", ms: 40 },
    { seq: 2, action: "assert", target: { role: "status" }, value: "Amount must be greater than 0", result: "got “Submitted successfully”", status: "failed", screenshot_sha: "bb", ms: 12 },
  ],
  artifacts: [
    { kind: "trace", name: "trace.zip", sha256: "tt" },
    { kind: "screenshot", name: "step-1.png", sha256: "aa" },
  ],
};

describe("ExecutionPage", () => {
  it("shows the verdict, failed assertion, steps with authenticated screenshots and the trace", async () => {
    mockFetch({
      "GET /executions/e1": () => ({ body: execution }),
      "GET /artifacts/aa": () => ({ body: "png" }),
      "GET /artifacts/bb": () => ({ body: "png" }),
    });
    renderPage(<ExecutionPage />, { path: "/executions/:executionId", route: "/executions/e1" });
    expect(await screen.findByText("Unmet assertions")).toBeTruthy();
    expect(screen.getByText(execution.failed_assertion)).toBeTruthy();
    expect(screen.getByText("failed")).toBeTruthy();
    expect(screen.getByText("1. Fill")).toBeTruthy();
    expect(screen.getByText("label “Amount”")).toBeTruthy();
    expect(screen.getByText("got “Submitted successfully”")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Download trace.zip" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Download step-1.png" })).toBeNull();
    await waitFor(() => expect(screen.getAllByRole("img", { name: /Step \d screenshot/ })).toHaveLength(2));
  });

  it("renders the pytest report: steps, requests, assertions with expected/actual, data, raw output", async () => {
    const pytestRun = {
      ...execution,
      executor: "pytest",
      agent_run_id: null,
      steps_recorded: [],
      artifacts: [],
      failed_assertion: "expected order['state'] equals 'pending', got 'approved'\n\ntests/x.py::test_a: assert ...",
      result: "F  [100%]\n1 failed in 0.5s",
      test_data: { amount_minor: 100 },
      report: {
        version: 1,
        tests: [
          {
            name: "tests/x.py::test_a",
            outcome: "failed",
            duration_ms: 812,
            requests: 1,
            checks: { total: 2, failed: 1 },
            data_keys: ["amount_minor", "title"],
            data_used: { amount_minor: 100 },
            data_missing: ["title"],
            failure: { type: "AssertionError", explain: "expected order['state'] equals 'pending', got 'approved'" },
            steps: [
              {
                name: "Step 1: create purchase order",
                status: "passed",
                source: "comment",
                checks: 1,
                events: [
                  { type: "request", seq: 1, method: "POST", url: "http://x/sample/orders", status: 201, ms: 12, request: '{"amount_minor": 100}', response: '{"state": "approved"}' },
                  { type: "check", seq: 2, name: "created.status == 201", assert: true, passed: true, expected: "201", actual: "201" },
                ],
              },
              {
                name: "Step 2: check state",
                status: "failed",
                source: "comment",
                checks: 1,
                events: [{ type: "check", seq: 3, name: "order['state'] == 'pending'", assert: true, passed: false, expected: "'pending'", actual: "'approved'", explain: "expected order['state'] equals 'pending', got 'approved'" }],
              },
            ],
          },
        ],
      },
    };
    mockFetch({ "GET /executions/e1": () => ({ body: pytestRun }) });
    renderPage(<ExecutionPage />, { path: "/executions/:executionId", route: "/executions/e1" });
    expect(await screen.findByTestId("run-report")).toBeTruthy();
    expect(screen.getByText("Assertion failed")).toBeTruthy();
    expect(screen.queryByText("Unmet assertions")).toBeNull(); // explained once, not twice
    expect(screen.getByText("Step 1: create purchase order")).toBeTruthy();
    expect(screen.getByText("POST")).toBeTruthy();
    expect(screen.getByText("http://x/sample/orders")).toBeTruthy();
    expect(screen.getByText("201", { selector: ".ant-tag" })).toBeTruthy();
    expect(screen.getByText("1/2 passed")).toBeTruthy();
    expect(screen.getAllByText("'approved'").length).toBeGreaterThan(0);
    expect(screen.getByText("amount_minor = 100")).toBeTruthy();
    expect(screen.getByText("title (not provided, script defaults used)")).toBeTruthy();
    expect(screen.getByText("Raw output (pytest)")).toBeTruthy();
  });

  it("summarizes old pytest output without a report", () => {
    const raw = ".  [100%]\r\n===== warnings summary =====\r\nnoise\r\n-- Docs: https://x\r\n1 passed, 1 warning in 1.14s\r\n";
    const out = summarizeRawOutput(raw);
    expect(out.summary).toBe("1 passed, 1 warning in 1.14s");
    expect(out.body).not.toContain("noise");
  });

  it("describes locator targets", () => {
    expect(describeTarget({ role: "button", name: "Submit" })).toBe("button “Submit”");
    expect(describeTarget({ selector: "#amount" })).toBe("#amount");
    expect(describeTarget(null)).toBe("");
  });
});
