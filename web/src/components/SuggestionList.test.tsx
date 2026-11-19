import type { Suggestion } from "../api/types";
import { fieldLabel } from "./EntityFields";
import { SuggestionList, completionNote, defaultSelected, describeSuggestion } from "./SuggestionList";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { mockFetch, renderPage } from "../test/utils";

const base = { id: "s1", status: "pending" } as const;

describe("describeSuggestion", () => {
  it("shows names, never UUIDs", () => {
    const attr = { ...base, kind: "attribute", payload: { node_id: "b1d63985-uuid", node_name: "PurchaseOrder", attr: "constraints", text: "Amount > 0" } } as Suggestion;
    expect(describeSuggestion(attr)).toBe("添加到“PurchaseOrder”：约束：Amount > 0");
    const old = { ...base, kind: "attribute", payload: { node_id: "b1d63985-uuid", attr: "states", text: "paid" } } as Suggestion;
    expect(describeSuggestion(old)).not.toContain("b1d63985");
  });

  it("describes field suggestions", () => {
    const field = {
      ...base,
      kind: "field",
      payload: { node_id: "x", node_name: "PurchaseOrder", name: "currency", display_name: "Currency", data_type: "enum", unit: null },
    } as Suggestion;
    expect(describeSuggestion(field)).toBe("添加到“PurchaseOrder”新字段 currency（Currency）, 枚举");
    expect(fieldLabel({ name: "amount_minor", display_name: "Amount", node_name: "PurchaseOrder" })).toBe("PurchaseOrder.amount_minor (Amount)");
  });

  it("describes link and rules suggestions", () => {
    const link = {
      ...base,
      kind: "link",
      payload: {
        from_name: "Payment",
        to_name: "PurchaseOrder",
        forward_name: "belongs to",
        reverse_name: "has",
        cardinality: "many_to_one",
        fk_field: "Payment.order_id",
      },
    } as Suggestion;
    expect(describeSuggestion(link)).toBe("新建关系“Payment belongs to PurchaseOrder” / “PurchaseOrder has Payment”（N:1，外键 Payment.order_id）");
    const rules = {
      ...base,
      kind: "rules",
      payload: {
        node_id: "a",
        node_name: "Approve purchase order",
        preconditions: [{ field: "PurchaseOrder.state", op: "eq", value: "pending" }],
        effects: [{ kind: "set_field", field: "PurchaseOrder.state", values: ["approved", "rejected"] }],
      },
    } as Suggestion;
    expect(describeSuggestion(rules)).toBe(
      "添加到动作“Approve purchase order”：前置条件 PurchaseOrder.state == pending；效果 PurchaseOrder.state → approved | rejected",
    );
  });
});

describe("SuggestionList sources and batch accept (#6/#4)", () => {
  afterEach(() => vi.unstubAllGlobals());
  const items = [
    { id: "a", status: "pending", kind: "attribute", source: "requirement", requirement_code: "REQ-001", evidence: "50,000 or more need approval", payload: { node_name: "PurchaseOrder", attr: "constraints", text: "Approval at 50,000" } },
    { id: "b", status: "pending", kind: "field", source: "openapi", evidence: "POST /orders: currency", payload: { node_name: "PurchaseOrder", name: "currency", data_type: "string" } },
    { id: "c", status: "pending", kind: "attribute", source: "ai_inferred", payload: { node_name: "PurchaseOrder", attr: "states", text: "archived" } },
    { id: "d", status: "pending", kind: "link", source: "model_rule", payload: { from_name: "Payment", to_name: "PurchaseOrder", forward_name: "belongs to", reverse_name: "has" } },
    { id: "e", status: "pending", kind: "node", source: "ai_inferred", payload: { node_kind: "action", name: "Create order draft", similar_to: "Create purchase order", api: "POST /drafts" } },
  ] as Suggestion[];

  it("pre-selects sourced suggestions only and shows source tags", () => {
    expect(defaultSelected(items)).toEqual(["a", "b"]);
    renderPage(<SuggestionList sutId="s1" items={items} onChanged={() => {}} />);
    expect(screen.getByText("需求 REQ-001")).toBeTruthy();
    expect(screen.getByText("OpenAPI")).toBeTruthy();
    expect(screen.getByText("模型规则")).toBeTruthy();
    expect(screen.getAllByText("AI 推断")).toHaveLength(2);
    expect(screen.getByText("Basis: 50,000 or more need approval")).toBeTruthy();
    expect(screen.getByText("Possible duplicate: Create purchase order")).toBeTruthy();
    expect(screen.getByRole("button", { name: "接受所选（2）" })).toBeTruthy();
    fireEvent.click(screen.getByLabelText("仅 AI 推断"));
    expect(screen.queryByText("OpenAPI")).toBeNull();
  });

  it("accepts the selection in one call", async () => {
    const calls = mockFetch({
      "POST /suts/s1/suggestions/accept-batch": () => ({ body: { accepted: ["a"], skipped: [] } }),
    });
    const onChanged = vi.fn();
    renderPage(<SuggestionList sutId="s1" items={items} onChanged={onChanged} />);
    fireEvent.click(screen.getByLabelText(/选择 添加到“PurchaseOrder”新字段 currency/));
    fireEvent.click(screen.getByRole("button", { name: "接受所选（1）" }));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(calls[0].body).toEqual({ ids: ["a"] });
  });

  it("asks why before accepting an AI inference", async () => {
    const calls = mockFetch({ "POST /suggestions/c/accept": () => ({ body: { id: "c", status: "accepted" } }) });
    renderPage(<SuggestionList sutId="s1" items={items} onChanged={() => {}} />);
    fireEvent.click(screen.getAllByText("接受")[2]);
    const note = await screen.findByLabelText("为何正确");
    const ok = () => screen.getByRole("button", { name: "确定" }) as HTMLButtonElement;
    expect(ok().disabled).toBe(true);
    fireEvent.change(note, { target: { value: "ok" } });
    expect(ok().disabled).toBe(true);
    fireEvent.change(note, { target: { value: "Seen in the demo" } });
    await waitFor(() => expect(ok().disabled).toBe(false));
    expect(calls).toHaveLength(0);
    fireEvent.click(ok());
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].body).toEqual({ note: "Seen in the demo" });
  });

  it("summarises what the completion left out", () => {
    expect(
      completionNote({
        agent_run_id: "r",
        status: "succeeded",
        suggestions: [items[0]],
        skipped: 4,
        dropped: { duplicate_node: 0, duplicate_api: 1, duplicate_in_batch: 2, previously_rejected: 0, invalid: 0 },
      }),
    ).toBe("1 条新建议，排除 4 条（1 API 已绑定到动作，2 本批次中重复，1 条已在待处理中）");
    expect(completionNote({ agent_run_id: "r", status: "failed" })).toBeNull();
  });
});
