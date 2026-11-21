import { fireEvent, screen, waitFor } from "@testing-library/react";

import type { ApiEndpoint } from "../api/types";
import { mockFetch, renderPage } from "../test/utils";
import { ApiPanel } from "./ApiPanel";

const row = {
  id: "a1",
  method: "POST",
  path: "/sample/orders",
  name: "Create purchase order",
  description: "创建订单",
  request_schema: { body: { type: "object" } },
  response_schema: null,
  io: { inputs: [{ name: "amount", data_type: "money", required: true }], outputs: [] },
} as ApiEndpoint;

afterEach(() => vi.unstubAllGlobals());

it("saves the description and the field table from one button", async () => {
  const calls = mockFetch({ "PATCH /apis/a1": () => ({ body: row }) });
  renderPage(<ApiPanel sutId="s1" row={row} onClose={() => {}} />, { motion: false });
  expect(screen.getByDisplayValue("/sample/orders")).toBeTruthy();
  expect(screen.queryByRole("dialog")).toBeNull();
  fireEvent.change(screen.getByDisplayValue("创建订单"), { target: { value: "创建并审批" } });
  fireEvent.click(screen.getByRole("tab", { name: "输入输出" }));
  expect(screen.getByDisplayValue("amount")).toBeTruthy();
  fireEvent.click(screen.getByRole("tab", { name: "高级" }));
  expect(screen.getByDisplayValue(/request/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "保存" }));
  await waitFor(() => expect(calls.some((call) => call.method === "PATCH")).toBe(true));
  const body = calls.find((call) => call.method === "PATCH")!.body as { path: string; description: string; request_fields: { name: string }[] };
  expect(body.path).toBe("/sample/orders");
  expect(body.description).toBe("创建并审批");
  expect(body.request_fields.map((item) => item.name)).toEqual(["amount"]);
});
