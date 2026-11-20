import { fireEvent, screen, waitFor } from "@testing-library/react";

import { review } from "../test/navigationFixtures";
import { mockFetch, renderPage } from "../test/utils";
import { ModelReviewPage } from "./ModelReviewPage";

describe("ModelReviewPage", () => {
  it("shows entities, relations both ways, actions, coverage and saves a review mark", async () => {
    const calls = mockFetch({
      "GET /suts/s1/model-review": () => ({ body: review }),
      "PUT /suts/s1/model-review/marks": () => ({ body: { reviewed: true } }),
    });
    renderPage(<ModelReviewPage />, { path: "/suts/:sutId/review", route: "/suts/s1/review" });
    expect(await screen.findByText("模型评审：Procurement system (PROC)")).toBeTruthy();
    expect(screen.getByText("PurchaseOrder belongs to Supplier (N:1, 外键 PurchaseOrder.supplier_id)")).toBeTruthy();
    expect(screen.getByText("Supplier supplies PurchaseOrder")).toBeTruthy();
    expect(screen.getByText("枚举 (draft / done)")).toBeTruthy();
    expect(screen.getByText("POST /orders/{id}/submit")).toBeTruthy();
    expect(screen.getByText("Create purchase order (REQ-001)").closest("a")?.getAttribute("href")).toBe("/versions/v1?req=r1");
    expect(screen.getAllByText("未覆盖").length).toBeGreaterThan(0);
    expect(screen.getByText("评审后又有变更，请重新评审")).toBeTruthy();
    expect(screen.getByText(/并不会接受任何 AI 建议/)).toBeTruthy();

    const boxes = screen.getAllByRole("checkbox", { name: "已评审" });
    fireEvent.click(boxes[boxes.length - 1]);
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ target_type: "action", target_id: "a1", reviewed: true, note: null });
  });

  it("filters to unreviewed elements", async () => {
    mockFetch({ "GET /suts/s1/model-review": () => ({ body: review }) });
    renderPage(<ModelReviewPage />, { path: "/suts/:sutId/review", route: "/suts/s1/review" });
    await screen.findByText("模型评审：Procurement system (PROC)");
    fireEvent.click(screen.getByText("未评审"));
    expect(screen.queryByRole("link", { name: "PurchaseOrder" })).toBeNull();
    expect(screen.getByRole("link", { name: "Supplier" })).toBeTruthy();
  });
});
