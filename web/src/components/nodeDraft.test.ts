import type { ApiEndpoint, NodeDetail } from "../api/types";
import { fillFromApis, toDraft } from "./nodeDraft";

const node = {
  id: "n1",
  name: "Submit",
  kind: "action",
  description: "",
  module_id: null,
  attributes: { conditions: [], states: [], constraints: [] },
  apis: [{ id: "a1" }],
  edges: [],
  links: [],
  inputs: [{ name: "note", data_type: "string" }],
  outputs: [],
  input_format: "",
  output_format: "",
} as unknown as NodeDetail;

const api = {
  id: "a1",
  method: "POST",
  path: "/orders",
  description: "创建订单",
  io: {
    inputs: [{ name: "amount", data_type: "money", required: true }],
    outputs: [{ name: "id", data_type: "string" }],
    input_format: "JSON",
    output_format: "JSON",
  },
} as ApiEndpoint;

describe("node draft", () => {
  it("merges API fields locally and leaves existing inputs", () => {
    const draft = toDraft(node, []);
    const filled = fillFromApis(draft, [api], false);
    expect(filled.addedIn).toBe(1);
    expect(filled.draft.inputs.map((row) => row.name)).toEqual(["note", "amount"]);
    expect(filled.draft.outputs.map((row) => row.name)).toEqual(["id"]);
    expect(filled.draft.input_format).toBe("JSON");
    expect(filled.draft.description).toBe("创建订单");
  });

  it("replaces inputs when rebuilding from APIs", () => {
    const filled = fillFromApis(toDraft(node, []), [api], true);
    expect(filled.draft.inputs.map((row) => row.name)).toEqual(["amount"]);
  });
});
