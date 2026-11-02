import { render, screen } from "@testing-library/react";

import { StepItem } from "./AgentRunDrawer";
import { toolLabel, withLabels } from "./agentLabels";

const NODE = "b1d63985-0000-4000-8000-000000000001";

describe("StepItem", () => {
  it("renders model, tool and invalid-submit steps with readable tool labels", () => {
    render(
      <>
        <StepItem step={{ type: "model", seq: 1, content: "Thinking", tool_calls: [{ name: "search_nodes", args: {} }], ms: 12 }} />
        <StepItem step={{ type: "tool", tool: "search_nodes", status: "error", args: { q: "x" }, result: "Error" }} />
        <StepItem step={{ type: "submit_invalid", errors: [{ loc: "items.0.node_id", msg: "Node not found" }] }} />
      </>,
    );
    expect(screen.getByText("Model #1")).toBeTruthy();
    expect(screen.getByText("Search model nodes (search_nodes)", { selector: "code" })).toBeTruthy();
    expect(screen.getByText("Search model nodes (search_nodes)", { selector: ".ant-tag" })).toBeTruthy();
    expect(screen.getByText("Node not found")).toBeTruthy();
  });

  it("replaces UUIDs with names in validation messages", () => {
    render(
      <StepItem
        step={{ type: "submit_invalid", errors: [{ loc: "items", msg: `node_id ${NODE} is wrong` }] }}
        labels={{ [NODE]: "PurchaseOrder" }}
      />,
    );
    expect(screen.getByText(/node_id PurchaseOrder \[b1d63985\] is wrong/)).toBeTruthy();
  });
});

describe("agent labels", () => {
  it("labels tools and keeps unknown names", () => {
    expect(toolLabel("get_api_schema")).toBe("View API schema (get_api_schema)");
    expect(toolLabel("custom_tool")).toBe("custom_tool");
    expect(withLabels(`x ${NODE.toUpperCase()}`, { [NODE]: "PurchaseOrder" })).toBe("x PurchaseOrder [B1D63985]");
    expect(withLabels("no ids", undefined)).toBe("no ids");
  });
});
