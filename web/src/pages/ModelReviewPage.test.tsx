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
    expect(await screen.findByText("Model review: Procurement system (PROC)")).toBeTruthy();
    expect(screen.getByText("PurchaseOrder belongs to Supplier (N:1, foreign key PurchaseOrder.supplier_id)")).toBeTruthy();
    expect(screen.getByText("Supplier supplies PurchaseOrder")).toBeTruthy();
    expect(screen.getByText("Enum (draft / done)")).toBeTruthy();
    expect(screen.getByText("POST /orders/{id}/submit")).toBeTruthy();
    expect(screen.getByText("Create purchase order (REQ-001)").closest("a")?.getAttribute("href")).toBe("/versions/v1?req=r1");
    expect(screen.getAllByText("Not covered").length).toBeGreaterThan(0);
    expect(screen.getByText("Changed since review; please review again")).toBeTruthy();
    expect(screen.getByText(/does not accept any AI suggestion/)).toBeTruthy();

    const boxes = screen.getAllByRole("checkbox", { name: "Reviewed" });
    fireEvent.click(boxes[boxes.length - 1]);
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ target_type: "action", target_id: "a1", reviewed: true, note: null });
  });

  it("filters to unreviewed elements", async () => {
    mockFetch({ "GET /suts/s1/model-review": () => ({ body: review }) });
    renderPage(<ModelReviewPage />, { path: "/suts/:sutId/review", route: "/suts/s1/review" });
    await screen.findByText("Model review: Procurement system (PROC)");
    fireEvent.click(screen.getByText("Not reviewed"));
    expect(screen.queryByRole("link", { name: "PurchaseOrder" })).toBeNull();
    expect(screen.getByRole("link", { name: "Supplier" })).toBeTruthy();
  });
});
