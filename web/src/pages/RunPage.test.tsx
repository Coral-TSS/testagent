import { screen, waitFor } from "@testing-library/react";

import { mockFetch, renderPage } from "../test/utils";
import { RunPage } from "./RunPage";
import { scheduleBody } from "./TaskPage";
import dayjs from "dayjs";

afterEach(() => vi.unstubAllGlobals());

const run = {
  id: "r1",
  task_id: "t1",
  task_name: "Smoke",
  version_id: "v1",
  sut_id: "s1",
  executor: "agent",
  trigger: "manual",
  status: "failed",
  cancel_requested: false,
  created_at: "2026-10-31T20:00:00+08:00",
  started_at: "2026-10-31T20:00:01+08:00",
  ended_at: "2026-10-31T20:01:00+08:00",
  counts: { total: 3, done: 3, passed: 1, failed: 1, error: 0, blocked: 1, skipped: 0 },
  not_ready: [{ id: "c9", code: "TC-009", title: "Draft", status: "draft" }],
  report_id: "rep1",
  executions: [
    { id: "e1", case_id: "c1", case_code: "TC-001", case_title: "Sign in", executor: "agent_browser", status: "passed", created_at: "x" },
    { id: "e2", case_id: "c2", case_code: "TC-002", case_title: "Place order", executor: "agent_browser", status: "failed", failed_assertion: "Wrong amount", created_at: "x" },
    { id: "e3", case_id: "c3", case_code: "TC-003", case_title: "Refund", executor: "manual", status: "blocked", created_at: "x" },
  ],
};

describe("RunPage", () => {
  it("shows progress, per-case results, not-ready cases and the report link", async () => {
    mockFetch({ "GET /runs/r1": () => ({ body: run }) });
    renderPage(<RunPage />, { path: "/runs/:runId", route: "/runs/r1" });
    expect(await screen.findByText("3/3")).toBeTruthy();
    expect(screen.getByText("Wrong amount")).toBeTruthy();
    expect(screen.getByText("Waiting for manual execution")).toBeTruthy();
    expect(screen.getByText("Record result")).toBeTruthy();
    expect(screen.getByText(/TC-009/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "View report" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Cancel run" })).toBeNull();
  });

  it("follows a live run over SSE and can cancel it", async () => {
    let current = { ...run, status: "running", report_id: null, counts: { ...run.counts, done: 1 }, executions: run.executions.slice(0, 1) };
    const calls = mockFetch({
      "GET /runs/r1": () => ({ body: current }),
      "GET /runs/r1/events": () => {
        current = { ...run, report_id: null };
        return { body: "" };
      },
      "POST /runs/r1/cancel": () => ({ body: { ...current, cancel_requested: true } }),
    });
    renderPage(<RunPage />, { path: "/runs/:runId", route: "/runs/r1" });
    expect(await screen.findByText("1/3")).toBeTruthy();
    await waitFor(() => expect(calls.some((c) => c.path === "/runs/r1/events")).toBe(true));
    expect(await screen.findByText("3/3")).toBeTruthy();
  });
});

describe("scheduleBody", () => {
  it("maps the schedule form", () => {
    expect(scheduleBody({ kind: "none" })).toBeNull();
    expect(scheduleBody({ kind: "cron", expr: " 0  1 * * * " })).toEqual({ type: "cron", expr: "0 1 * * *" });
    const at = dayjs("2026-11-01T09:00:00+08:00");
    expect(scheduleBody({ kind: "once", at })).toEqual({ type: "once", at: "2026-11-01T01:00:00.000Z" });
    expect(scheduleBody({ kind: "cron", expr: "" })).toBeNull();
    expect(scheduleBody({ kind: "cron", expr: "0 9 * * *", tz: "Asia/Shanghai" })).toEqual({ type: "cron", expr: "0 9 * * *", tz: "Asia/Shanghai" });
  });
});
