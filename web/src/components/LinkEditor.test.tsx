import { fireEvent, screen, waitFor } from "@testing-library/react";

import type { EntityField, Link, ModelNode } from "../api/types";
import { mockFetch, renderPage } from "../test/utils";
import { LinkEditor, LinksTable } from "./LinkEditor";

const entities: ModelNode[] = [
  { id: "po", sut_id: "s", kind: "entity", name: "PurchaseOrder", attributes: {} },
  { id: "sup", sut_id: "s", kind: "entity", name: "Supplier", attributes: {} },
];
const fields = [
  { id: "f1", node_id: "po", node_name: "PurchaseOrder", name: "supplier_id", data_type: "reference", ref_node_name: "Supplier" },
] as EntityField[];
const link = {
  id: "l1",
  sut_id: "s",
  from_node_id: "po",
  to_node_id: "sup",
  from_name: "PurchaseOrder",
  to_name: "Supplier",
  forward_name: "belongs to",
  reverse_name: "supplies",
  forward_api_name: "supplier",
  reverse_api_name: "purchaseOrders",
  cardinality: "many_to_one",
  fk_attribute_id: "f1",
  fk_field: "PurchaseOrder.supplier_id",
  required: true,
} as Link;

describe("LinkEditor", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("previews both readings and saves the edited relation", async () => {
    const calls = mockFetch({ "PATCH /links/l1": () => ({ body: link }) });
    const onClose = vi.fn();
    renderPage(<LinkEditor sutId="s" open link={link} entities={entities} fields={fields} onClose={onClose} />);
    await waitFor(() => expect(screen.getByTestId("link-preview").textContent).toContain("PurchaseOrder belongs to Supplier / Supplier supplies PurchaseOrder"));
    expect(screen.getByTestId("link-preview").textContent).toContain("N:1");
    fireEvent.change(screen.getByDisplayValue("supplies"), { target: { value: "provides" } });
    await waitFor(() => expect(screen.getByTestId("link-preview").textContent).toContain("Supplier provides PurchaseOrder"));
    fireEvent.click(screen.getByText("Save"));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    const body = calls.find((c) => c.method === "PATCH")!.body as Record<string, unknown>;
    expect(Object.keys(body)).not.toContain("from_name");
    expect(body).toMatchObject({ reverse_name: "provides", forward_name: "belongs to", cardinality: "many_to_one", fk_attribute_id: "f1" });
  });

  it("lists relations with both directions, cardinality and key", () => {
    renderPage(<LinksTable links={[link]} onOpen={() => undefined} />);
    expect(screen.getByText("PurchaseOrder belongs to Supplier")).toBeTruthy();
    expect(screen.getByText("Supplier supplies PurchaseOrder")).toBeTruthy();
    expect(screen.getByText("N:1")).toBeTruthy();
    expect(screen.getByText("PurchaseOrder.supplier_id")).toBeTruthy();
    expect(screen.getByText("supplier / purchaseOrders")).toBeTruthy();
  });
});
