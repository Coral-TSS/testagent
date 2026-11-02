import type { Link } from "../api/types";
import { cleanEffects, cleanPreconditions, preconditionRows } from "./ActionRules";
import { effectText, forwardText, linkText, preconditionText, reverseText } from "./links";

const link = {
  id: "l1",
  from_node_id: "po",
  to_node_id: "sup",
  from_name: "PurchaseOrder",
  to_name: "Supplier",
  forward_name: "belongs to",
  reverse_name: "supplies",
  cardinality: "many_to_one",
  fk_field: "PurchaseOrder.supplier_id",
  required: true,
} as Link;

describe("link texts", () => {
  it("reads both directions with cardinality and foreign key", () => {
    expect(forwardText(link)).toBe("PurchaseOrder belongs to Supplier");
    expect(reverseText(link)).toBe("Supplier supplies PurchaseOrder");
    expect(linkText(link)).toBe("PurchaseOrder belongs to Supplier (N:1, foreign key PurchaseOrder.supplier_id)");
    expect(linkText({ ...link, cardinality: "many_to_many", fk_field: null, via_name: "OrderLine" })).toBe(
      "PurchaseOrder belongs to Supplier (M:N, junction entity OrderLine)",
    );
  });

  it("formats preconditions and effects", () => {
    expect(preconditionText({ field: "PurchaseOrder.state", op: "eq", value: "pending" })).toBe("PurchaseOrder.state == pending");
    expect(preconditionText({ field: "PurchaseOrder.state", op: "in", value: ["a", "b"] })).toBe("PurchaseOrder.state ∈ a | b");
    expect(preconditionText({ text: "The approver is not the submitter" })).toBe("The approver is not the submitter");
    expect(effectText({ kind: "set_field", field: "PurchaseOrder.state", values: ["approved", "rejected"] })).toBe(
      "PurchaseOrder.state → approved | rejected",
    );
    expect(effectText({ kind: "create_object", entity: "Payment", when: "Success" })).toBe("Create object Payment (Success)");
    expect(effectText({ kind: "create_link", link_id: "l1" }, new Map([["l1", "Payment pays PurchaseOrder"]]))).toBe(
      "Create link Payment pays PurchaseOrder",
    );
  });
});

describe("action rule form values", () => {
  it("cleans rows into the API body", () => {
    expect(
      cleanPreconditions([
        { attribute_id: "f1", op: "eq", value: "pending", message: "" },
        { attribute_id: "f1", op: "in", value_list: ["a", "b"] },
        { attribute_id: "f2", op: "not_null", value: "x" },
        { text: "  Manual condition " },
        {} as never,
      ]),
    ).toEqual([
      { attribute_id: "f1", op: "eq", value: "pending", message: null, text: null },
      { attribute_id: "f1", op: "in", value: ["a", "b"], message: null, text: null },
      { attribute_id: "f2", op: "not_null", value: null, message: null, text: null },
      { text: "Manual condition", message: null },
    ]);
    expect(
      cleanEffects([
        { kind: "set_field", attribute_id: "f1", values: ["paid"], node_id: "ignored" },
        { kind: "create_object", node_id: "n1" },
        { kind: "create_link", link_id: "l1", when: "Success" },
      ]),
    ).toEqual([
      { kind: "set_field", attribute_id: "f1", values: ["paid"], when: null, text: null },
      { kind: "create_object", node_id: "n1", when: null, text: null },
      { kind: "create_link", link_id: "l1", when: "Success", text: null },
    ]);
  });

  it("splits list values for the editor", () => {
    expect(preconditionRows([{ attribute_id: "f1", op: "in", value: ["a", "b"] }])).toEqual([
      { attribute_id: "f1", op: "in", value: null, value_list: ["a", "b"] },
    ]);
  });
});
