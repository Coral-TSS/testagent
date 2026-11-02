import type { Suggestion } from "../api/types";
import { fieldLabel } from "./EntityFields";
import { describeSuggestion } from "./SuggestionList";

const base = { id: "s1", status: "pending" } as const;

describe("describeSuggestion", () => {
  it("shows names, never UUIDs", () => {
    const attr = { ...base, kind: "attribute", payload: { node_id: "b1d63985-uuid", node_name: "PurchaseOrder", attr: "constraints", text: "Amount > 0" } } as Suggestion;
    expect(describeSuggestion(attr)).toBe("Add to “PurchaseOrder”: Constraints: Amount > 0");
    const old = { ...base, kind: "attribute", payload: { node_id: "b1d63985-uuid", attr: "states", text: "paid" } } as Suggestion;
    expect(describeSuggestion(old)).not.toContain("b1d63985");
  });

  it("describes field suggestions", () => {
    const field = {
      ...base,
      kind: "field",
      payload: { node_id: "x", node_name: "PurchaseOrder", name: "currency", display_name: "Currency", data_type: "enum", unit: null },
    } as Suggestion;
    expect(describeSuggestion(field)).toBe("Add to “PurchaseOrder” new field currency (Currency), Enum");
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
    expect(describeSuggestion(link)).toBe("New link “Payment belongs to PurchaseOrder” / “PurchaseOrder has Payment” (N:1, foreign key Payment.order_id)");
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
      "Add to action “Approve purchase order”: precondition PurchaseOrder.state == pending; effect PurchaseOrder.state → approved | rejected",
    );
  });
});
