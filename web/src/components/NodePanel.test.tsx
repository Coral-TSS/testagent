import { fireEvent, screen, waitFor } from "@testing-library/react";

import { mockFetch, renderPage } from "../test/utils";
import { NodePanel } from "./NodePanel";

const entity = {
  id: "e1",
  name: "PurchaseOrder",
  kind: "entity",
  description: "订单",
  module_id: null,
  attributes: { conditions: [{ text: "金额为正" }], states: [], constraints: [] },
  apis: [],
  edges: [],
  links: [],
  fields: [],
  data_schema: { id: "string" },
};

afterEach(() => vi.unstubAllGlobals());

it("stages a field and saves it only from the footer", async () => {
  const calls = mockFetch({
    "GET /nodes/e1": () => ({ body: entity }),
    "GET /nodes/e1/references": () => ({ body: [{ type: "requirement", id: "r1", label: "REQ-001 下单" }] }),
    "GET /nodes/e1/fields": () => ({ body: [] }),
    "GET /suts/s1/apis": () => ({ body: [] }),
    "GET /suts/s1/fields": () => ({ body: [] }),
    "GET /suts/s1/links": () => ({ body: [] }),
    "PATCH /nodes/e1": () => ({ body: entity }),
  });
  renderPage(<NodePanel sutId="s1" nodeId="e1" modules={[]} allNodes={[]} onClose={() => {}} onOpenNode={() => {}} />, { motion: false });
  expect(await screen.findByText("描述")).toBeTruthy();
  expect(screen.queryByText("description")).toBeNull();
  expect(screen.queryByRole("dialog")).toBeNull();
  fireEvent.click(screen.getByRole("tab", { name: "字段" }));
  fireEvent.click(screen.getByRole("button", { name: "添加一行" }));
  fireEvent.change(screen.getByPlaceholderText("amount_minor"), { target: { value: "amount" } });
  expect(calls.every((call) => call.method === "GET")).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "保存" }));
  await waitFor(() => expect(calls.some((call) => call.method === "POST" && call.path === "/nodes/e1/fields")).toBe(true));
  const created = calls.find((call) => call.method === "POST");
  expect(created?.body).toMatchObject({ name: "amount", data_type: "string", required: false });
  fireEvent.click(screen.getByRole("tab", { name: "被引用" }));
  expect(screen.getByText("需求")).toBeTruthy();
  expect(screen.getByText("REQ-001 下单")).toBeTruthy();
});
