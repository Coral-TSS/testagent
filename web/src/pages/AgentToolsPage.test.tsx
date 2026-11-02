import { fireEvent, screen, waitFor } from "@testing-library/react";

import { CorrectionButton } from "../components/CorrectionButton";
import { mockFetch, renderPage } from "../test/utils";
import { AgentToolsPage } from "./AgentToolsPage";

afterEach(() => vi.unstubAllGlobals());

const prompts = [
  { name: "system", kind: "system", versions: 0, active_version: null, updated_at: null, content: "You are TestAgent", is_default: true },
  { name: "generate_cases", kind: "entry", versions: 2, active_version: 2, updated_at: "2026-10-31T12:00:00Z", content: "At least one negative-amount case per requirement.", is_default: false },
];
const versions = [
  { id: "pv2", name: "generate_cases", version: 2, content: "At least one negative-amount case per requirement.", active: true, source_correction_ids: ["c1"], created_by: "agent:r1", note: "Generated from corrections", agent_run_id: "r1", created_at: "2026-10-31T12:00:00Z" },
  { id: "pv1", name: "generate_cases", version: 1, content: "", active: false, source_correction_ids: [], created_by: "system", note: "Built-in default", agent_run_id: null, created_at: "2026-10-31T12:00:00Z" },
];

describe("AgentToolsPage", () => {
  it("rolls a prompt back to an older version", async () => {
    const calls = mockFetch({
      "GET /agent/prompts": () => ({ body: prompts }),
      "GET /agent/prompts/system": () => ({ body: [] }),
      "GET /agent/prompts/generate_cases": () => ({ body: versions }),
      "POST /agent/prompts/generate_cases/versions/1/activate": () => ({ body: { ...versions[1], active: true } }),
    });
    renderPage(<AgentToolsPage />, { path: "/agent/tools", route: "/agent/tools" });
    expect(await screen.findByText("No versions yet: using the built-in default")).toBeTruthy();
    fireEvent.click(await screen.findByText("Case generation (generate_cases)"));
    expect(await screen.findByText("Active")).toBeTruthy();
    expect(screen.getByText("AI processed")).toBeTruthy();
    expect(screen.getByText("From 1 correction(s)")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Roll back to this version" }));
    fireEvent.click(await screen.findByRole("button", { name: /OK/ }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path.endsWith("/versions/1/activate"))).toBe(true));
  });

  it("lists memories with their source and disables one", async () => {
    const calls = mockFetch({
      "GET /agent/memories": () => ({
        body: [
          { id: "m1", scope: "sut", sut_id: "s1", sut_code: "procurement", content: "Amount boundaries must cover 0.01", tags: ["generate_cases"], enabled: true, source_correction_ids: ["c1"], created_by: "agent:r1", agent_run_id: "r1", created_at: "2026-10-31T12:00:00Z" },
        ],
      }),
      "PATCH /agent/memories/m1": () => ({ body: {} }),
    });
    renderPage(<AgentToolsPage />, { path: "/agent/tools", route: "/agent/tools?tab=memories" });
    expect(await screen.findByText("Amount boundaries must cover 0.01")).toBeTruthy();
    expect(screen.getByText("procurement")).toBeTruthy();
    expect(screen.getByText("Case generation")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Correct" }).getAttribute("href")).toBe("/agent/tools?tab=corrections&id=c1");
    fireEvent.click(screen.getByRole("switch"));
    await waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ enabled: false }));
  });

  it("shows corrections with digest results and retries a failed one", async () => {
    const calls = mockFetch({
      "GET /corrections": () => ({
        body: [
          { id: "c1", target_type: "case", target_id: "k1", target_label: "Case TC-001 amount", content: "Boundary\nall three points", author: "local-user", kind: "correction", status: "processed", attempts: 1, error: null, agent_run_id: "r1", outputs: { memory_ids: ["m1"], prompt_versions: [{ name: "generate_cases", version: 2, id: "pv2" }] }, created_at: "2026-10-31T12:00:00Z", sut_code: "procurement" },
          { id: "c2", target_type: "task_run", target_id: "run1", target_label: "Run of task Smoke", content: "Missed approver self-approval", author: "local-user", kind: "omission", status: "failed", attempts: 2, error: "MODEL_UNAVAILABLE: no model configured", agent_run_id: null, outputs: {}, created_at: "2026-10-31T12:00:00Z", sut_code: "procurement" },
        ],
      }),
      "POST /corrections/c2/reprocess": () => ({ body: {} }),
    });
    renderPage(<AgentToolsPage />, { path: "/agent/tools", route: "/agent/tools?tab=corrections" });
    expect(await screen.findByText("Case TC-001 amount")).toBeTruthy();
    expect(screen.getByText("Memory 1 item(s) generate_cases v2")).toBeTruthy();
    expect(screen.getByText("Missed test")).toBeTruthy();
    expect(screen.getByText("MODEL_UNAVAILABLE: no model configured")).toBeTruthy();
    fireEvent.click(screen.getAllByRole("button", { name: "Process again" })[1]);
    await waitFor(() => expect(calls.some((c) => c.path === "/corrections/c2/reprocess")).toBe(true));
  });

  it("registers a skill without loading it", async () => {
    const calls = mockFetch({
      "GET /agent/skills": () => ({ body: [] }),
      "POST /agent/skills": () => ({ status: 201, body: { id: "s1" } }),
    });
    renderPage(<AgentToolsPage />, { path: "/agent/tools", route: "/agent/tools?tab=skills" });
    expect(await screen.findByText(/never loaded or executed/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Register skill" }));
    fireEvent.change(await screen.findByLabelText("Name"), { target: { value: "jira-export" } });
    fireEvent.click(screen.getByRole("button", { name: /OK/ }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({ name: "jira-export" }));
  });
});

describe("CorrectionButton", () => {
  it("submits the raw text verbatim as a post-run omission", async () => {
    const calls = mockFetch({
      "GET /corrections": () => ({ body: [] }),
      "POST /corrections": () => ({ status: 201, body: { id: "c9" } }),
    });
    renderPage(<CorrectionButton targetType="task_run" targetId="run1" kind="omission" />);
    fireEvent.click(screen.getByRole("button", { name: "Report missed test" }));
    const raw = "  Missed: an approver approving their own order \n";
    fireEvent.change(await screen.findByLabelText("Correction"), { target: { value: raw } });
    fireEvent.click(screen.getByRole("button", { name: "Submit missed test" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(calls.find((c) => c.method === "POST")!.body).toEqual({ target_type: "task_run", target_id: "run1", content: raw, kind: "omission" });
  });
});
