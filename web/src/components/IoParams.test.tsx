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
    expect(screen.getAllByText("Amount")).toHaveLength(1); // display_name stays English; type is 金额
    expect(screen.getByText("金额")).toBeTruthy();
    expect(screen.getByText("枚举")).toBeTruthy();
    expect(screen.getByText("pending / paid")).toBeTruthy();
    expect(screen.getByText("必填", { selector: ".ant-tag" })).toBeTruthy();
    expect(screen.getByText("请求体")).toBeTruthy();
    expect(screen.getByText("integer in cents")).toBeTruthy();
    expect(screen.getByText("例如 5000000")).toBeTruthy();
    expect(screen.getByText("PurchaseOrder.amount_minor")).toBeTruthy();
    expect(screen.queryByText("添加参数")).toBeNull(); // read-only without onChange
  });

  it("deletes a row in editor mode", () => {
    const onChange = vi.fn();
    render(<IoParamsTable value={params} onChange={onChange} />);
    fireEvent.click(screen.getByLabelText("删除 state"));
    expect(onChange).toHaveBeenCalledWith([params[0]]);
    expect(screen.getByText("添加参数")).toBeTruthy();
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
      response_schema: { "201": { description: "成功" } },
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
    expect(screen.getByText(/说明该 API 做什么/)).toBeTruthy();
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
    expect(describeSuggestion(s)).toBe("添加到动作“Approve purchase order”：用途：Approve；输入 amount_minor；输出 state");
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
    expect(describeSuggestion(s)).toBe("“PurchaseOrder”的字段 amount 已重命名为 amount_minor（与 API 字段一致，关系保留）, 整数");
  });
});
