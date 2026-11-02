import { fireEvent, render, screen } from "@testing-library/react";

import type { ApiEndpoint, IoParam, Suggestion } from "../api/types";
import { ApiSchemaView } from "./ApiSchema";
import { IoParamsTable } from "./IoParams";
import { describeSuggestion } from "./SuggestionList";

const params: IoParam[] = [
  {
    name: "amount_minor",
    display_name: "Amount",
    data_type: "money",
    required: true,
    location: "body",
    format: "integer in cents",
    example: "5000000",
    field: "PurchaseOrder.amount_minor",
  },
  { name: "state", data_type: "enum", enum_values: ["pending", "paid"], location: "response" },
];

describe("IoParamsTable", () => {
  it("shows name, type, required, location, format, field", () => {
    render(<IoParamsTable value={params} showLocation />);
    expect(screen.getByText("amount_minor")).toBeTruthy();
    expect(screen.getAllByText("Amount")).toHaveLength(2); // display name + type Amount (money)
    expect(screen.getByText("Enum")).toBeTruthy();
    expect(screen.getByText("pending / paid")).toBeTruthy();
    expect(screen.getByText("Required", { selector: ".ant-tag" })).toBeTruthy();
    expect(screen.getByText("Request body")).toBeTruthy();
    expect(screen.getByText("integer in cents")).toBeTruthy();
    expect(screen.getByText("e.g. 5000000")).toBeTruthy();
    expect(screen.getByText("PurchaseOrder.amount_minor")).toBeTruthy();
    expect(screen.queryByText("Add parameter")).toBeNull(); // read-only without onChange
  });

  it("deletes a row in editor mode", () => {
    const onChange = vi.fn();
    render(<IoParamsTable value={params} onChange={onChange} />);
    fireEvent.click(screen.getByLabelText("Delete state"));
    expect(onChange).toHaveBeenCalledWith([params[0]]);
    expect(screen.getByText("Add parameter")).toBeTruthy();
  });
});

describe("ApiSchemaView", () => {
  it("shows purpose, formats and field tables", () => {
    const api = {
      id: "a",
      method: "POST",
      path: "/sample/orders",
      description: "Create a purchase order and decide whether approval is required",
      request_schema: { body: {} },
      response_schema: { "201": { description: "Success" } },
      request_content_type: "application/json",
      io: {
        inputs: [params[0]],
        outputs: [params[1]],
        input_format: "Request body JSON object (application/json)",
        output_format: "HTTP 201, JSON object (application/json)",
      },
    } as ApiEndpoint;
    render(<ApiSchemaView api={api} />);
    expect(screen.getByText("Create a purchase order and decide whether approval is required")).toBeTruthy();
    expect(screen.getByText("Request body JSON object (application/json)")).toBeTruthy();
    expect(screen.getByText("HTTP 201, JSON object (application/json)")).toBeTruthy();
    expect(screen.getByText("amount_minor")).toBeTruthy();
    expect(screen.getByText("state")).toBeTruthy();
  });

  it("asks for a purpose when missing", () => {
    render(<ApiSchemaView api={{ id: "b", method: "GET", path: "/x" } as ApiEndpoint} />);
    expect(screen.getByText(/describe what this API does/)).toBeTruthy();
  });
});

describe("describeSuggestion io", () => {
  it("lists purpose, inputs and outputs by name", () => {
    const s = {
      id: "s",
      status: "pending",
      kind: "io",
      payload: { node_id: "n", node_name: "Approve purchase order", description: "Approve", inputs: [params[0]], outputs: [params[1]] },
    } as Suggestion;
    expect(describeSuggestion(s)).toBe("Add to action “Approve purchase order”: purpose: Approve; inputs amount_minor; outputs state");
  });
});

describe("describeSuggestion field rename", () => {
  it("says which field is renamed to the API name", () => {
    const s = {
      id: "r",
      status: "pending",
      kind: "field",
      payload: { node_id: "n", node_name: "PurchaseOrder", name: "amount_minor", rename_from: "amount", data_type: "integer" },
    } as Suggestion;
    expect(describeSuggestion(s)).toBe("“PurchaseOrder” field amount renamed to amount_minor (same as the API field, links kept), Integer");
  });
});
