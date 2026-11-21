import { fireEvent, screen, waitFor } from "@testing-library/react";
import { useState } from "react";

import { api } from "../api/client";
import { mockFetch, renderPage } from "../test/utils";
import { CaseList } from "./CaseList";
import { ScopePreview } from "./ScopePreview";

const coverage = {
  version_id: "v1",
  sut_id: "s1",
  cases: 0,
  requirements: { total: 1, covered: 0, uncovered: [], items: [] },
  actions: { total: 0, covered: 0, uncovered: [], items: [] },
  by_priority: {},
  by_type: {},
  by_scenario: {},
};

const manifest = {
  requirement: { id: "r1", code: "REQ-001", title: "Approve" },
  depth: 1,
  nodes: [{ id: "n1", kind: "action", name: "Approve purchase order", origin: "seed" }],
  fields: [{ id: "f1", entity: "PurchaseOrder", name: "amount", origin: "expanded" }],
  links: [],
  apis: [],
  targets: [{ id: "field:f1", type: "field", entity: "PurchaseOrder", name: "amount" }],
};

function scope(extra: Record<string, unknown> = {}) {
  return { id: "sc1", requirement_id: "r1", depth: 1, edited: false, confirmed: false, manifest, ...extra };
}

function routes(scopeBody: { scopes: object[] } = { scopes: [scope()] }) {
  return {
    "GET /suts/s1/cases": () => ({ body: [] }),
    "GET /versions/v1/requirements": () => ({ body: [{ id: "r1", code: "REQ-001", title: "Approve" }] }),
    "GET /versions/v1/coverage": () => ({ body: coverage }),
    "GET /agent/config": () => ({ body: { auto_automate: false, configured: false, temperature: 0, timeout_s: 30, max_steps: 8 } }),
    "GET /suts/s1/environments": () => ({ body: [] }),
    "GET /versions/v1/automation": () => ({ body: { jobs: [] } }),
    "GET /versions/v1/case-gen/chains": () => ({ body: { chains: [] } }),
    "GET /suts/s1/nodes": () => ({ body: [{ id: "n2", kind: "entity", name: "Supplier" }] }),
    "POST /versions/v1/case-gen/scope": () => ({ body: scopeBody }),
    "PUT /versions/v1/case-gen/scope": (init: RequestInit) => {
      const body = JSON.parse(String(init.body)) as { depth?: number; recompute?: boolean; remove?: { id: string }[]; add?: { id: string; kind: string }[] };
      const fields = body.remove?.length ? [] : manifest.fields;
      const nodes = body.add?.length
        ? [...manifest.nodes, { id: body.add[0].id, kind: body.add[0].kind, name: "Supplier", origin: "manual" }]
        : manifest.nodes;
      return { body: { scopes: [scope({ depth: body.depth ?? 1, confirmed: false, manifest: { ...manifest, depth: body.depth ?? 1, fields, nodes } })] } };
    },
    "POST /versions/v1/case-gen/scope/confirm": () => ({ body: { scopes: [scope({ confirmed: true })] } }),
    "POST /versions/v1/cases/generate": () => ({ body: { agent_run_id: "ar1", status: "succeeded", cases: [] } }),
  };
}

function PreviewHarness() {
  const [ready, setReady] = useState(false);
  return (
    <>
      <ScopePreview versionId="v1" sutId="s1" requirementIds={["r1"]} onReady={setReady} />
      <button type="button" disabled={!ready} onClick={() => api("/versions/v1/cases/generate", { method: "POST", body: { requirement_ids: ["r1"] } })}>
        生成
      </button>
    </>
  );
}

describe("case generation scope preview", () => {
  it("edits depth and rows, then generates only after confirmation", async () => {
    const calls = mockFetch(routes());
    renderPage(<PreviewHarness />);
    expect(await screen.findByText("Approve purchase order")).toBeTruthy();
    expect(screen.getAllByText("PurchaseOrder.amount").length).toBeGreaterThan(0);
    expect((screen.getByRole("button", { name: "生成" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByTestId("remove-f1"));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT" && (c.body as { remove?: unknown[] }).remove?.length)).toBe(true));
    fireEvent.mouseDown(screen.getByLabelText("REQ-001 的范围深度"));
    fireEvent.click(await screen.findByText("0 只含已引用"));
    await waitFor(() =>
      expect(calls.some((c) => c.method === "PUT" && (c.body as { recompute?: boolean }).recompute && (c.body as { depth?: number }).depth === 0)).toBe(true),
    );
    fireEvent.mouseDown(screen.getByLabelText("REQ-001 加入对象"));
    fireEvent.click(await screen.findByText("实体 Supplier"));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT" && (c.body as { add?: unknown[] }).add?.length)).toBe(true));
    expect(await screen.findByText("Supplier")).toBeTruthy();
    const confirm = await screen.findByRole("button", { name: /确认范围/ });
    await waitFor(() => expect((confirm as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(confirm);
    await waitFor(() => expect((screen.getByRole("button", { name: "生成" }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole("button", { name: "生成" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/versions/v1/cases/generate")).toBe(true));
    const generated = calls.filter((c) => c.path === "/versions/v1/cases/generate");
    const confirmed = calls.filter((c) => c.path === "/versions/v1/case-gen/scope/confirm");
    expect(confirmed.length).toBe(1);
    expect(calls.indexOf(confirmed[0])).toBeLessThan(calls.indexOf(generated[0]));
  });

  it("blocks generation when a requirement has no structured refs", async () => {
    mockFetch(routes({
      scopes: [{
        id: null,
        requirement_id: "r1",
        depth: 1,
        edited: false,
        confirmed: false,
        message: "需求 REQ-001 没有结构化引用（节点、字段或链接）。请先在需求上挂上模型对象后再生成用例。",
        manifest: {
          requirement: { id: "r1", code: "REQ-001", title: "Approve" },
          depth: 1,
          blocked: true,
          message: "需求 REQ-001 没有结构化引用（节点、字段或链接）。请先在需求上挂上模型对象后再生成用例。",
          nodes: [],
          fields: [],
          links: [],
          apis: [],
          targets: [],
        },
      }],
    }));
    renderPage(<CaseList sutId="s1" versionId="v1" />);
    fireEvent.click(await screen.findByRole("button", { name: /AI 生成用例/ }));
    expect(await screen.findByText(/没有结构化引用/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "生成" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
